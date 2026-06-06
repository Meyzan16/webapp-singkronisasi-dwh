"""
History API — paper-trade tracking backed by PostgreSQL.
Direct DB queries — no legacy paper_trader dependency.
"""

import time
from collections import defaultdict
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal, require_db
from app.models.paper_trade import PaperTrade

router = APIRouter(tags=["history"])
logger = structlog.get_logger(__name__)

_db = Depends(require_db)


def _trade_dict(t: PaperTrade) -> dict:
    import json
    try:
        meta = json.loads(t.signals_json or "{}")
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}

    return {
        "id":          t.id,
        "symbol":      t.symbol,
        "direction":   t.direction,
        "style":       t.style,
        "status":      t.status,
        "entry":       t.entry_price,
        "sl":          t.stop_loss,
        "tp2":         t.take_profit,
        "tp1":         meta.get("tp1"),
        "tp3":         meta.get("tp3"),
        "risk_pct":    meta.get("risk_pct", 0),
        "tp2_pct":     meta.get("tp2_pct", 0),
        "tp3_pct":     meta.get("tp3_pct", 0),
        "rr_ratio":    float(t.risk_reward.split(":")[1]) if t.risk_reward and ":" in t.risk_reward else 0,
        "score":       t.probability,
        "leverage":    t.leverage,
        "margin_type": t.margin_type,
        "signals":     meta.get("signals", []) if isinstance(meta.get("signals"), list) else [],
        "alert_type":  t.alert_type,
        "pnl_pct":     t.pnl_pct,
        "pnl_gross_pct": meta.get("pnl_gross_pct"),
        "fee_pct":     meta.get("fee_pct"),
        "close_price": t.close_price,
        "close_reason": meta.get("close_reason"),
        "tp1_hit":     meta.get("tp1_hit", False),
        "current_price": None,
        "unrealized_pnl_pct": None,
        "entry_at":    t.entry_at,
        "closed_at":   t.closed_at,
        "agent":       t.style,
    }


@router.get("/history/trades", dependencies=[_db])
async def get_trades(
    style:  Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days:   int           = Query(30),
) -> dict:
    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as s:
        q = select(PaperTrade).where(PaperTrade.entry_at >= cutoff)
        if style:
            q = q.where(PaperTrade.style == style)
        if status:
            q = q.where(PaperTrade.status == status)
        q = q.order_by(PaperTrade.entry_at.desc())
        result = await s.execute(q)
        trades = [_trade_dict(t) for t in result.scalars().all()]
    return {"trades": trades, "total": len(trades)}


@router.get("/history/stats", dependencies=[_db])
async def get_stats() -> dict:
    async with AsyncSessionLocal() as s:
        result = await s.execute(select(PaperTrade))
        all_trades = list(result.scalars().all())

    closed = [t for t in all_trades if t.status in ("tp", "sl")]
    wins   = [t for t in closed if t.status == "tp"]

    by_style: dict = defaultdict(lambda: {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_pnl": 0.0})
    for t in closed:
        st = by_style[t.style]
        st["total"] += 1
        if t.status == "tp":
            st["wins"] += 1
        else:
            st["losses"] += 1
        if t.pnl_pct is not None:
            st["avg_pnl"] = (st["avg_pnl"] * (st["total"] - 1) + t.pnl_pct) / st["total"]
    for st in by_style.values():
        st["win_rate"] = st["wins"] / st["total"] * 100 if st["total"] > 0 else 0.0

    return {
        "overall": {
            "total":    len(all_trades),
            "open":     sum(1 for t in all_trades if t.status == "open"),
            "closed":   len(closed),
            "wins":     len(wins),
            "losses":   len(closed) - len(wins),
            "win_rate": len(wins) / len(closed) * 100 if closed else 0.0,
            "avg_pnl":  sum(t.pnl_pct for t in closed if t.pnl_pct) / len(closed) if closed else 0.0,
        },
        "by_style": dict(by_style),
    }


@router.get("/history/equity", dependencies=[_db])
async def get_equity() -> dict:
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(PaperTrade)
            .where(PaperTrade.status.in_(["tp", "sl"]))
            .order_by(PaperTrade.closed_at)
        )
        trades = list(result.scalars().all())

    BALANCE     = 1000.0
    RISK_PCT    = 0.01
    RISK_DOLLAR = BALANCE * RISK_PCT  # $10

    balance = BALANCE
    points  = [{"trade_n": 0, "balance": balance, "win": True, "symbol": "start"}]
    for i, t in enumerate(trades, 1):
        if t.pnl_pct is None or t.stop_loss <= 0 or t.entry_price <= 0:
            continue
        risk_pct_val = abs(t.entry_price - t.stop_loss) / t.entry_price * 100
        if risk_pct_val <= 0:
            continue
        notional = RISK_DOLLAR / (risk_pct_val / 100)
        pnl_dollar = (t.pnl_pct / 100) * notional
        balance = max(0, balance + pnl_dollar)
        points.append({
            "trade_n": i,
            "balance": round(balance, 2),
            "win":     t.status == "tp",
            "symbol":  t.symbol,
        })

    return {"points": points}


@router.get("/history/daily-pnl", dependencies=[_db])
async def get_daily_pnl(days: int = Query(30)) -> dict:
    import datetime
    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(PaperTrade)
            .where(PaperTrade.closed_at >= cutoff, PaperTrade.status.in_(["tp", "sl"]))
            .order_by(PaperTrade.closed_at)
        )
        trades = list(result.scalars().all())

    daily: dict = defaultdict(lambda: {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0})
    for t in trades:
        day = datetime.datetime.fromtimestamp(t.closed_at or 0).strftime("%Y-%m-%d")
        d   = daily[day]
        d["trades"] += 1
        if t.pnl_pct:
            d["pnl"] = round(d["pnl"] + t.pnl_pct, 2)
        if t.status == "tp":
            d["wins"] += 1
        else:
            d["losses"] += 1

    return {"daily": [{"date": k, **v} for k, v in sorted(daily.items())]}


@router.delete("/history/all", dependencies=[_db])
async def clear_all_trades(
    style: Optional[str] = Query(None)
) -> dict:
    """Hard reset paper trades by style."""
    scanner_styles = ["scalping", "daytrading", "swing", "position"]
    async with AsyncSessionLocal() as session:
        if style:
            result = await session.execute(delete(PaperTrade).where(PaperTrade.style == style))
        else:
            result = await session.execute(delete(PaperTrade).where(PaperTrade.style.in_(scanner_styles)))
        await session.commit()
        deleted = result.rowcount
    logger.info("paper_trades_cleared", style=style or "scanner", deleted=deleted)
    return {"deleted": deleted, "style": style or "scanner"}
