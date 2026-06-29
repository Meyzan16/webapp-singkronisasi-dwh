"""
Signal Performance API — SP4 + PLAN_v2 P3.

GET /api/v1/signals/performance           — all signal weights with stats, filterable
GET /api/v1/signals/cross_agent           — cross-agent comparison per signal
GET /api/v1/signals/{signal_key}/history  — weight trajectory timeseries (P3.1)
GET /api/v1/signals/{signal_key}/explain  — explain current weight for a signal (P3.2)
GET /api/v1/signals/catalog               — signal → formula → agent mapping (P3.3)
GET /api/v1/signals/regime_heatmap        — weight per (signal, regime) heatmap (P3.5)
GET /api/v1/signals/updater/state         — state of weight updaters
POST /api/v1/signals/updater/run          — force-run all weight updaters
"""

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.database import AsyncSessionLocal, require_db
from app.models.signal_weight import AgentSignalWeight
from app.models.signal_weight_history import SignalWeightHistory

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


# ── GET /signals/catalog ─────────────────────────────────────────────────────

@router.get("/signals/catalog")
async def get_signal_catalog() -> dict:
    """Return signal → formula → agent mapping (P3.3). No DB required."""
    from app.services.signal_catalog import SIGNAL_CATALOG, get_all_categories
    return {
        "catalog": SIGNAL_CATALOG,
        "categories": get_all_categories(),
        "total": len(SIGNAL_CATALOG),
    }


# ── GET /signals/regime_heatmap ───────────────────────────────────────────────

@router.get("/signals/regime_heatmap", dependencies=[Depends(require_db)])
async def get_regime_heatmap(
    agent:  str = Query("all",  description="all | futures_agent1 | futures_agent2 | futures_agent3"),
    limit:  int = Query(20, ge=1, le=100),
) -> dict:
    """Weight per (signal, regime) for heatmap visualization (P3.5)."""
    REGIMES = ["all", "trending_up", "trending_down", "ranging", "volatile"]
    async with AsyncSessionLocal() as session:
        q = select(AgentSignalWeight)
        if agent != "all":
            q = q.where(AgentSignalWeight.agent == agent)
        else:
            q = q.where(AgentSignalWeight.agent.in_(ALL_AGENTS))
        result = await session.execute(q)
        rows   = list(result.scalars().all())

    # Group by signal_key: collect weight per regime
    sig_map: dict[str, dict] = {}
    for r in rows:
        entry = sig_map.setdefault(r.signal_key, {
            "signal_key":   r.signal_key,
            "regimes":      {reg: None for reg in REGIMES},
            "max_deviation": 0.0,
        })
        if r.regime in REGIMES:
            entry["regimes"][r.regime] = round(r.weight, 3)
        # Track max deviation from neutral (1.0) across regimes for sort
        dev = abs(r.weight - 1.0)
        if dev > entry["max_deviation"]:
            entry["max_deviation"] = round(dev, 3)

    signals = sorted(sig_map.values(), key=lambda x: x["max_deviation"], reverse=True)[:limit]
    return {"signals": signals, "regimes": REGIMES, "total": len(sig_map)}


# ── GET /signals/{signal_key}/history ────────────────────────────────────────

@router.get("/signals/{signal_key}/history", dependencies=[Depends(require_db)])
async def get_signal_history(
    signal_key: str,
    agent:      str = Query("all",  description="all | futures_agent1 | opportunity_spot | …"),
    days:       int = Query(30,     ge=1, le=90),
) -> dict:
    """Weight trajectory timeseries for a signal (P3.1)."""
    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as session:
        q = select(SignalWeightHistory).where(
            SignalWeightHistory.signal_key == signal_key,
            SignalWeightHistory.snapshot_at >= cutoff,
        )
        if agent != "all":
            q = q.where(SignalWeightHistory.agent == agent)
        q = q.order_by(SignalWeightHistory.snapshot_at)
        result = await session.execute(q)
        rows   = list(result.scalars().all())

    # Group by agent
    by_agent: dict[str, list[dict]] = {}
    for r in rows:
        by_agent.setdefault(r.agent, []).append({
            "ts":          round(r.snapshot_at),
            "weight":      round(r.weight, 3),
            "win_rate":    round(r.win_rate * 100, 1),
            "total_count": r.total_count,
        })

    return {
        "signal_key": signal_key,
        "days":       days,
        "agents":     by_agent,
        "total_snapshots": len(rows),
    }


# ── GET /signals/{signal_key}/explain ────────────────────────────────────────

@router.get("/signals/{signal_key}/explain", dependencies=[Depends(require_db)])
async def explain_signal(signal_key: str) -> dict:
    """Explain current weight, score impact, regime breakdown, catalog info (P3.2)."""
    from app.services.signal_catalog import get_catalog_entry
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentSignalWeight).where(AgentSignalWeight.signal_key == signal_key)
        )
        rows = list(result.scalars().all())

    # Partition by regime
    all_row   = next((r for r in rows if r.regime == "all"), None)
    regimes   = {r.regime: round(r.weight, 3) for r in rows}
    agents_using = list({r.agent for r in rows if r.agent != "cross_agent"})
    cross_row = next((r for r in rows if r.agent == "cross_agent" and r.regime == "all"), None)

    current_weight = all_row.weight if all_row else 1.0
    delta_30d: float | None = None

    # Fetch 30d-ago snapshot for delta
    cutoff = time.time() - 30 * 86400
    async with AsyncSessionLocal() as session:
        hist_result = await session.execute(
            select(SignalWeightHistory).where(
                SignalWeightHistory.signal_key == signal_key,
                SignalWeightHistory.regime     == "all",
                SignalWeightHistory.snapshot_at >= cutoff,
            ).order_by(SignalWeightHistory.snapshot_at).limit(1)
        )
        oldest = hist_result.scalar_one_or_none()
    if oldest:
        delta_30d = round(current_weight - oldest.weight, 3)

    catalog = get_catalog_entry(signal_key)
    return {
        "signal_key":    signal_key,
        "current_weight": round(current_weight, 3),
        "delta_30d":     delta_30d,
        "win_rate":      round((all_row.win_rate or 0) * 100, 1) if all_row else None,
        "total_trades":  all_row.total_count if all_row else 0,
        "score_impact_pts": round((current_weight - 1.0) * 7.0, 2),
        "regime_breakdown": regimes,
        "agents_using":  agents_using,
        "cross_weight":  round(cross_row.weight, 3) if cross_row else None,
        "catalog":       catalog,
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


# ── GET /signals/agent_health ────────────────────────────────────────────────

@router.get("/signals/agent_health")
async def get_agent_health() -> dict:
    """
    Aggregate health dashboard for all futures agents.
    Combines: scan timing, risk gate state, per-lane WR/pause, weight updater stats.
    Powers the Signal Performance Overview Agent Intelligence panel.
    """
    from agents.futures import scheduler as futures_scheduler
    from agents.futures import risk_gate
    from agents.futures import weight_updater as wu

    scan_state = futures_scheduler.get_state()
    gate_state = risk_gate.get_gate_state()
    wu_state   = wu.get_state()

    lane_map = {
        "pre_gainer":   ("futures_agent1", "Pre-Gainer"),
        "accumulation": ("futures_agent2", "Accumulation"),
        "momentum":     ("futures_agent3", "Momentum"),
        "bigmover":     ("futures_agent_bigmover", "BigMover"),
    }
    lanes = []
    for lane, (agent, label) in lane_map.items():
        paused_info = gate_state.get("lane_pauses", {}).get(lane, {})
        wr_info     = gate_state.get("lane_wr", {}).get(lane, {})
        lanes.append({
            "lane":        lane,
            "agent":       agent,
            "label":       label,
            "paused":      paused_info.get("paused", False),
            "pause_until": paused_info.get("pause_until"),
            "wr":          wr_info.get("wr", 0.0),
            "trades":      wr_info.get("total", 0),
        })

    blacklisted = wu_state.get("blacklisted_coins", [])
    bl_dir      = wu_state.get("blacklisted_directional", [])

    return {
        "scan": {
            "running":          scan_state.get("running"),
            "cycle_count":      scan_state.get("cycle_count"),
            "last_scan_ts":     scan_state.get("last_scan_ts"),
            "next_scan_in_min": scan_state.get("next_scan_in_min"),
            "last_error":       scan_state.get("last_error"),
            "interval_minutes": scan_state.get("interval_minutes"),
        },
        "gate": {
            "active":       gate_state.get("active"),
            "gate_type":    gate_state.get("gate_type"),
            "reason":       gate_state.get("reason"),
            "drawdown_pct": gate_state.get("drawdown_pct"),
            "dd_threshold": gate_state.get("dd_threshold"),
            "rar":          gate_state.get("rar"),
            "n_trades":     gate_state.get("n_trades"),
            "stale":        gate_state.get("stale"),
        },
        "lanes": lanes,
        "learning": {
            "cached_keys":       wu_state.get("cached_keys", 0),
            "cached_agents":     wu_state.get("cached_agents", []),
            "blacklisted_count": len(blacklisted),
            "blacklisted_coins": blacklisted[:10],
            "bl_directional":    bl_dir[:10],
            "last_run":          wu_state.get("last_run"),
            "last_error":        wu_state.get("last_error"),
        },
    }


# ── GET /signals/rejections ───────────────────────────────────────────────────

@router.get("/signals/rejections", dependencies=[Depends(require_db)])
async def get_rejections(
    symbol: str = Query("", description="filter by symbol"),
    agent:  str = Query("all", description="all | futures_agent1 | futures_agent2 | futures_agent3"),
    hours:  int = Query(24, ge=1, le=168, description="lookback window in hours"),
    limit:  int = Query(50, ge=1, le=200),
) -> dict:
    """P7.2: Return recent signal rejections for the Rejections tab."""
    from app.models.rejection_log import RejectionLog
    import json as _json
    cutoff = time.time() - hours * 3600
    async with AsyncSessionLocal() as session:
        q = select(RejectionLog).where(RejectionLog.rejected_at >= cutoff)
        if symbol:
            q = q.where(RejectionLog.symbol == symbol.upper())
        if agent != "all":
            q = q.where(RejectionLog.agent == agent)
        q = q.order_by(RejectionLog.rejected_at.desc()).limit(limit)
        result = await session.execute(q)
        rows = list(result.scalars().all())

    rejections = []
    for r in rows:
        try:
            weak = _json.loads(r.weak_signals or "[]")
        except Exception:
            weak = []
        rejections.append({
            "id":            r.id,
            "symbol":        r.symbol,
            "agent":         r.agent,
            "direction":     r.direction,
            "score":         r.score,
            "threshold":     r.threshold,
            "gap":           round(r.threshold - r.score, 1),
            "regime":        r.regime,
            "reject_reason": r.reject_reason,
            "weak_signals":  weak,
            "rejected_at":   r.rejected_at,
        })

    return {
        "rejections": rejections,
        "total": len(rejections),
        "hours": hours,
        "filters": {"symbol": symbol, "agent": agent},
    }
