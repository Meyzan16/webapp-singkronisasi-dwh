"""
History API — paper-trade tracking backed by PostgreSQL.
Returns 503 when DB is unavailable.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query

from app.database import require_db
from agents.paper_trader import trader as paper_trader

router = APIRouter(tags=["history"])
logger = structlog.get_logger(__name__)

# All history endpoints require DB — inject require_db as a dependency
_db = Depends(require_db)


@router.get("/history/trades", dependencies=[_db])
async def get_trades(
    style:  Optional[str] = Query(None,  description="scalping|daytrading|swing|position"),
    status: Optional[str] = Query(None,  description="open|tp|sl"),
    days:   int           = Query(14,    description="Number of days to look back"),
) -> dict:
    """Return paper trades from PostgreSQL, optionally filtered."""
    await paper_trader.maybe_check_trades()
    trades = await paper_trader.get_all_trades(style=style, status=status, days=days)
    return {"trades": trades, "total": len(trades)}


@router.get("/history/stats", dependencies=[_db])
async def get_stats() -> dict:
    """Accuracy stats overall and per trading style."""
    await paper_trader.maybe_check_trades()
    return await paper_trader.get_stats()


@router.get("/history/equity", dependencies=[_db])
async def get_equity() -> dict:
    """Equity curve — cumulative PnL assuming 1% risk per trade."""
    return {"points": await paper_trader.get_equity_curve()}


@router.post("/history/check", dependencies=[_db])
async def force_check() -> dict:
    """Manually trigger SL/TP price check for all open trades."""
    closed = await paper_trader.check_and_close_trades()
    return {"closed": closed, "message": f"{closed} trade(s) closed"}


@router.get("/history/daily-pnl", dependencies=[_db])
async def get_daily_pnl(days: int = Query(30, description="Number of days to include")) -> dict:
    """
    Daily PnL aggregation for calendar view.
    Returns one entry per day with total PnL, wins, losses, and trade count.
    """
    return await paper_trader.get_daily_pnl(days=days)


@router.delete("/history/all", dependencies=[_db])
async def clear_all_trades() -> dict:
    """Delete all paper trades — hard reset. Used when changing scoring rules."""
    from sqlalchemy import text
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("DELETE FROM paper_trades"))
        await session.commit()
        deleted = result.rowcount
    logger.info("paper_trades_cleared", deleted=deleted)
    return {"deleted": deleted, "message": "All paper trades cleared."}
