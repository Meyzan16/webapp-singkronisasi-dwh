"""
Predictive Signal API — PLAN_v3 P4 D4.2.

GET /predictive/hit_rate  — accuracy of each agent's signals over resolved predictions.
GET /predictive/recent    — recent unresolved/resolved predictions.
POST /predictive/resolve  — trigger resolution of stale predictions (admin).
"""

import json
import time

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, update

from app.database import AsyncSessionLocal, require_db
from app.models.predictive_log import PredictiveLog

router = APIRouter(tags=["predictive"])

_FUTURES_AGENTS = [
    "futures_agent1", "futures_agent2", "futures_agent3", "futures_agent_bigmover",
]

# Minimum move for a hit (4h: 1.5%, 24h: 3%)
_HIT_4H_PCT  = 1.5
_HIT_24H_PCT = 3.0


@router.get("/predictive/hit_rate", dependencies=[Depends(require_db)])
async def get_hit_rate(
    agent:  str | None = Query(None, description="Filter by agent name"),
    regime: str | None = Query(None, description="Filter by regime"),
    hours:  int        = Query(168, ge=1, le=720, description="Lookback window (hours)"),
) -> dict:
    """
    PLAN_v3 D4.2: per-agent signal accuracy from resolved PredictiveLog entries.
    Returns hit rates (4h and 24h) broken down by agent and direction.
    """
    cutoff = time.time() - hours * 3600

    async with AsyncSessionLocal() as session:
        q = select(PredictiveLog).where(
            PredictiveLog.scanned_at >= cutoff,
            PredictiveLog.resolved_at.is_not(None),
        )
        if agent:
            q = q.where(PredictiveLog.agent == agent)
        if regime:
            q = q.where(PredictiveLog.regime == regime)

        result = await session.execute(q)
        rows = result.scalars().all()

    # Aggregate by agent + direction
    stats: dict[str, dict] = {}
    for row in rows:
        key = f"{row.agent}:{row.direction}"
        if key not in stats:
            stats[key] = {
                "agent": row.agent, "direction": row.direction,
                "total": 0, "hits_4h": 0, "hits_24h": 0,
                "avg_move_4h": 0.0, "avg_move_24h": 0.0,
                "_sum_4h": 0.0, "_sum_24h": 0.0,
            }
        s = stats[key]
        s["total"] += 1
        if row.hit_4h:
            s["hits_4h"] += 1
        if row.hit_24h:
            s["hits_24h"] += 1
        s["_sum_4h"]  += row.move_4h_pct  or 0.0
        s["_sum_24h"] += row.move_24h_pct or 0.0

    for s in stats.values():
        n = s["total"] or 1
        s["hit_rate_4h"]   = round(s["hits_4h"]  / n * 100, 1)
        s["hit_rate_24h"]  = round(s["hits_24h"] / n * 100, 1)
        s["avg_move_4h"]   = round(s["_sum_4h"]  / n, 2)
        s["avg_move_24h"]  = round(s["_sum_24h"] / n, 2)
        del s["_sum_4h"], s["_sum_24h"]

    return {
        "window_hours": hours,
        "resolved_count": len(rows),
        "by_agent": list(stats.values()),
    }


@router.get("/predictive/signal_review", dependencies=[Depends(require_db)])
async def get_signal_review(
    run: bool = Query(False, description="True = jalankan review sekarang (manual trigger)"),
) -> dict:
    """
    PLAN_FUTURES item C (v4 P2.1/P2.2): hasil weekly signal review terakhir —
    penyesuaian bobot per sinyal + report hit-rate per (agent, regime, direction).
    ?run=true menjalankan review saat itu juga (dipakai review manual 20 Jul).
    """
    from agents.learning.weekly_signal_review import get_last_review, run_weekly_signal_review
    if run:
        return await run_weekly_signal_review(force=True)
    return get_last_review()


@router.get("/predictive/recent", dependencies=[Depends(require_db)])
async def get_recent_predictions(
    limit: int = Query(50, ge=1, le=200),
    agent: str | None = Query(None),
    resolved_only: bool = Query(False),
) -> dict:
    """Recent predictions with their outcomes (if resolved)."""
    async with AsyncSessionLocal() as session:
        q = select(PredictiveLog).order_by(PredictiveLog.scanned_at.desc()).limit(limit)
        if agent:
            q = q.where(PredictiveLog.agent == agent)
        if resolved_only:
            q = q.where(PredictiveLog.resolved_at.is_not(None))

        result = await session.execute(q)
        rows = result.scalars().all()

    return {
        "count": len(rows),
        "predictions": [
            {
                "id":            r.id,
                "symbol":        r.symbol,
                "agent":         r.agent,
                "direction":     r.direction,
                "regime":        r.regime,
                "score":         r.score,
                "signals":       json.loads(r.signals_json or "[]"),
                "price_at_scan": r.price_at_scan,
                "change_24h":    r.change_24h,
                "oi_change":     r.oi_change,
                "funding_rate":  r.funding_rate,
                "scanned_at":    r.scanned_at,
                "hit_4h":        r.hit_4h,
                "hit_24h":       r.hit_24h,
                "move_4h_pct":   r.move_4h_pct,
                "move_24h_pct":  r.move_24h_pct,
                "resolved_at":   r.resolved_at,
            }
            for r in rows
        ],
    }


@router.post("/predictive/resolve", dependencies=[Depends(require_db)])
async def resolve_predictions() -> dict:
    """
    Admin trigger: resolve stale predictions by fetching current Binance price.
    Resolves entries that are 4h or 24h old and not yet resolved.
    In production this runs automatically from the scheduler every 4h.
    """
    now = time.time()
    resolved = 0
    errors   = 0

    async with AsyncSessionLocal() as session:
        # Find unresolved entries older than 4h
        q = select(PredictiveLog).where(
            PredictiveLog.resolved_at.is_(None),
            PredictiveLog.scanned_at <= now - 4 * 3600,
        ).limit(200)
        result = await session.execute(q)
        pending = result.scalars().all()

    if not pending:
        return {"resolved": 0, "message": "No pending predictions to resolve"}

    symbols_needed = list({r.symbol for r in pending})

    # Fetch current prices
    price_map: dict[str, float] = {}
    try:
        from app.services.binance_urls import fapi
        import json as _json
        async with httpx.AsyncClient(timeout=10) as client:
            sym_param = _json.dumps(symbols_needed, separators=(",", ":"))
            r = await client.get(fapi("/fapi/v1/ticker/price"), params={"symbols": sym_param})
            if r.status_code == 200:
                for item in r.json():
                    price_map[item["symbol"]] = float(item["price"])
    except Exception:
        pass

    async with AsyncSessionLocal() as session:
        for row in pending:
            current_price = price_map.get(row.symbol)
            if not current_price or row.price_at_scan <= 0:
                continue
            try:
                age_h = (now - row.scanned_at) / 3600
                move_pct = (current_price - row.price_at_scan) / row.price_at_scan * 100
                # For LONG: positive move is a hit; for SHORT: negative move is a hit
                directed_move = move_pct if row.direction == "LONG" else -move_pct

                # 4h hit: resolve if old enough
                hit_4h = None
                move_4h = None
                if age_h >= 4.0:
                    move_4h = round(directed_move, 3)
                    hit_4h  = directed_move >= _HIT_4H_PCT

                # 24h hit
                hit_24h = None
                move_24h = None
                if age_h >= 24.0:
                    move_24h = round(directed_move, 3)
                    hit_24h  = directed_move >= _HIT_24H_PCT

                # Only mark fully resolved once 24h window has passed.
                # Setting resolved_at at 4h makes the row invisible to future resolve runs,
                # so 24h outcome is never written.
                resolved_ts = now if (hit_24h is not None) else None

                await session.execute(
                    update(PredictiveLog)
                    .where(PredictiveLog.id == row.id)
                    .values(
                        price_4h=current_price if age_h >= 4 else None,
                        price_24h=current_price if age_h >= 24 else None,
                        hit_4h=hit_4h,
                        hit_24h=hit_24h,
                        move_4h_pct=move_4h,
                        move_24h_pct=move_24h,
                        resolved_at=resolved_ts,
                    )
                )
                if resolved_ts:
                    resolved += 1
            except Exception:
                errors += 1

        await session.commit()

    return {"resolved": resolved, "errors": errors, "total_pending": len(pending)}
