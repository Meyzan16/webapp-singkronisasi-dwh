import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

# Make agents/ importable whether backend is run from:
#   cd backend && uvicorn app.main:app        ← adds repo root to sys.path
#   cd agents-trading && python backend/...   ← repo root already in path
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import structlog
from fastapi import FastAPI, WebSocket

from app.api.v1.market import router as market_router
from app.api.v1.history import router as history_router
from app.api.v1.opportunity import router as opportunity_router
from app.api.v1.futures_scanner import router as futures_router
from app.api.v1.futures_learning import router as futures_learning_router
from app.api.v1.market_context import router as market_context_router
from app.api.v1.binance_status import router as binance_status_router
from app.models.paper_trade import PaperTrade as _PaperTrade          # noqa: F401
from app.models.signal_weight import AgentSignalWeight as _ASW         # noqa: F401
from app.config import get_settings
from app.database import create_db_schema, dispose_engine, set_db_available
from agents.opportunity.scheduler import run_opportunity_loop
from agents.opportunity.monitor import run_opportunity_monitor
from agents.futures.scheduler import run_futures_loop
from agents.futures.monitor import run_futures_monitor
from app.ws.opportunity_stream import opportunity_stream
from app.ws.futures_stream import futures_stream

logger = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup:
      - Connect to PostgreSQL, create tables.
      - Start 4 background agents: Spot Scanner, Spot Monitor, Futures Scanner, Futures Monitor.
    Shutdown:
      - Cancel all background tasks.
    """
    # ── Database ───────────────────────────────────────────────────────────────
    try:
        await create_db_schema()
        set_db_available(True)
        logger.info("database_ready", msg="PostgreSQL connected")
    except Exception as exc:
        set_db_available(False)
        logger.warning("database_unavailable", error=str(exc)[:120])

    # ── Background agents ─────────────────────────────────────────────────────
    opportunity_task     = asyncio.create_task(run_opportunity_loop())
    monitor_task         = asyncio.create_task(run_opportunity_monitor())
    futures_task         = asyncio.create_task(run_futures_loop())
    futures_monitor_task = asyncio.create_task(run_futures_monitor())

    yield  # ← app is running

    # ── Shutdown ───────────────────────────────────────────────────────────────
    for task in [opportunity_task, monitor_task, futures_task, futures_monitor_task]:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# ── Active Routers ─────────────────────────────────────────────────────────────
app.include_router(market_router,           prefix=settings.api_v1_prefix)
app.include_router(history_router,          prefix=settings.api_v1_prefix)
app.include_router(opportunity_router,      prefix=settings.api_v1_prefix)
app.include_router(futures_router,          prefix=settings.api_v1_prefix)
app.include_router(futures_learning_router, prefix=settings.api_v1_prefix)
app.include_router(market_context_router,   prefix=settings.api_v1_prefix)
app.include_router(binance_status_router,   prefix=settings.api_v1_prefix)


@app.websocket("/ws/opportunity")
async def ws_opportunity(websocket: WebSocket) -> None:
    await opportunity_stream(websocket)


@app.websocket("/ws/futures")
async def ws_futures(websocket: WebSocket) -> None:
    await futures_stream(websocket)


@app.get("/health")
async def health() -> dict:
    """Health check — DB + all agent statuses."""
    from app.database import is_db_available
    from agents.opportunity.scheduler  import get_state as opp_sched_state
    from agents.opportunity.monitor    import get_state as opp_mon_state
    from agents.futures.scheduler      import get_state as fut_sched_state
    from agents.futures.monitor        import get_state as fut_mon_state
    from agents.futures.weight_updater import get_state as weight_state
    db_ok = is_db_available()
    return {
        "status":          "ok",
        "db":              "ok" if db_ok else "unavailable",
        "database":        "connected" if db_ok else "unavailable",
        "spot_scanner":    opp_sched_state(),
        "spot_monitor":    opp_mon_state(),
        "futures_scanner": fut_sched_state(),
        "futures_monitor": fut_mon_state(),
        "weight_updater":  weight_state(),
        "scheduler":       opp_sched_state(),  # legacy key
    }
