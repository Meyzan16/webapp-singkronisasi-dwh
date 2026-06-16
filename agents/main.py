"""
Agents standalone entry point (optional — agents also start via FastAPI lifespan).

Usage:
    cd backend && python -m agents
"""

import asyncio
import os
import sys

import structlog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.logging_config import configure_logging
configure_logging("agents")   # JSON-to-stdout, no file writes — see backend/app/logging_config.py

logger = structlog.get_logger(__name__)


async def run_all_agents() -> None:
    from agents.opportunity.scheduler import run_opportunity_loop
    from agents.opportunity.monitor   import run_opportunity_monitor
    from agents.futures.scheduler     import run_futures_loop
    from agents.futures.monitor       import run_futures_monitor

    logger.info("agents_starting", agents=["opportunity", "futures"])
    try:
        await asyncio.gather(
            run_opportunity_loop(),
            run_opportunity_monitor(),
            run_futures_loop(),
            run_futures_monitor(),
        )
    except asyncio.CancelledError:
        logger.info("agents_stopped")


if __name__ == "__main__":
    asyncio.run(run_all_agents())
