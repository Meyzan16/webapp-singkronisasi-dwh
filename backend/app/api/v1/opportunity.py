"""
Opportunity API — returns coins with high potential for price increase.

Read-only: serves cached results from agents/opportunity/store.
The opportunity agent writes to the store every 15 minutes.
"""

import structlog
from fastapi import APIRouter, Query

router = APIRouter(tags=["opportunity"])
logger = structlog.get_logger(__name__)


@router.get("/opportunity/scan")
async def get_opportunities(
    min_score: float = Query(default=30, description="Minimum opportunity score (0–99)"),
    alert_type: str  = Query(default="ALL", description="ALL | squeeze | accumulation | breakout"),
    limit: int       = Query(default=30, ge=1, le=100, description="Max results"),
) -> dict:
    """
    Return coins with high potential for price increase.
    Served from agents/opportunity/store cache (updated every 15 min).
    Falls back to live scan if cache is empty.
    """
    from agents.opportunity import store as opp_store

    cached = opp_store.get_result()

    if cached is None:
        # Cache empty — trigger a fresh scan (first startup)
        logger.info("opportunity_cache_miss_triggering_scan")
        from agents.opportunity.scanner import run_opportunity_scan
        cached = await run_opportunity_scan()
        opp_store.set_result(cached)

    results = cached.get("results", [])

    # Apply filters
    if min_score > 0:
        results = [r for r in results if r["opportunity_score"] >= min_score]
    if alert_type != "ALL":
        results = [r for r in results if r.get("alert_type") == alert_type]

    return {
        "results":      results[:limit],
        "total":        len(results),
        "scanned":      cached.get("scanned", 0),
        "generated_at": cached.get("generated_at", 0),
        "elapsed_sec":  cached.get("elapsed_sec", 0),
    }


@router.get("/opportunity/status")
async def get_opportunity_status() -> dict:
    """Status of the opportunity scanner agent."""
    from agents.opportunity.scheduler import get_state
    from agents.opportunity import store as opp_store
    import time

    state = get_state()
    last_ts = opp_store.last_scan_ts()
    next_in = None
    if last_ts:
        elapsed = time.time() - last_ts
        next_in = max(0, round((900 - elapsed) / 60, 1))

    return {**state, "next_scan_in_min": next_in}
