"""
Diagnostics Export API — PLAN_v2 P7.3.

GET /api/v1/diagnostics/snapshot — return a JSON snapshot of current system state:
  - Last 100 closed trades
  - Current signal weights
  - Current adaptive thresholds
  - Risk gate state
  - In-memory cache summaries
"""

import json
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, require_db
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight
from app.models.spot_decision_event import SpotDecisionEvent
from app.models.spot_model_version import SpotModelVersion

router = APIRouter(tags=["diagnostics"])

_FUTURES_STYLES = [
    "futures_agent1", "futures_agent2", "futures_agent3",
    "futures_agent_bigmover",
]


@router.get("/diagnostics/snapshot", dependencies=[Depends(require_db)])
async def get_diagnostic_snapshot() -> dict:
    """
    P7.3: Full system state snapshot — cache, weights, recent trades, thresholds.
    Useful for debugging "why is the system behaving this way" without needing log access.
    """
    now = time.time()

    # ── Signal weights ─────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        weights_result = await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.agent.in_(_FUTURES_STYLES + ["opportunity_spot", "cross_agent"]),
                AgentSignalWeight.regime == "all",
            ).order_by(AgentSignalWeight.agent, AgentSignalWeight.signal_key)
        )
        weights = [
            {
                "agent":      w.agent,
                "signal_key": w.signal_key,
                "weight":     round(w.weight, 3),
                "win_rate":   round(w.win_rate * 100, 1),
                "total":      w.total_count,
                "updated_at": w.updated_at,
            }
            for w in weights_result.scalars().all()
        ]

        decision_summary_result = await session.execute(
            select(
                SpotDecisionEvent.outcome_status,
                func.count(SpotDecisionEvent.id),
            ).group_by(SpotDecisionEvent.outcome_status)
        )
        decision_outcomes = {
            status: count for status, count in decision_summary_result.all()
        }
        latest_decision_ts = await session.scalar(select(func.max(SpotDecisionEvent.scan_ts)))
        total_decisions = await session.scalar(select(func.count(SpotDecisionEvent.id))) or 0
        unique_decisions = await session.scalar(select(func.count(func.distinct(SpotDecisionEvent.decision_key)))) or 0
        missing_snapshots = await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            (SpotDecisionEvent.feature_snapshot_json.is_(None)) | (SpotDecisionEvent.feature_snapshot_json == "")
        )) or 0
        future_events = await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts > now + 60
        )) or 0
        invalid_closes = await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.closed_at.isnot(None), SpotDecisionEvent.closed_at < SpotDecisionEvent.scan_ts
        )) or 0
        model_rows = list((await session.execute(select(SpotModelVersion).order_by(
            SpotModelVersion.trained_at.desc()
        ))).scalars().all())

    # ── Last 100 closed trades ─────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        trades_result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(_FUTURES_STYLES),
                PaperTrade.status.in_(["tp", "sl", "expired"]),
            ).order_by(PaperTrade.closed_at.desc()).limit(100)
        )
        recent_trades = [
            {
                "id":          t.id,
                "symbol":      t.symbol,
                "style":       t.style,
                "direction":   t.direction,
                "status":      t.status,
                "setup_type":  t.setup_type,
                "pnl_pct":     t.pnl_pct,
                "pnl_dollar":  t.pnl_dollar,
                "leverage":    t.leverage,
                "closed_at":   t.closed_at,
                "close_reason": json.loads(t.signals_json or "{}").get("close_reason"),
            }
            for t in trades_result.scalars().all()
        ]

    # ── In-memory cache state ──────────────────────────────────────────────────
    cache_state = {}
    try:
        from agents.futures.weight_updater import get_state as fut_cache
        cache_state["futures_weights"] = fut_cache()
    except Exception as e:
        cache_state["futures_weights"] = {"error": str(e)}

    try:
        from agents.shared.cross_agent_learning import get_state as cross_cache
        cache_state["cross_agent"] = cross_cache()
    except Exception as e:
        cache_state["cross_agent"] = {"error": str(e)}

    try:
        from agents.opportunity.weight_updater import get_state as spot_cache
        cache_state["spot_weights"] = spot_cache()
    except Exception as e:
        cache_state["spot_weights"] = {"error": str(e)}

    # ── Risk gate state ────────────────────────────────────────────────────────
    risk_gate = {}
    try:
        from agents.futures.risk_gate import get_gate_state
        risk_gate = get_gate_state()
    except Exception as e:
        risk_gate = {"error": str(e)}

    # ── Monitor state ──────────────────────────────────────────────────────────
    monitor_state = {}
    try:
        from agents.futures.monitor import get_state as mon_state
        monitor_state = mon_state()
    except Exception as e:
        monitor_state = {"error": str(e)}

    return {
        "snapshot_at":    now,
        "signal_weights": weights,
        "recent_trades":  recent_trades,
        "cache":          cache_state,
        "risk_gate":      risk_gate,
        "monitor":        monitor_state,
        "spot_decision_ledger": {
            "outcomes": decision_outcomes,
            "latest_scan_ts": latest_decision_ts,
            "quality": {
                "total": total_decisions,
                "unique_keys": unique_decisions,
                "duplicate_keys": total_decisions - unique_decisions,
                "missing_snapshots": missing_snapshots,
                "future_events": future_events,
                "invalid_closes": invalid_closes,
            },
        },
        "spot_model_registry": {
            "total": len(model_rows),
            "by_status": {
                status: sum(row.status == status for row in model_rows)
                for status in sorted({row.status for row in model_rows})
            },
            "latest_version": model_rows[0].version if model_rows else None,
            "latest_status": model_rows[0].status if model_rows else None,
        },
    }
