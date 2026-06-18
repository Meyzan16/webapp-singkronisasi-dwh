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

_HEALTH_PORT = int(os.getenv("AGENTS_HEALTH_PORT", "8001"))


async def _run_health_server() -> None:
    """
    Tiny HTTP health server so the backend can poll real agent running state
    when AGENTS_STANDALONE=true (agents run in a separate container).
    Endpoint: GET http://agents:8001/health
    """
    from fastapi import FastAPI
    import uvicorn

    health_app = FastAPI(title="agents-health")

    @health_app.get("/health")
    def agent_health() -> dict:
        from agents.opportunity.scheduler  import get_state as opp_s
        from agents.opportunity.monitor    import get_state as opp_m
        from agents.futures.scheduler      import get_state as fut_s
        from agents.futures.monitor        import get_state as fut_m
        from agents.futures.weight_updater import get_state as wt_s
        return {
            "spot_scanner":    opp_s(),
            "spot_monitor":    opp_m(),
            "futures_scanner": fut_s(),
            "futures_monitor": fut_m(),
            "weight_updater":  wt_s(),
        }

    config = uvicorn.Config(
        health_app, host="0.0.0.0", port=_HEALTH_PORT,
        log_level="warning", access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_all_agents() -> None:
    from agents.opportunity.scheduler import run_opportunity_loop
    from agents.opportunity.monitor   import run_opportunity_monitor
    from agents.futures.scheduler     import run_futures_loop
    from agents.futures.monitor       import run_futures_monitor

    logger.info("agents_starting", agents=["opportunity", "futures"],
                health_port=_HEALTH_PORT)
    try:
        await asyncio.gather(
            run_opportunity_loop(),
            run_opportunity_monitor(),
            run_futures_loop(),
            run_futures_monitor(),
            _run_health_server(),
        )
    except asyncio.CancelledError:
        logger.info("agents_stopped")


if __name__ == "__main__":
    asyncio.run(run_all_agents())
