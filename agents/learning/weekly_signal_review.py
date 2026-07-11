"""
Weekly Signal Review — PLAN_FUTURES item C (v4 P2.1 + P2.2 report).

P2.1: tiap Senin 00:10 UTC, hitung hit-rate 4h per sinyal dari predictive_log
      (resolved, era-H saja) lalu sesuaikan bobot di agent_signal_weights:
        hit_rate < 25% (n≥10) → weight −0.10 (floor 0.70)
        hit_rate > 60% (n≥10) → weight +0.10 (cap 1.50) — AKTIF setelah 4 minggu
        pertama (keputusan terkunci: lower-only dulu, hindari self-reinforcing).
      Bobot untuk sinyal yang BELUM pernah di-trade tetap hidup di scoring karena
      weight_updater menyemai cache dari baris DB regime='all' (lihat item C di
      weight_updater.update_weights).

P2.2: REPORT-ONLY — hit-rate per (agent, regime, direction) + rekomendasi apakah
      regime modifier ±5 di agents terkonfirmasi data. Keputusan penyesuaian
      modifier diambil manual di review 20 Jul (bagian SCHEDULE_FUTURES.md),
      bukan otomatis — mengubah modifier menyentuh scoring 3 agent sekaligus.

Endpoint: GET /predictive/signal_review (backend/app/api/v1/predictive.py).
Scheduler: dipanggil dari run_futures_loop tiap Senin 00:10-00:15 UTC.
"""

import json
import time
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.predictive_log import PredictiveLog
from app.models.signal_weight import AgentSignalWeight
from app.models.signal_weight_history import SignalWeightHistory
from agents.futures.weight_updater import (
    normalize_signal_key, FUTURES_AGENTS, DATA_ERA_EPOCH,
)

logger = structlog.get_logger(__name__)

WINDOW_DAYS      = 7
MIN_N            = 10      # sampel minimum per sinyal sebelum bobot boleh bergerak
LOW_HIT          = 0.25    # di bawah ini → turunkan bobot
HIGH_HIT         = 0.60    # di atas ini → naikkan bobot (setelah masa lower-only)
STEP             = 0.10
FLOOR, CAP       = 0.70, 1.50
# Keputusan terkunci: lower-only 4 minggu pertama era-H
RAISE_ENABLED_AFTER = DATA_ERA_EPOCH + 28 * 86400
MIN_RUN_GAP_SEC  = 20 * 3600   # guard dobel-run dalam window Senin yang sama

_last_review: dict = {
    "ran_at":        None,
    "window_start":  None,
    "resolved_rows": 0,
    "raises_enabled": False,
    "adjustments":   [],
    "regime_report": [],
}


def get_last_review() -> dict:
    """Hasil review terakhir (untuk endpoint) — {} berarti belum pernah jalan."""
    return dict(_last_review)


async def run_weekly_signal_review(force: bool = False) -> dict:
    """Jalankan review. Self-gating: tanpa sampel cukup = no-op yang aman."""
    global _last_review
    now = time.time()

    if not is_db_available():
        return {"ok": False, "reason": "db_unavailable"}
    if not force and _last_review["ran_at"] and (now - _last_review["ran_at"]) < MIN_RUN_GAP_SEC:
        return _last_review

    # Era-H filter WAJIB: prediksi pra-1783698144 dibuat oleh scoring lama.
    cutoff = max(DATA_ERA_EPOCH, now - WINDOW_DAYS * 86400)
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(PredictiveLog).where(
                PredictiveLog.agent.in_(FUTURES_AGENTS),
                PredictiveLog.resolved_at.is_not(None),
                PredictiveLog.scanned_at >= cutoff,
            )
        )).scalars().all())

    # ── Agregasi ──────────────────────────────────────────────────────────────
    sig_stats: dict[tuple, dict] = {}   # (agent, signal_key) → {n, hits}
    reg_stats: dict[tuple, dict] = {}   # (agent, regime, direction) → {n, hits}
    for r in rows:
        try:
            sigs = json.loads(r.signals_json or "[]")
        except Exception:
            sigs = []
        for raw in sigs:
            if not isinstance(raw, str):
                continue
            k = (r.agent, normalize_signal_key(raw))
            d = sig_stats.setdefault(k, {"n": 0, "hits": 0})
            d["n"]    += 1
            d["hits"] += 1 if r.hit_4h else 0
        rk = (r.agent, r.regime or "unknown", r.direction)
        d = reg_stats.setdefault(rk, {"n": 0, "hits": 0})
        d["n"]    += 1
        d["hits"] += 1 if r.hit_4h else 0

    # ── P2.1: sesuaikan bobot ─────────────────────────────────────────────────
    raises_enabled = now >= RAISE_ENABLED_AFTER
    adjustments: list[dict] = []
    async with AsyncSessionLocal() as session:
        for (agent, key), d in sorted(sig_stats.items()):
            if d["n"] < MIN_N:
                continue
            hit = d["hits"] / d["n"]
            if hit < LOW_HIT:
                step = -STEP
            elif hit > HIGH_HIT and raises_enabled:
                step = +STEP
            else:
                continue

            row = (await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.agent      == agent,
                    AgentSignalWeight.signal_key == key,
                    AgentSignalWeight.regime     == "all",
                )
            )).scalar_one_or_none()
            old_w = row.weight if row else 1.0
            new_w = round(max(FLOOR, min(CAP, old_w + step)), 3)
            if abs(new_w - old_w) < 1e-9:
                continue   # sudah di floor/cap

            if row is None:
                session.add(AgentSignalWeight(
                    agent=agent, signal_key=key, regime="all", weight=new_w,
                    win_count=d["hits"], total_count=d["n"],
                    win_rate=round(hit, 4), avg_pnl_pct=0.0,
                    sample_count_raw=d["n"], updated_at=now,
                ))
            else:
                row.weight     = new_w
                row.updated_at = now
            session.add(SignalWeightHistory(
                agent=agent, signal_key=key, regime="all", weight=new_w,
                win_count=d["hits"], total_count=d["n"], win_rate=round(hit, 4),
                avg_pnl_pct=0.0, sample_count_raw=d["n"], snapshot_at=now,
            ))
            adjustments.append({
                "agent": agent, "signal_key": key, "n": d["n"],
                "hit_rate_4h": round(hit * 100, 1),
                "old_weight": round(old_w, 3), "new_weight": new_w,
            })
        if adjustments:
            await session.commit()

    # ── P2.2: report per (agent, regime, direction) ───────────────────────────
    agent_tot: dict[str, list] = {}
    for (agent, _, _), d in reg_stats.items():
        t = agent_tot.setdefault(agent, [0, 0])
        t[0] += d["hits"]
        t[1] += d["n"]
    regime_report: list[dict] = []
    for (agent, regime, direction), d in sorted(reg_stats.items()):
        if d["n"] < MIN_N:
            continue
        hit = d["hits"] / d["n"]
        avg = agent_tot[agent][0] / agent_tot[agent][1] if agent_tot[agent][1] else 0.0
        if hit >= avg + 0.10:
            rec = "modifier searah TERKONFIRMASI (hit ≥ avg+10%)"
        elif hit <= avg - 0.10:
            rec = "modifier searah DIRAGUKAN — pertimbangkan kecilkan (mis. ±5 → ±3)"
        else:
            rec = "netral — pertahankan modifier sekarang"
        regime_report.append({
            "agent": agent, "regime": regime, "direction": direction,
            "n": d["n"], "hit_rate_4h": round(hit * 100, 1),
            "agent_avg_4h": round(avg * 100, 1), "recommendation": rec,
        })

    _last_review = {
        "ran_at":         now,
        "window_start":   cutoff,
        "resolved_rows":  len(rows),
        "raises_enabled": raises_enabled,
        "adjustments":    adjustments,
        "regime_report":  regime_report,
    }
    logger.info(
        "weekly_signal_review_done",
        resolved_rows=len(rows), signals_sampled=len(sig_stats),
        adjustments=len(adjustments), raises_enabled=raises_enabled,
    )
    return _last_review
