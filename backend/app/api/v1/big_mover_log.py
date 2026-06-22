"""
Big Mover Log API — Phase 1 T4.

GET /api/v1/big-mover-log/stats   — hypothetical win rate per horizon
GET /api/v1/big-mover-log/entries — recent rows (paginated)
POST /api/v1/big-mover-log/backfill — manual trigger (debug)
"""

import time
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func

from app.database import AsyncSessionLocal, is_db_available
from app.models.big_mover_log import BigMoverLog

router = APIRouter(tags=["big-mover-log"])
logger = structlog.get_logger(__name__)


@router.get("/big-mover-log/stats")
async def get_stats(
    market: str = Query("all", description="all | futures | spot"),
    days:   int = Query(7,    ge=1, le=30),
) -> dict:
    """
    Hypothetical win rate stats per horizon.
    'win' = forward pnl positive (after assumed slippage applied at logger).
    """
    if not is_db_available():
        raise HTTPException(status_code=503, detail="DB tidak tersedia")

    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as s:
        q = select(BigMoverLog).where(BigMoverLog.ts >= cutoff)
        if market != "all":
            q = q.where(BigMoverLog.market == market)
        rows = list((await s.execute(q)).scalars().all())

    def _wr(horizon_attr: str) -> dict:
        vals = [getattr(r, horizon_attr) for r in rows if getattr(r, horizon_attr) is not None]
        if not vals:
            return {"n": 0, "wins": 0, "win_rate": None, "avg_pnl_pct": None, "median_pnl_pct": None}
        wins = sum(1 for v in vals if v > 0)
        avg  = sum(vals) / len(vals)
        sorted_v = sorted(vals)
        med = sorted_v[len(sorted_v) // 2]
        return {
            "n":              len(vals),
            "wins":           wins,
            "win_rate":       round(wins / len(vals) * 100, 1),
            "avg_pnl_pct":    round(avg, 2),
            "median_pnl_pct": round(med, 2),
        }

    hypothetical = {
        "n":           sum(1 for r in rows if r.would_be_status is not None),
        "wins":        sum(1 for r in rows if r.would_be_status == "tp"),
        "losses":      sum(1 for r in rows if r.would_be_status == "sl"),
        "open":        sum(1 for r in rows if r.would_be_status == "open"),
    }
    n_decided = hypothetical["wins"] + hypothetical["losses"]
    hypothetical["win_rate"] = round(hypothetical["wins"] / n_decided * 100, 1) if n_decided > 0 else None

    # Status breakdown
    by_status = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    return {
        "market":         market,
        "days":           days,
        "total_rows":     len(rows),
        "status_counts":  by_status,
        "by_horizon": {
            "1h":  _wr("pnl_1h_pct"),
            "4h":  _wr("pnl_4h_pct"),
            "24h": _wr("pnl_24h_pct"),
            "7d":  _wr("pnl_7d_pct"),
        },
        "hypothetical_tp_sl": hypothetical,
        "generated_at":   int(time.time()),
    }


@router.get("/big-mover-log/entries")
async def get_entries(
    market:    str = Query("all"),
    status:    Optional[str] = Query(None, description="missed | opened | manual"),
    limit:     int = Query(100, ge=1, le=500),
    offset:    int = Query(0, ge=0),
) -> dict:
    """Paginated rows, most recent first."""
    if not is_db_available():
        raise HTTPException(status_code=503, detail="DB tidak tersedia")

    async with AsyncSessionLocal() as s:
        q = select(BigMoverLog)
        if market != "all":
            q = q.where(BigMoverLog.market == market)
        if status:
            q = q.where(BigMoverLog.status == status)
        q = q.order_by(BigMoverLog.ts.desc()).offset(offset).limit(limit)
        rows = list((await s.execute(q)).scalars().all())

        # Total for pagination
        cq = select(func.count(BigMoverLog.id))
        if market != "all":
            cq = cq.where(BigMoverLog.market == market)
        if status:
            cq = cq.where(BigMoverLog.status == status)
        total = int((await s.execute(cq)).scalar() or 0)

    entries = [
        {
            "id":          r.id,
            "ts":          r.ts,
            "symbol":      r.symbol,
            "market":      r.market,
            "direction":   r.direction,
            "change_24h":  r.change_24h,
            "scan_price":  r.scan_price,
            "max_score":   r.max_score,
            "threshold":   r.threshold,
            "scoring_gap": r.scoring_gap,
            "funding_rate": r.funding_rate,
            "status":      r.status,
            "reason":      r.reason,
            "pnl_1h_pct":  r.pnl_1h_pct,
            "pnl_4h_pct":  r.pnl_4h_pct,
            "pnl_24h_pct": r.pnl_24h_pct,
            "pnl_7d_pct":  r.pnl_7d_pct,
            "would_be_status":   r.would_be_status,
            "would_be_pnl_pct":  r.would_be_pnl_pct,
        }
        for r in rows
    ]
    return {
        "entries": entries,
        "total":   total,
        "offset":  offset,
        "limit":   limit,
    }


@router.post("/big-mover-log/backfill")
async def trigger_backfill(max_rows: int = Query(100, ge=1, le=500)) -> dict:
    """Manual backfill trigger — for debug. Scheduler runs this automatically."""
    from app.services.big_mover_logger import backfill_pending
    updated = await backfill_pending(max_rows=max_rows)
    return {"updated": updated}
