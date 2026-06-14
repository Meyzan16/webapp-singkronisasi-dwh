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

# F33/Phase 9: balance now comes from the real wallet; keep shared constants for the
# conservative-equity baseline and the legacy-row P&L fallback.
from app.services.trading_costs import (
    FUTURES_RISK_PCT as RISK_PCT,
    futures_pnl_dollar as _pnl_dollar,
)


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
                PaperTrade.style.in_(["futures_agent1", "futures_agent2", "futures_agent3"]),
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

    closed  = [t for t in all_trades if t.status in ("tp", "sl")]   # win-rate: expired excluded
    open_t  = [t for t in all_trades if t.status == "open"]
    # BUG-L19: balance/equity must include expired (real money moved), sorted by close time —
    # keeps the chart aligned with the wallet (which also counts expired). Win-rate stays tp/sl.
    balance_closed = sorted(
        [t for t in all_trades if t.status in ("tp", "sl", "expired")],
        key=lambda t: t.closed_at or 0,
    )

    def _is_real_win(t) -> bool:
        """BUG FIX: status=='tp' with negative net pnl is NOT a win."""
        return t.status == "tp" and (t.pnl_pct or 0.0) > 0

    # Phase 9: seed from the REAL futures wallet (initial + deposits − withdrawals),
    # so the chart and the wallet agree and deposits are reflected.
    from app.api.v1.balance import get_or_create_balance
    _wallet      = await get_or_create_balance("futures")
    wallet_base  = _wallet.initial_balance + _wallet.deposited_total - _wallet.withdrawn_total

    def _trade_pnl_dollar(t) -> float:
        """Stored real $ P&L; prefer the trade's real notional; $1000 constant only for
        truly ancient rows that have neither pnl_dollar nor position_size (BUG-L22)."""
        if t.pnl_dollar is not None:
            return t.pnl_dollar
        if t.position_size:
            return (t.pnl_pct or 0.0) / 100 * t.position_size
        try:
            risk_pct = json.loads(t.signals_json or "{}").get("risk_pct", 2.0)
        except Exception:
            risk_pct = 2.0
        return _pnl_dollar(t.pnl_pct or 0.0, risk_pct)

    # Balance simulation
    balance = wallet_base
    equity_points = []
    for t in balance_closed:        # BUG-L19: include expired so chart matches the wallet
        balance += _trade_pnl_dollar(t)
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
        entry["pnl_sum"] += _trade_pnl_dollar(t)   # Phase 9: real stored $ P&L

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
            "agent3": {"wins": 0, "total": 0},
        })
        if t.style == "futures_agent1":
            ak = "agent1"
        elif t.style == "futures_agent2":
            ak = "agent2"
        else:
            ak = "agent3"
        entry[ak]["total"] += 1
        if _is_real_win(t):
            entry[ak]["wins"] += 1

    monthly_stats = []
    for month_key in sorted(monthly.keys())[-6:]:  # last 6 months
        v = monthly[month_key]
        a1 = v["agent1"]
        a2 = v["agent2"]
        a3 = v["agent3"]
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
            "agent3": {
                "total":    a3["total"],
                "wins":     a3["wins"],
                "win_rate": round(a3["wins"] / a3["total"] * 100, 1) if a3["total"] > 0 else 0.0,
            },
        })

    # Conservative (flat R:R 1:3) equity — F65: derive from constants, not hardcoded $30/$10.
    # Phase 9: scale off the real wallet base so it sits alongside the actual curve.
    _risk_dollar = wallet_base * RISK_PCT   # loss per trade
    _win_dollar  = _risk_dollar * 3.0       # R:R 1:3 → win pays 3× risk
    nc_balance = wallet_base
    nc_points = []
    for ep in equity_points:
        win = ep["win"]
        nc_balance += _win_dollar if win else -_risk_dollar
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
        "agent3":        agent_stats("futures_agent3"),
        "balance": {
            "starting":  round(wallet_base, 2),                     # Phase 9: real base (incl. deposits)
            "current":   round(balance, 2),
            "total_pnl": round(balance - wallet_base, 2),
            "roi_pct":   round((balance - wallet_base) / wallet_base * 100, 2) if wallet_base > 0 else 0.0,
        },
        "equity_points":   equity_points,         # F66: full journey from $start (no slice)
        "win_rate_trend":  trend[-20:],           # last 20 for trend chart
        "top_signals":     top_signals,
        "bottom_signals":  bottom_signals,
        "regime_breakdown": regime_breakdown,
        "direction_stats": {
            "long":  {"total": len(long_closed),  "wins": len(long_wins),  "win_rate": round(len(long_wins)/len(long_closed)*100, 1) if long_closed else 0.0},
            "short": {"total": len(short_closed), "wins": len(short_wins), "win_rate": round(len(short_wins)/len(short_closed)*100, 1) if short_closed else 0.0},
        },
        "leverage_dist":   lev_dist,
        "conservative_equity": nc_points,   # F66: full journey (no slice)
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
