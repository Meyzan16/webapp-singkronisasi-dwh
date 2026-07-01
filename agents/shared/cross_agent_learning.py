"""
Cross-Agent Learning — SP3.

Aggregates signal performance across ALL agents (SPOT + Futures) and produces
a blended "cross_agent" weight for each signal key.

Why: a signal proven in SPOT (e.g. BB Squeeze) is likely valid in Futures too.
Instead of each agent learning in isolation, they now share evidence:
  - Own-agent weight: 70%  (from own trade history)
  - Cross-agent weight: 30% (from all agents combined)

Requirements:
  - MIN_CROSS_SAMPLE = 10 trades total across agents before cross weight activates
  - Runs after both spot and futures weight updaters complete
  - Stores result in agent_signal_weights with agent='cross_agent'
  - In-memory cache read synchronously by agent scoring functions
"""

import time
from collections import defaultdict
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.signal_weight import AgentSignalWeight

logger = structlog.get_logger(__name__)

CROSS_AGENT_KEY    = "cross_agent"
CROSS_BLEND        = 0.30    # 30% cross-agent influence on final weight
MIN_CROSS_SAMPLE   = 10      # minimum raw trades across ALL agents before cross weight moves
STEP_CAP           = 0.10
MIN_RUN_INTERVAL   = 30 * 60  # run at most once every 30 minutes

_last_run:    Optional[float]       = None
_last_error:  Optional[str]         = None
_cross_cache: dict[str, float]      = {}   # {signal_key: cross_weight}

ALL_AGENTS = [
    "opportunity_spot",
    "futures_agent1",
    "futures_agent2",
    "futures_agent3",
]


# ── Public accessors ───────────────────────────────────────────────────────────

def get_cross_weight(signal_key: str) -> float:
    """Return cross-agent weight for a signal — 1.0 (neutral) if not enough data."""
    return _cross_cache.get(signal_key, 1.0)


def blend_weights(own: float, cross: float) -> float:
    """Blend own-agent weight with cross-agent weight."""
    return round(own * (1 - CROSS_BLEND) + cross * CROSS_BLEND, 3)


def get_state() -> dict:
    return {
        "last_run":    _last_run,
        "last_error":  _last_error,
        "cached_keys": len(_cross_cache),
        "top_signals": sorted(
            [{"key": k, "weight": v} for k, v in _cross_cache.items()],
            key=lambda x: x["weight"], reverse=True
        )[:5],
    }


# ── Weight formula (same as updaters) ─────────────────────────────────────────

def _target_weight(win_rate_adj: float) -> float:
    if win_rate_adj >= 0.70: return 1.5
    if win_rate_adj >= 0.55: return 1.2
    if win_rate_adj >= 0.40: return 1.0
    return 0.7


# ── Main update ────────────────────────────────────────────────────────────────

async def update_cross_agent_weights() -> int:
    """
    Read all agent_signal_weights rows (regime='all') from every agent,
    aggregate by signal_key, compute cross-agent weight, upsert with step cap.
    Returns number of rows touched.
    """
    global _last_run, _last_error, _cross_cache, CROSS_BLEND

    if not is_db_available():
        return 0

    now = time.time()
    if _last_run and (now - _last_run) < MIN_RUN_INTERVAL:
        return 0

    # PLAN_v5 Group C: blend_weights() (called from agent1/2/3 at scoring time)
    # reads CROSS_BLEND as a bare global in THIS module, so refreshing it here
    # takes effect starting the next scan cycle — this update runs post-scan.
    try:
        from agents.shared.config_reader import cfg
        CROSS_BLEND = await cfg.get("learning", "cross_blend", CROSS_BLEND)
    except Exception as exc:
        logger.warning("agent_config_pull_failed", scope="cross_agent_learning", error=str(exc)[:120])

    try:

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.agent.in_(ALL_AGENTS),
                    AgentSignalWeight.regime == "all",
                )
            )
            rows = list(result.scalars().all())

        # Aggregate: sum wins + total across all agents per signal_key
        agg: dict[str, dict] = defaultdict(lambda: {
            "wins": 0, "total": 0, "pnl_sum": 0.0, "win_n": 0
        })
        for row in rows:
            a = agg[row.signal_key]
            a["wins"]    += row.win_count
            a["total"]   += row.sample_count_raw or row.total_count
            a["pnl_sum"] += (row.avg_pnl_pct or 0.0) * max(row.win_count, 1)
            a["win_n"]   += max(row.win_count, 0)

        # Compute cross weights
        new_cross: dict[str, float] = {}
        for signal_key, v in agg.items():
            if v["total"] < MIN_CROSS_SAMPLE:
                continue  # not enough evidence
            n_eff   = float(v["total"])
            wr_adj  = (v["wins"] + 1.0) / (n_eff + 2.0)
            target  = _target_weight(wr_adj)
            conf    = min(1.0, n_eff / 20.0)   # cross needs more data: full at n=20
            desired = 1.0 + (target - 1.0) * conf
            new_cross[signal_key] = round(max(0.70, min(1.50, desired)), 3)

        # Upsert cross_agent rows with step cap
        touched = 0
        async with AsyncSessionLocal() as session:
            existing_result = await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.agent  == CROSS_AGENT_KEY,
                    AgentSignalWeight.regime == "all",
                )
            )
            existing_map = {r.signal_key: r for r in existing_result.scalars().all()}

            for signal_key, desired_w in new_cross.items():
                a    = agg[signal_key]
                wr   = a["wins"] / a["total"] if a["total"] > 0 else 0.0
                apnl = a["pnl_sum"] / a["win_n"] if a["win_n"] > 0 else 0.0

                row = existing_map.get(signal_key)
                if row is None:
                    initial = 1.0 + max(-STEP_CAP, min(STEP_CAP, desired_w - 1.0))
                    session.add(AgentSignalWeight(
                        agent            = CROSS_AGENT_KEY,
                        signal_key       = signal_key,
                        regime           = "all",
                        weight           = round(initial, 3),
                        win_count        = a["wins"],
                        total_count      = a["total"],
                        win_rate         = round(wr, 4),
                        avg_pnl_pct      = round(apnl, 3),
                        sample_count_raw = a["total"],
                        updated_at       = now,
                    ))
                else:
                    step             = max(-STEP_CAP, min(STEP_CAP, desired_w - row.weight))
                    row.weight           = round(row.weight + step, 3)
                    row.win_count        = a["wins"]
                    row.total_count      = a["total"]
                    row.win_rate         = round(wr, 4)
                    row.avg_pnl_pct      = round(apnl, 3)
                    row.sample_count_raw = a["total"]
                    row.updated_at       = now
                touched += 1

            # Prune stale cross keys no longer in current data
            for signal_key, row in existing_map.items():
                if signal_key in new_cross:
                    continue
                stale = (now - (row.updated_at or 0)) / 86400
                if stale > 30:
                    await session.delete(row)
                elif abs(row.weight - 1.0) > 0.01:
                    row.weight = round(
                        max(1.0, row.weight - STEP_CAP) if row.weight > 1.0
                        else min(1.0, row.weight + STEP_CAP),
                        3
                    )
                touched += 1

            await session.commit()

        _cross_cache = new_cross
        _last_run    = now
        _last_error  = None
        logger.info("cross_agent_weights_updated", keys=len(new_cross), touched=touched)
        return touched

    except Exception as exc:
        _last_error = str(exc)[:120]
        logger.error("cross_agent_learning_error", error=_last_error)
        return 0
