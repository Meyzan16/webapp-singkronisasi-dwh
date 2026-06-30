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
from app.services.trading_costs import FUTURES_STARTING_BALANCE, FUTURES_RISK_PCT

router = APIRouter(tags=["history"])
logger = structlog.get_logger(__name__)

_db = Depends(require_db)

_FUTURES_STYLES = [
    "futures_agent1", "futures_agent2", "futures_agent3",
    "futures_agent_bigmover",   # Phase 2 BM1
]


def _parse_rr(rr: Optional[str]) -> float:
    """F50: robust R:R parse — handles '1:3', '1:3.5', bare '3.5', or malformed."""
    if not rr:
        return 0.0
    try:
        return float(rr.split(":")[1]) if ":" in rr else float(rr)
    except (ValueError, IndexError):
        return 0.0


def _apply_trade_filters(q, style: Optional[str], search: Optional[str]):
    """F45: shared style + symbol-search filter so paginated and summary queries match."""
    if style and style != "all":
        if style == "spot":
            q = q.where(PaperTrade.style == "opportunity_spot")
        elif style == "agent1":
            q = q.where(PaperTrade.style == "futures_agent1")
        elif style == "agent2":
            q = q.where(PaperTrade.style == "futures_agent2")
        elif style == "agent3":
            q = q.where(PaperTrade.style == "futures_agent3")
        elif style == "futures":
            q = q.where(PaperTrade.style.in_(_FUTURES_STYLES))
        else:
            q = q.where(PaperTrade.style == style)
    if search and search.strip():
        q = q.where(PaperTrade.symbol.like(f"%{search.strip().upper()}%"))
    return q


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
        "rr_ratio":    _parse_rr(t.risk_reward),
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
        "entry_at":       t.entry_at,
        "closed_at":      t.closed_at,
        "agent":          t.style,
        "position_size":  t.position_size,
        "risk_dollar":    t.risk_dollar,
        "balance_snapshot": t.balance_snapshot,
        "pnl_dollar":     t.pnl_dollar,
    }


@router.get("/history/trades", dependencies=[_db])
async def get_trades(
    style:     Optional[str] = Query(None),
    status:    Optional[str] = Query(None),
    search:    Optional[str] = Query(None),   # symbol search (partial match)
    days:      int           = Query(90),
    page:      int           = Query(1, ge=1),
    page_size: int           = Query(25, ge=1, le=200),
    sort_by:   str           = Query("entry_at"),  # entry_at | closed_at | pnl_pct | score
    sort_dir:  str           = Query("desc"),       # desc | asc
) -> dict:
    """
    Paginated trade history with search, filter, and sort.
    Returns: trades (current page), total, page, pages, stats summary.
    """
    from sqlalchemy import func, or_

    cutoff = time.time() - days * 86400

    async with AsyncSessionLocal() as s:
        q = select(PaperTrade).where(PaperTrade.entry_at >= cutoff)
        q = _apply_trade_filters(q, style, search)   # F45: shared filter

        # Status filter — §16.5: "win" konsisten dengan _is_real_win (tp + net > 0)
        if status and status != "all":
            if status == "win":
                q = q.where(PaperTrade.status == "tp", PaperTrade.pnl_pct > 0)
            elif status == "loss":
                from sqlalchemy import and_ as _and, or_ as _or
                q = q.where(_or(
                    PaperTrade.status == "sl",
                    _and(PaperTrade.status == "tp", PaperTrade.pnl_pct <= 0),
                ))
            elif status == "open":
                q = q.where(PaperTrade.status == "open")
            else:
                q = q.where(PaperTrade.status == status)

        # Total count (before pagination)
        count_q  = select(func.count()).select_from(q.subquery())
        total    = (await s.execute(count_q)).scalar() or 0

        # Sort
        sort_col = {
            "entry_at":  PaperTrade.entry_at,
            "closed_at": PaperTrade.closed_at,
            "pnl_pct":   PaperTrade.pnl_pct,
            "score":     PaperTrade.probability,
            "symbol":    PaperTrade.symbol,
        }.get(sort_by, PaperTrade.entry_at)

        if sort_dir == "asc":
            q = q.order_by(sort_col.asc().nullslast())
        else:
            q = q.order_by(sort_col.desc().nullslast())

        # Pagination
        offset = (page - 1) * page_size
        q = q.offset(offset).limit(page_size)

        result = await s.execute(q)
        trades  = [_trade_dict(t) for t in result.scalars().all()]

        # Quick summary stats (across full filtered set, not just this page)
        all_q = select(PaperTrade).where(PaperTrade.entry_at >= cutoff)
        all_q = _apply_trade_filters(all_q, style, search)   # F45: same shared filter

        all_result = await s.execute(all_q)
        all_trades = list(all_result.scalars().all())

    # §6.2: summary konsisten dengan balance — manual ikut dihitung sebagai closed
    tp_sl   = [t for t in all_trades if t.status in ("tp", "sl")]
    manual  = [t for t in all_trades if t.status == "manual"]
    closed  = tp_sl + manual
    wins    = [t for t in tp_sl if _is_real_win(t)]
    open_t  = [t for t in all_trades if t.status == "open"]
    avg_pnl = (sum(t.pnl_pct for t in closed if t.pnl_pct is not None) / len(closed)) if closed else 0.0
    realized_dollar = sum(t.pnl_dollar for t in closed if t.pnl_dollar is not None)

    # §14.8: max drawdown + profit factor — metrik kunci "profit dengan risiko baik"
    gross_win  = sum(t.pnl_dollar for t in closed if (t.pnl_dollar or 0) > 0)
    gross_loss = abs(sum(t.pnl_dollar for t in closed if (t.pnl_dollar or 0) < 0))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for t in sorted(closed, key=lambda x: x.closed_at or 0):
        equity += t.pnl_dollar or 0.0
        peak    = max(peak, equity)
        max_dd  = max(max_dd, peak - equity)

    return {
        "trades":    trades,
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     max(1, -(-total // page_size)),  # ceiling division
        "summary": {
            "total_all":        len(all_trades),
            "open":             len(open_t),
            "closed":           len(closed),
            "manual_count":     len(manual),
            "wins":             len(wins),
            "losses":           len(tp_sl) - len(wins),
            "win_rate":         round(len(wins) / len(tp_sl) * 100, 1) if tp_sl else 0.0,
            "avg_pnl":          round(avg_pnl, 2),
            "realized_pnl_dollar": round(realized_dollar, 2),
            "profit_factor":    profit_factor,
            "max_drawdown_dollar": round(max_dd, 2),
        },
    }


def _is_real_win(t: PaperTrade) -> bool:
    """
    BUG FIX: A trade is a REAL win only if:
      1. status == "tp" AND
      2. net pnl_pct > 0 (not negative after fees)
    Previously we counted status=="tp" with pnl_pct=-0.16 as a "win" — wrong!
    """
    if t.status != "tp":
        return False
    return (t.pnl_pct or 0.0) > 0


@router.get("/history/stats", dependencies=[_db])
async def get_stats(days: int = Query(90)) -> dict:
    cutoff = time.time() - days * 86400   # F48: bound query by time window
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(PaperTrade).where(PaperTrade.entry_at >= cutoff)
        )
        all_trades = list(result.scalars().all())

    closed = [t for t in all_trades if t.status in ("tp", "sl", "manual", "expired")]
    # BUG FIX: real wins require positive net pnl (status "tp" with negative pnl is a loss)
    wins   = [t for t in closed if _is_real_win(t)]

    by_style: dict = defaultdict(lambda: {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_pnl": 0.0})
    for t in closed:
        st = by_style[t.style]
        st["total"] += 1
        if _is_real_win(t):
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
            # F53: include break-even (pnl_pct == 0.0) in the average
            "avg_pnl":  sum(t.pnl_pct for t in closed if t.pnl_pct is not None) / len(closed) if closed else 0.0,
        },
        "by_style": dict(by_style),
    }


@router.get("/history/equity", dependencies=[_db])
async def get_equity(style: str = Query("futures")) -> dict:
    import json

    # F103: filter by style so the curve isn't a mix of futures + spot
    if style == "spot":
        style_filter = [PaperTrade.style == "opportunity_spot"]
    elif style == "agent1":
        style_filter = [PaperTrade.style == "futures_agent1"]
    elif style == "agent2":
        style_filter = [PaperTrade.style == "futures_agent2"]
    elif style == "agent3":
        style_filter = [PaperTrade.style == "futures_agent3"]
    elif style == "all":
        style_filter = []
    else:  # "futures" (default)
        style_filter = [PaperTrade.style.in_(_FUTURES_STYLES)]

    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(PaperTrade)
            .where(PaperTrade.status.in_(["tp", "sl", "manual", "expired"]), *style_filter)
            .order_by(PaperTrade.closed_at)
        )
        trades = list(result.scalars().all())

    # F41: single source of truth from trading_costs.py
    BALANCE     = FUTURES_STARTING_BALANCE
    RISK_DOLLAR = BALANCE * FUTURES_RISK_PCT

    balance = BALANCE
    points  = [{"trade_n": 0, "balance": balance, "win": True, "symbol": "start"}]
    for i, t in enumerate(trades, 1):
        if t.pnl_pct is None or t.entry_price <= 0:
            continue
        # F44: use original risk_pct from signals_json — current SL may be trailed
        try:
            meta = json.loads(t.signals_json or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        risk_pct_val = meta.get("risk_pct_original") or meta.get("risk_pct") or 2.0
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
            .where(PaperTrade.closed_at >= cutoff, PaperTrade.status.in_(["tp", "sl", "manual", "expired"]))
            .order_by(PaperTrade.closed_at)
        )
        trades = list(result.scalars().all())

    daily: dict = defaultdict(lambda: {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0})
    for t in trades:
        day = datetime.datetime.fromtimestamp(t.closed_at or 0).strftime("%Y-%m-%d")
        d   = daily[day]
        d["trades"] += 1
        if t.pnl_pct is not None:   # F42: include break-even (0.0) trades
            d["pnl"] = round(d["pnl"] + t.pnl_pct, 2)
        if _is_real_win(t):
            d["wins"] += 1
        else:
            d["losses"] += 1

    return {"daily": [{"date": k, **v} for k, v in sorted(daily.items())]}


@router.delete("/history/cleanup-legacy", dependencies=[_db])
async def cleanup_legacy_trades() -> dict:
    """
    Remove closed opportunity_spot trades that have no position_size data
    (legacy trades from before real-balance tracking was added).
    Keeps all open trades and all futures trades untouched.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style    == "opportunity_spot",
                PaperTrade.status   != "open",
                PaperTrade.position_size.is_(None),
            )
        )
        legacy = list(result.scalars().all())
        count  = len(legacy)
        for t in legacy:
            await session.delete(t)
        await session.commit()

    logger.info("legacy_trades_cleaned", deleted=count)
    return {"deleted": count, "message": f"{count} trade lama tanpa data margin dihapus"}


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
