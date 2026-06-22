"""
Weekly Backtest API — P3.

GET /backtest/weekly        — last 8 weekly results
GET /backtest/weekly/run    — manual trigger (force=true)
"""

import time
from typing import Optional

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.backtest_result import WeeklyBacktestResult

router   = APIRouter(tags=["backtest"])
logger   = structlog.get_logger(__name__)


@router.get("/backtest/weekly")
async def get_weekly_backtest(limit: int = Query(8, ge=1, le=52)) -> dict:
    """Return the last N weekly backtest results, newest first."""
    if not is_db_available():
        return {"results": [], "error": "DB unavailable"}

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(WeeklyBacktestResult)
            .order_by(WeeklyBacktestResult.week_start.desc())
            .limit(limit)
        )).scalars().all())

    return {
        "results": [
            {
                "week_label":   r.week_label,
                "week_start":   r.week_start,
                "computed_at":  r.computed_at,
                "n_entries":    r.n_entries,
                "n_with_pnl":   r.n_with_pnl,
                "wr_1h":        r.wr_1h,
                "wr_4h":        r.wr_4h,
                "wr_24h":       r.wr_24h,
                "wr_7d":        r.wr_7d,
                "avg_pnl_24h":  r.avg_pnl_24h,
                "train_week":   r.train_week,
                "best_thresh":  r.best_thresh,
                "train_wr":     r.train_wr,
                "test_week":    r.test_week,
                "test_wr":      r.test_wr,
                "test_n":       r.test_n,
                "forward_pred": r.forward_pred,
                "forward_note": r.forward_note,
            }
            for r in rows
        ],
        "count": len(rows),
        "generated_at": int(time.time()),
    }


@router.post("/backtest/weekly/run")
async def trigger_weekly_backtest() -> dict:
    """Manually trigger the weekly backtest (force=True bypasses day-of-week check)."""
    try:
        from agents.learning.weekly_backtest import run_weekly_backtest
        result = await run_weekly_backtest(force=True)
        if result is None:
            return {"status": "skipped", "reason": "insufficient data or DB unavailable"}
        return {"status": "ok", "result": result}
    except Exception as exc:
        logger.error("manual_backtest_error", error=str(exc)[:120])
        return {"status": "error", "error": str(exc)[:120]}
