"""
Futures Learning API.

GET  /futures/learning/stats    — win rates, regime, balance sim, win rate trend
GET  /futures/learning/weights  — signal weights per agent
POST /futures/learning/update   — force weight recalculation
"""

import json
import time

import structlog
from fastapi import APIRouter
from sqlalchemy import select

router = APIRouter(tags=["futures-learning"])
logger = structlog.get_logger(__name__)

from app.services.trading_costs import FUTURES_STARTING_BALANCE as STARTING_BALANCE, FUTURES_RISK_PCT as RISK_PCT


def _notional(risk_pct: float) -> float:
    return STARTING_BALANCE * RISK_PCT / (risk_pct / 100) if risk_pct > 0 else 0


def _pnl_dollar(pnl_pct: float, risk_pct: float) -> float:
    return pnl_pct / 100 * _notional(risk_pct)


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/futures/learning/stats")
async def get_learning_stats() -> dict:
    """
    Returns:
      - Overall win rate (both agents)
      - Win rate per agent
      - Simulated balance ($1000 start, 1% risk)
      - Current market regime
      - Win rate over last 10 trades (trend)
      - Top 5 best/worst performing signals
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from app.models.signal_weight import AgentSignalWeight
    from agents.futures.regime import get_cached_regime
    from agents.futures.monitor import get_state as monitor_state
    from agents.futures.weight_updater import get_state as updater_state

    if not is_db_available():
        return {"error": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(["futures_agent1", "futures_agent2"]),
            ).order_by(PaperTrade.entry_at)
        )
        all_trades = list(result.scalars().all())

        weights_result = await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.total_count >= 2,
                AgentSignalWeight.regime == "all",
            ).order_by(AgentSignalWeight.win_rate.desc())
        )
        weights = list(weights_result.scalars().all())

    closed  = [t for t in all_trades if t.status in ("tp", "sl")]   # expired excluded — not real outcomes
    open_t  = [t for t in all_trades if t.status == "open"]

    def _is_real_win(t) -> bool:
        """BUG FIX: status=='tp' with negative net pnl is NOT a win."""
        return t.status == "tp" and (t.pnl_pct or 0.0) > 0

    # Balance simulation
    balance = STARTING_BALANCE
    equity_points = []
    for t in closed:
        try:
            meta     = json.loads(t.signals_json or "{}")
            risk_pct = meta.get("risk_pct", 2.0)
        except Exception:
            risk_pct = 2.0
        pnl_d = _pnl_dollar(t.pnl_pct or 0.0, risk_pct)
        balance += pnl_d
        equity_points.append({
            "trade_n": len(equity_points) + 1,
            "balance": round(balance, 2),
            "symbol":  t.symbol,
            "win":     t.status == "tp",
            "agent":   t.style,
            "ts":      t.closed_at,
        })

    wins   = [t for t in closed if _is_real_win(t)]
    losses = [t for t in closed if not _is_real_win(t)]
    wr     = len(wins) / len(closed) * 100 if closed else 0.0

    # Per-agent
    def agent_stats(agent_name: str) -> dict:
        ag_closed = [t for t in closed if t.style == agent_name]
        ag_wins   = [t for t in ag_closed if _is_real_win(t)]
        ag_rate   = len(ag_wins) / len(ag_closed) * 100 if ag_closed else 0.0
        return {
            "total":    len(ag_closed),
            "wins":     len(ag_wins),
            "losses":   len(ag_closed) - len(ag_wins),
            "win_rate": round(ag_rate, 1),
        }

    # Win rate trend: last 10 closed trades (rolling)
    trend = []
    window = 10
    for i in range(len(closed)):
        start = max(0, i - window + 1)
        chunk = closed[start: i + 1]
        chunk_wins = sum(1 for t in chunk if _is_real_win(t))
        trend.append({
            "trade_n":  i + 1,
            "win_rate": round(chunk_wins / len(chunk) * 100, 1),
            "win":      _is_real_win(closed[i]),
        })

    # Signal performance
    top_signals    = [{"key": w.signal_key, "agent": w.agent, "win_rate": round(w.win_rate * 100, 1),
                       "weight": w.weight, "total": w.total_count, "wins": w.win_count}
                      for w in weights[:5]]
    bottom_signals = [{"key": w.signal_key, "agent": w.agent, "win_rate": round(w.win_rate * 100, 1),
                       "weight": w.weight, "total": w.total_count, "wins": w.win_count}
                      for w in sorted(weights, key=lambda x: x.win_rate)[:5]
                      if w.total_count >= 3]

    # Regime breakdown: win rate + count per regime
    regime_map: dict[str, dict] = {}
    for t in closed:
        r = t.regime or "unknown"
        entry = regime_map.setdefault(r, {"wins": 0, "total": 0, "pnl_sum": 0.0})
        entry["total"] += 1
        if _is_real_win(t):
            entry["wins"] += 1
        try:
            meta     = json.loads(t.signals_json or "{}")
            risk_pct = meta.get("risk_pct", 2.0)
        except Exception:
            risk_pct = 2.0
        entry["pnl_sum"] += _pnl_dollar(t.pnl_pct or 0.0, risk_pct)

    regime_breakdown = [
        {
            "regime":    r,
            "total":     v["total"],
            "wins":      v["wins"],
            "win_rate":  round(v["wins"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0,
            "pnl_dollar": round(v["pnl_sum"], 2),
        }
        for r, v in regime_map.items()
    ]

    # Per-direction stats
    long_closed  = [t for t in closed if t.direction == "LONG"]
    short_closed = [t for t in closed if t.direction == "SHORT"]
    long_wins    = [t for t in long_closed  if _is_real_win(t)]
    short_wins   = [t for t in short_closed if _is_real_win(t)]

    # Leverage distribution: how many trades per leverage bucket
    lev_dist: dict[str, int] = {}
    for t in all_trades:
        lev = t.leverage or 1
        bucket = f"{lev}x"
        lev_dist[bucket] = lev_dist.get(bucket, 0) + 1

    # Monthly win rate per agent (last 6 months)
    import datetime as dt
    monthly: dict[str, dict] = {}
    for t in closed:
        if not t.entry_at:
            continue
        month_key = dt.datetime.utcfromtimestamp(t.entry_at).strftime("%Y-%m")
        entry = monthly.setdefault(month_key, {
            "month": month_key,
            "agent1": {"wins": 0, "total": 0},
            "agent2": {"wins": 0, "total": 0},
        })
        ak = "agent1" if t.style == "futures_agent1" else "agent2"
        entry[ak]["total"] += 1
        if _is_real_win(t):
            entry[ak]["wins"] += 1

    monthly_stats = []
    for month_key in sorted(monthly.keys())[-6:]:  # last 6 months
        v = monthly[month_key]
        a1 = v["agent1"]
        a2 = v["agent2"]
        monthly_stats.append({
            "month": month_key,
            "agent1": {
                "total":    a1["total"],
                "wins":     a1["wins"],
                "win_rate": round(a1["wins"] / a1["total"] * 100, 1) if a1["total"] > 0 else 0.0,
            },
            "agent2": {
                "total":    a2["total"],
                "wins":     a2["wins"],
                "win_rate": round(a2["wins"] / a2["total"] * 100, 1) if a2["total"] > 0 else 0.0,
            },
        })

    # Conservative (no-leverage) equity: each win = +$30, loss = -$10 flat
    nc_balance = STARTING_BALANCE
    nc_points = []
    for ep in equity_points:
        win = ep["win"]
        nc_balance += 30.0 if win else -10.0
        nc_points.append({"trade_n": ep["trade_n"], "balance": round(nc_balance, 2)})

    return {
        "regime":          get_cached_regime(),
        "target_win_rate": 80.0,
        "overall": {
            "total":     len(all_trades),
            "open":      len(open_t),
            "closed":    len(closed),
            "wins":      len(wins),
            "losses":    len(losses),
            "win_rate":  round(wr, 1),
        },
        "agent1":        agent_stats("futures_agent1"),
        "agent2":        agent_stats("futures_agent2"),
        "balance": {
            "starting":  STARTING_BALANCE,
            "current":   round(balance, 2),
            "total_pnl": round(balance - STARTING_BALANCE, 2),
            "roi_pct":   round((balance - STARTING_BALANCE) / STARTING_BALANCE * 100, 2),
        },
        "equity_points":   equity_points[-50:],  # last 50 for chart
        "win_rate_trend":  trend[-20:],           # last 20 for trend chart
        "top_signals":     top_signals,
        "bottom_signals":  bottom_signals,
        "regime_breakdown": regime_breakdown,
        "direction_stats": {
            "long":  {"total": len(long_closed),  "wins": len(long_wins),  "win_rate": round(len(long_wins)/len(long_closed)*100, 1) if long_closed else 0.0},
            "short": {"total": len(short_closed), "wins": len(short_wins), "win_rate": round(len(short_wins)/len(short_closed)*100, 1) if short_closed else 0.0},
        },
        "leverage_dist":   lev_dist,
        "conservative_equity": nc_points[-50:],
        "monthly_stats":   monthly_stats,
        "monitor":         monitor_state(),
        "updater":         updater_state(),
        "generated_at":    time.time(),
    }


# ── Weights ───────────────────────────────────────────────────────────────────

@router.get("/futures/learning/weights")
async def get_signal_weights(
    agent:  str = "all",
    regime: str = "all",
) -> dict:
    """All adaptive signal weights."""
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.signal_weight import AgentSignalWeight

    if not is_db_available():
        return {"weights": [], "total": 0}

    conditions = [AgentSignalWeight.total_count >= 1]
    if agent != "all":
        conditions.append(AgentSignalWeight.agent == agent)
    if regime != "all":
        conditions.append(AgentSignalWeight.regime == regime)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentSignalWeight)
            .where(*conditions)
            .order_by(AgentSignalWeight.win_rate.desc())
            .limit(100)
        )
        rows = result.scalars().all()

    return {
        "weights": [
            {
                "agent":       r.agent,
                "signal_key":  r.signal_key,
                "weight":      r.weight,
                "win_rate":    round(r.win_rate * 100, 1),
                "win_count":   r.win_count,
                "total_count": r.total_count,
                "regime":      r.regime,
                "updated_at":  r.updated_at,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── Force update ──────────────────────────────────────────────────────────────

@router.post("/futures/learning/update")
async def force_weight_update() -> dict:
    """Trigger immediate signal weight recalculation."""
    from agents.futures.weight_updater import update_weights
    from agents.futures.regime import fetch_regime

    regime  = await fetch_regime()
    updated = await update_weights()
    return {"updated_rows": updated, "regime": regime, "ts": time.time()}
