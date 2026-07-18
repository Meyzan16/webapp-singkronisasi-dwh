"""Predictive Repair Agent — perbaikan sinyal LIVE dari data predictive (R2).

Weekly review (Senin) tetap jalan sebagai jaring pengaman lebar; agen ini adalah
refleks cepatnya: tiap ~30 menit memeriksa hit-rate 4h per sinyal (era-filter)
dan langsung menurunkan bobot sinyal yang terbukti buruk — tanpa menunggu Senin.

Guardrails terkunci (PLAN_SIGNAL_REPAIR_LIVE §3):
  - bounded 0.70–1.50, step 0.10 (konstanta dibagi dgn weekly_signal_review)
  - max 1 aksi bobot per target per 24 jam (cooldown via repair ledger R1)
  - raise (+0.10) HANYA setelah masa lower-only berakhir (7 Agu)
  - tidak menyentuh rumus skor dasar; veto-only tetap berlaku
  - SETIAP aksi tercatat di futures_repair_actions (aksi senyap = bug)
"""

from __future__ import annotations

import json
import time
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.predictive_log import PredictiveLog
from app.models.signal_weight import AgentSignalWeight
from app.models.signal_weight_history import SignalWeightHistory
from agents.futures.learning_policy import canonical_signal_key, signal_key as fallback_key
from agents.futures.weight_updater import DATA_ERA_EPOCH, FUTURES_AGENTS
from agents.learning.weekly_signal_review import (
    CAP, FLOOR, HIGH_HIT, LOW_HIT, RAISE_ENABLED_AFTER, STEP,
)
from agents.futures.repair_log import COOLDOWN_ACTION_H, has_recent_action, record_action

logger = structlog.get_logger(__name__)

WINDOW_DAYS     = 7
MIN_N           = 15      # lebih ketat dari weekly (10): refleks cepat butuh bukti lebih
MIN_RUN_GAP_SEC = 20 * 60

_status: dict = {"last_run": None, "checked": 0, "actions_last_run": 0, "actions_total": 0}


def get_repair_agent_status() -> dict:
    return dict(_status)


async def collect_predictive_stats(min_ts: float,
                                   agent_filter: Optional[str] = None) -> dict[tuple, dict]:
    """Agregasi hit-rate 4h per (agent, canonical/fallback key) dari predictive_log
    resolved sejak min_ts. Dipakai R2 (deteksi) dan R3 verifier (metrik sesudah)."""
    stats: dict[tuple, dict] = {}
    async with AsyncSessionLocal() as session:
        q = select(PredictiveLog).where(
            PredictiveLog.agent.in_(FUTURES_AGENTS),
            PredictiveLog.resolved_at.is_not(None),
            PredictiveLog.scanned_at >= min_ts,
        )
        if agent_filter:
            q = q.where(PredictiveLog.agent == agent_filter)
        rows = list((await session.execute(q)).scalars().all())
    for r in rows:
        try:
            sigs = json.loads(r.signals_json or "[]")
        except Exception:
            sigs = []
        for raw in sigs:
            if not isinstance(raw, str) or not raw.strip():
                continue
            key = canonical_signal_key(raw) or fallback_key(raw)
            d = stats.setdefault((r.agent, key), {"n": 0, "hits": 0})
            d["n"] += 1
            d["hits"] += 1 if r.hit_4h else 0
    return stats


async def _apply_weight_step(agent: str, key: str, step: float, now: float) -> Optional[tuple[float, float]]:
    """Upsert bobot ±step (bounded) + snapshot history. Return (old_w, new_w) atau None."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.agent == agent,
                AgentSignalWeight.signal_key == key,
                AgentSignalWeight.regime == "all",
            )
        )).scalar_one_or_none()
        old_w = row.weight if row else 1.0
        new_w = round(max(FLOOR, min(CAP, old_w + step)), 3)
        if abs(new_w - old_w) < 1e-9:
            return None   # sudah mentok floor/cap
        if row is None:
            session.add(AgentSignalWeight(
                agent=agent, signal_key=key, regime="all", weight=new_w,
                updated_at=now,
            ))
        else:
            row.weight = new_w
            row.updated_at = now
        session.add(SignalWeightHistory(
            agent=agent, signal_key=key, regime="all", weight=new_w,
            snapshot_at=now,
        ))
        await session.commit()
    return old_w, new_w


async def run_predictive_repair(force: bool = False) -> dict:
    """Satu pass agen: deteksi era-filtered → aksi bobot bounded → catat ledger."""
    global _status
    now = time.time()
    if not is_db_available():
        return {"status": "db_unavailable"}
    if not force and _status["last_run"] and (now - _status["last_run"]) < MIN_RUN_GAP_SEC:
        return {"status": "cooldown", **_status}

    cutoff = max(DATA_ERA_EPOCH, now - WINDOW_DAYS * 86400)
    stats = await collect_predictive_stats(cutoff)
    actions: list[dict] = []
    raises_enabled = now >= RAISE_ENABLED_AFTER

    for (agent, key), d in sorted(stats.items()):
        if d["n"] < MIN_N:
            continue
        hit = d["hits"] / d["n"]
        if hit < LOW_HIT:
            step, issue = -STEP, "hit_rate_low"
        elif hit > HIGH_HIT and raises_enabled:
            step, issue = +STEP, "hit_rate_high"
        else:
            continue

        target = f"{agent}:{key}"
        if await has_recent_action(target, hours=COOLDOWN_ACTION_H):
            continue   # anti-osilasi: sudah ada aksi ≤24 jam
        applied = await _apply_weight_step(agent, key, step, now)
        if applied is None:
            continue   # sudah di floor/cap — bukan aksi
        old_w, new_w = applied
        await record_action(
            source="predictive_agent",
            target_key=target,
            agent=agent,
            issue=issue,
            action="weight_down" if step < 0 else "weight_up",
            evidence={"n": d["n"], "hit_rate_4h": round(hit, 4),
                      "before_weight": old_w, "after_weight": new_w,
                      "window_days": WINDOW_DAYS},
            delta=step,
            before_metric=round(hit, 4),
        )
        actions.append({"target": target, "issue": issue, "n": d["n"],
                        "hit_rate_4h": round(hit * 100, 1),
                        "weight": f"{old_w} → {new_w}"})
        logger.info("predictive_repair_action", target=target, issue=issue,
                    n=d["n"], hit=round(hit, 3), old_w=old_w, new_w=new_w)

    _status = {
        "last_run": now,
        "checked": len(stats),
        "actions_last_run": len(actions),
        "actions_total": _status.get("actions_total", 0) + len(actions),
    }
    return {"status": "ok", "checked": len(stats), "actions": actions,
            "raises_enabled": raises_enabled}
