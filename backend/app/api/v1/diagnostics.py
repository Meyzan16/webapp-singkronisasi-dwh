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
from sqlalchemy import select

from app.database import AsyncSessionLocal, require_db
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight

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
                AgentSignalWeight.agent.in_(_FUTURES_STYLES),
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
    }
