"""Persistence keputusan immutable pipeline FUTURES (PLAN_ADAPTIVE_LEARNING_FUTURES_10X F1).

Mirror pola agents/opportunity/decision_ledger.py (SPOT — tidak disentuh).
Satu baris = satu keputusan (symbol, agent, direction) pada satu scan: dibuka,
di-skip guard mana, atau sekadar rekomendasi — plus feature snapshot numerik
untuk training F3. Outcome diisi belakangan oleh outcome_tracker.

Kontrol volume (keputusan desain plan §2.5): scan futures tiap 2 menit × 4 agent
→ dedup window 15 menit per (symbol, agent, direction); event `opened` SELALU
ditulis (langka & paling berharga).
"""

from __future__ import annotations

import hashlib
import json
import time

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_decision_event import FuturesDecisionEvent

logger = structlog.get_logger(__name__)

MODEL_VERSION          = "futures_rules_adaptive_v1"
FEATURE_SCHEMA_VERSION = "futures_features_v1"
DEDUP_WINDOW_SEC       = 15 * 60
LEDGER_RETENTION_DAYS  = 45

# Field numerik kandidat yang dipetik jadi feature snapshot — semuanya SUDAH ada
# di dict hasil scan (tanpa fetch tambahan). Field learning (adaptive_score dll)
# terisi setelah F2; sebelum itu absen dari snapshot dan itu tidak apa-apa.
_FEATURE_KEYS = (
    "score", "change_24h", "funding_rate", "oi_change", "atr_pct", "risk_pct",
    "tp1_pct", "tp2_pct", "tp3_pct", "rr_ratio", "leverage",
    "liq_long", "liq_short", "size_mult", "quote_vol_24h", "entry_slippage_pct",
    "cost_floor_pct", "change_1h", "change_30m", "rsi",
    "adaptive_score", "weight_applied",
    "estimated_win_probability", "lower_confidence_probability",
)

_GLOBAL_BLOCK_REASONS = {
    "risk_gate_blocked", "daily_gate_blocked", "consec_sl_global_pause",
}
_RECOMMEND_REASONS = {"below_auto_threshold", "not_evaluated"}


def classify_action(reason: str, opened: bool) -> str:
    """Map reason code → action kelas (pola SPOT: opened/blocked/rejected/recommendation).
    `learning_ban`/`learning_veto` (F2) masuk kelas "blocked" — di-veto engine, bukan
    ditolak strategi dasar — supaya bisa dibedakan di analitik dari reject biasa."""
    if opened or reason == "opened":
        return "opened"
    if reason in _GLOBAL_BLOCK_REASONS or reason in ("learning_ban", "learning_veto"):
        return "blocked"
    if reason in _RECOMMEND_REASONS:
        return "recommendation"
    return "rejected"


def build_event_rows(
    candidates: list[dict],
    decisions: dict[tuple, str],
    scan_ts: float,
    breadth: dict | None = None,
    learning_status: str = "warming",
) -> list[dict]:
    """Baris deterministik — retry scan yang sama menghasilkan decision_key sama
    (unique constraint + on_conflict_do_nothing membuatnya idempotent)."""
    best: dict[tuple, dict] = {}
    for c in candidates:
        sym = str(c.get("symbol") or "")
        if not sym:
            continue
        key = (sym, str(c.get("agent") or ""), str(c.get("direction") or "LONG"))
        cur = best.get(key)
        if cur is None or float(c.get("score") or 0) > float(cur.get("score") or 0):
            best[key] = c

    breadth = breadth or {}
    now = time.time()
    rows: list[dict] = []
    for (sym, agent, direction), c in sorted(best.items()):
        reason = str(decisions.get((sym, agent, direction), "not_evaluated"))
        opened = reason == "opened"
        action = classify_action(reason, opened)

        feats: dict[str, float] = {}
        for k in _FEATURE_KEYS:
            v = c.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                feats[k] = float(v)
        for bk, fk in (("fade_frac", "breadth_fade_frac"), ("gainers", "breadth_gainers")):
            bv = breadth.get(bk)
            if isinstance(bv, (int, float)) and not isinstance(bv, bool):
                feats[fk] = float(bv)
        # F5: simpan prediksi shadow (bila model shadow/canary/champion aktif) —
        # dipakai evaluate_canary & monitor_champion_drift. Bukan fitur training
        # (di-exclude di futures_adaptive_model._EXCLUDE_FEATURES).
        if isinstance(c.get("shadow_probability"), (int, float)):
            feats["shadow_probability"] = float(c["shadow_probability"])
        if c.get("shadow_model_version"):
            feats["shadow_model_version"] = str(c["shadow_model_version"])

        key_material = f"{scan_ts:.0f}|{sym}|{agent}|{direction}"
        est_prob = c.get("estimated_win_probability")
        row_status = str(c.get("learning_status") or learning_status)
        rows.append({
            "decision_key":   hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:64],
            "scan_ts":        float(scan_ts),
            "symbol":         sym,
            "agent":          agent,
            "direction":      direction,
            "lane":           str(c.get("setup_type") or ""),
            "action":         action,
            "reason_code":    reason[:60],
            "opened":         opened,
            # Semua yang mencapai titik guard/open sudah melewati ambang auto —
            # hanya "recommendation" yang belum eligible.
            "auto_eligible":  action != "recommendation",
            "score":          float(c.get("score") or 0.0),
            "adaptive_score": float(c.get("adaptive_score") or c.get("score") or 0.0),
            "weight_applied": float(c.get("weight_applied") or 1.0),
            "estimated_win_probability": float(est_prob) if isinstance(est_prob, (int, float)) else None,
            "price_at_scan":  float(c.get("price") or c.get("entry") or 0.0),
            "leverage":       int(c.get("leverage") or 0),
            "cost_floor_pct": float(c["cost_floor_pct"]) if isinstance(c.get("cost_floor_pct"), (int, float)) else None,
            "regime":         (str(c.get("regime")) if c.get("regime") else None),
            "learning_status": row_status,
            "model_version":   MODEL_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_snapshot_json":  json.dumps(feats, ensure_ascii=False),
            "created_at":     now,
            "outcome_status": "pending",
            # Fase 5: jejak ukuran, diambil dari keluaran `sizing.compute` yang
            # ditempelkan auto_trader ke kandidat. Sengaja disimpan sebagai KOLOM,
            # bukan di dalam feature_snapshot_json: ini bukan fitur untuk melatih
            # model (ukuran adalah AKIBAT keputusan, bukan sebabnya), melainkan
            # bahan untuk menilai apakah "terukur" benar-benar tercapai.
            **_jejak_ukuran(c),
        })
    return rows


def _jejak_ukuran(c: dict) -> dict:
    """Ambil angka ukuran dari kandidat bila `sizing.compute` sudah berjalan.

    Semuanya None bila belum — kandidat yang ditolak SEBELUM tahap sizing memang
    tak punya ukuran, dan menuliskan nol di situ akan membuatnya tampak seperti
    posisi berukuran nol yang pernah dipertimbangkan.
    """
    sz = c.get("sizing") or {}
    if not isinstance(sz, dict) or not sz:
        return {}

    def _f(key: str):
        v = sz.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    return {
        "risk_usd":     _f("risk_usd"),
        "notional_usd": _f("notional"),
        "margin_usd":   _f("margin"),
        "tp1_net_usd":  _f("tp1_net_usd"),
        "sl_net_usd":   _f("sl_net_usd"),
        "cost_usd":     _f("cost_usd"),
    }


async def log_scan_decisions(candidates: list[dict], scan_ts: float | None = None) -> int:
    """Tulis keputusan satu cycle. Dipanggil scheduler SETELAH auto_open_positions
    (peta keputusan auto_trader harus sudah final). Fail-open total."""
    if not is_db_available() or not candidates:
        return 0

    from agents.futures.auto_trader import get_cycle_decisions
    decisions = get_cycle_decisions()
    breadth: dict = {}
    try:
        from agents.futures import store as futures_store
        breadth = futures_store.get_market_breadth() or {}
    except Exception:
        pass

    rows = build_event_rows(candidates, decisions, float(scan_ts or time.time()), breadth)
    if not rows:
        return 0

    now = time.time()
    async with AsyncSessionLocal() as session:
        recent = (await session.execute(
            select(FuturesDecisionEvent.symbol, FuturesDecisionEvent.agent,
                   FuturesDecisionEvent.direction).where(
                FuturesDecisionEvent.scan_ts >= now - DEDUP_WINDOW_SEC,
            )
        )).all()
        recent_keys = {(r[0], r[1], r[2]) for r in recent}
        to_insert = [
            r for r in rows
            if r["action"] == "opened"   # opened selalu ditulis
            or (r["symbol"], r["agent"], r["direction"]) not in recent_keys
        ]
        if not to_insert:
            return 0
        stmt = pg_insert(FuturesDecisionEvent).values(to_insert).on_conflict_do_nothing(
            index_elements=["decision_key"]
        )
        result = await session.execute(stmt)
        await session.commit()

    # rowcount = baris yang BENAR-BENAR ter-insert (on_conflict men-skip duplikat
    # decision_key bila scan yang sama diproses ulang) — bukan len(to_insert).
    inserted = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(to_insert)
    if inserted:
        logger.info("futures_decision_ledger_logged", rows=inserted,
                    opened=sum(1 for r in to_insert if r["opened"]))
    return inserted
