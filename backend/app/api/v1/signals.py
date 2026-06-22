"""
Signal Performance API — SP4.

GET /api/v1/signals/performance   — all signal weights with stats, filterable
GET /api/v1/signals/cross_agent   — cross-agent comparison per signal
GET /api/v1/signals/updater/state — state of weight updaters
POST /api/v1/signals/updater/run  — force-run all weight updaters
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.database import AsyncSessionLocal, require_db
from app.models.signal_weight import AgentSignalWeight

router = APIRouter(tags=["signals"])

ALL_AGENTS = [
    "opportunity_spot",
    "futures_agent1",
    "futures_agent2",
    "futures_agent3",
    "cross_agent",
]

AGENT_LABELS = {
    "opportunity_spot": "SPOT",
    "futures_agent1":   "Pre-Gainer",
    "futures_agent2":   "Accumulation",
    "futures_agent3":   "Momentum",
    "cross_agent":      "Cross-Agent",
}


# ── GET /signals/performance ──────────────────────────────────────────────────

@router.get("/signals/performance", dependencies=[Depends(require_db)])
async def get_signal_performance(
    agent:      str = Query("all",      description="all | opportunity_spot | futures_agent1 | futures_agent2 | futures_agent3 | cross_agent"),
    regime:     str = Query("all",      description="all | trending_up | trending_down | ranging | volatile"),
    min_trades: int = Query(3,          description="Minimum raw trade count"),
    sort_by:    str = Query("win_rate", description="win_rate | avg_pnl_pct | total_count | weight"),
    sort_dir:   str = Query("desc",     description="desc | asc"),
    limit:      int = Query(30,         ge=1, le=100),
) -> dict:
    """
    Return signal performance rows from agent_signal_weights.
    Groups by signal_key and returns per-agent breakdown.
    """
    async with AsyncSessionLocal() as session:
        q = select(AgentSignalWeight)

        if agent != "all":
            q = q.where(AgentSignalWeight.agent == agent)
        else:
            q = q.where(AgentSignalWeight.agent.in_(ALL_AGENTS))

        if regime != "all":
            q = q.where(AgentSignalWeight.regime == regime)
        else:
            q = q.where(AgentSignalWeight.regime == "all")

        result = await session.execute(q)
        rows   = list(result.scalars().all())

    # Filter by min_trades
    rows = [r for r in rows if (r.sample_count_raw or r.total_count) >= min_trades]

    # Group by signal_key — build per-agent breakdown
    signal_map: dict[str, dict] = {}
    for r in rows:
        entry = signal_map.setdefault(r.signal_key, {
            "signal_key": r.signal_key,
            "agents":     {},
            "best_win_rate":  0.0,
            "best_avg_pnl":   0.0,
            "total_trades":   0,
            "cross_weight":   None,
        })
        agent_label = AGENT_LABELS.get(r.agent, r.agent)
        entry["agents"][r.agent] = {
            "label":       agent_label,
            "win_rate":    round(r.win_rate * 100, 1),
            "total":       r.sample_count_raw or r.total_count,
            "wins":        r.win_count,
            "avg_pnl_pct": round(r.avg_pnl_pct or 0.0, 2),
            "weight":      round(r.weight, 3),
        }
        if r.agent == "cross_agent":
            entry["cross_weight"] = round(r.weight, 3)
        else:
            entry["total_trades"]  += r.sample_count_raw or r.total_count
            if r.win_rate > entry["best_win_rate"]:
                entry["best_win_rate"] = round(r.win_rate * 100, 1)
            if (r.avg_pnl_pct or 0.0) > entry["best_avg_pnl"]:
                entry["best_avg_pnl"] = round(r.avg_pnl_pct or 0.0, 2)

    signals = list(signal_map.values())

    # Sort
    reverse = sort_dir == "desc"
    sort_key_map = {
        "win_rate":    lambda x: x["best_win_rate"],
        "avg_pnl_pct": lambda x: x["best_avg_pnl"],
        "total_count": lambda x: x["total_trades"],
        "weight":      lambda x: x.get("cross_weight") or x["best_win_rate"],
    }
    signals.sort(key=sort_key_map.get(sort_by, lambda x: x["best_win_rate"]), reverse=reverse)
    signals = signals[:limit]

    return {
        "signals": signals,
        "meta": {
            "total":       len(signal_map),
            "shown":       len(signals),
            "agent_filter": agent,
            "regime_filter": regime,
            "min_trades":  min_trades,
        },
    }


# ── GET /signals/cross_agent ──────────────────────────────────────────────────

@router.get("/signals/cross_agent", dependencies=[Depends(require_db)])
async def get_cross_agent_signals(
    min_trades: int = Query(10, description="Minimum cross-agent trade count"),
    limit:      int = Query(20, ge=1, le=50),
) -> dict:
    """
    Return cross-agent aggregated signal performance.
    Shows signals proven across multiple agent types.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.agent  == "cross_agent",
                AgentSignalWeight.regime == "all",
            )
        )
        cross_rows = list(result.scalars().all())

        # Also fetch per-agent data for these signal keys
        keys = [r.signal_key for r in cross_rows]
        per_agent_rows = []
        if keys:
            pa_result = await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.signal_key.in_(keys),
                    AgentSignalWeight.agent.in_(ALL_AGENTS[:-1]),  # exclude cross_agent
                    AgentSignalWeight.regime == "all",
                )
            )
            per_agent_rows = list(pa_result.scalars().all())

    # Build per-key agent map
    pa_map: dict[str, dict] = {}
    for r in per_agent_rows:
        pa_map.setdefault(r.signal_key, {})[r.agent] = {
            "label":    AGENT_LABELS.get(r.agent, r.agent),
            "win_rate": round(r.win_rate * 100, 1),
            "total":    r.sample_count_raw or r.total_count,
            "weight":   round(r.weight, 3),
        }

    signals = []
    for r in cross_rows:
        if (r.sample_count_raw or r.total_count) < min_trades:
            continue
        agents_data = pa_map.get(r.signal_key, {})
        agent_count = len(agents_data)
        signals.append({
            "signal_key":   r.signal_key,
            "cross_weight": round(r.weight, 3),
            "cross_win_rate": round(r.win_rate * 100, 1),
            "cross_total":  r.sample_count_raw or r.total_count,
            "avg_pnl_pct":  round(r.avg_pnl_pct or 0.0, 2),
            "agent_count":  agent_count,
            "agents":       agents_data,
            "reliability":  "high" if agent_count >= 3 else "medium" if agent_count == 2 else "low",
        })

    signals.sort(key=lambda x: (x["agent_count"], x["cross_win_rate"]), reverse=True)
    return {
        "signals": signals[:limit],
        "meta":    {"total": len(signals), "min_trades": min_trades},
    }


# ── GET /signals/updater/state ────────────────────────────────────────────────

@router.get("/signals/updater/state")
async def get_updater_state() -> dict:
    """State of all weight updaters (last run, errors, cache sizes)."""
    try:
        from agents.futures.weight_updater import get_state as fut_state
    except Exception:
        fut_state = lambda: {}  # noqa: E731

    try:
        from agents.opportunity.weight_updater import get_state as spot_state
    except Exception:
        spot_state = lambda: {}  # noqa: E731

    try:
        from agents.shared.cross_agent_learning import get_state as cross_state
    except Exception:
        cross_state = lambda: {}  # noqa: E731

    return {
        "futures": fut_state(),
        "spot":    spot_state(),
        "cross":   cross_state(),
    }


# ── POST /signals/updater/run ─────────────────────────────────────────────────

@router.post("/signals/updater/run", dependencies=[Depends(require_db)])
async def force_run_updaters() -> dict:
    """Force-run all weight updaters immediately (bypass rate limit)."""
    results = {}

    try:
        from agents.futures.weight_updater import update_weights
        results["futures"] = await update_weights()
    except Exception as e:
        results["futures"] = f"error: {e}"

    try:
        from agents.opportunity.weight_updater import update_spot_weights
        results["spot"] = await update_spot_weights()
    except Exception as e:
        results["spot"] = f"error: {e}"

    try:
        from agents.shared.cross_agent_learning import update_cross_agent_weights
        results["cross"] = await update_cross_agent_weights()
    except Exception as e:
        results["cross"] = f"error: {e}"

    return {"updated": results}
