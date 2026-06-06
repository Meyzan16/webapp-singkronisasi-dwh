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

from app.api.v1.klines import router as klines_router
from app.api.v1.trend import router as trend_router
from app.api.v1.wyckoff import router as wyckoff_router
from app.api.v1.support_resistance import router as sr_router
from app.api.v1.pattern import router as pattern_router
from app.api.v1.trigger import router as trigger_router
from app.api.v1.signals import router as signals_router
from app.api.v1.backtest import router as backtest_router
from app.api.v1.positions import router as positions_router
from app.api.v1.account import router as account_router
from app.api.v1.market import router as market_router
from app.api.v1.coin_detail import router as coin_detail_router
from app.api.v1.history import router as history_router
from app.api.v1.opportunity import router as opportunity_router
from app.api.v1.futures_scanner import router as futures_router
from app.api.v1.futures_learning import router as futures_learning_router
from app.api.v1.market_context import router as market_context_router
from app.api.v1.binance_status import router as binance_status_router
from app.models.paper_trade import PaperTrade as _PaperTrade          # noqa: F401
from app.models.signal_weight import AgentSignalWeight as _ASW         # noqa: F401
from app.config import get_settings
from app.database import AsyncSessionLocal, create_db_schema, dispose_engine, set_db_available
from app.services.data_pipeline.binance_client import BinanceClient
from app.services.data_pipeline.kline_fetcher import KlineFetcher
from agents.opportunity.scheduler import run_opportunity_loop
from agents.opportunity.monitor import run_opportunity_monitor
from agents.futures.scheduler import run_futures_loop
from agents.futures.monitor import run_futures_monitor
from app.ws.position_stream import position_stream
from app.ws.opportunity_stream import opportunity_stream
from app.ws.futures_stream import futures_stream

logger = structlog.get_logger(__name__)
settings = get_settings()


async def run_data_pipeline(fetcher: KlineFetcher) -> None:
    """Run historical backfill once, then continue polling new candles."""
    await fetcher.backfill_all()
    await fetcher.poll_forever()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup:
      - Try to connect to PostgreSQL and create tables.
        If DB is down → log warning, set DB_AVAILABLE=False, continue anyway.
        All non-DB endpoints (scanner, market, TA engine) still work.
      - Start kline poller only if DB is available.

    Shutdown:
      - Cancel background tasks, dispose engine.
    """
    client = BinanceClient(settings)
    poller_task: asyncio.Task[None] | None = None

    # ── Database (optional) ────────────────────────────────────────────────────
    try:
        await create_db_schema()
        set_db_available(True)
        logger.info("database_ready", msg="PostgreSQL connected — DB features enabled")
    except Exception as exc:
        set_db_available(False)
        logger.warning(
            "database_unavailable",
            error=str(exc)[:120],
            msg="PostgreSQL is down — DB endpoints return 503. Non-DB features (scanner, market, TA) still work.",
        )

    # ── Kline poller (only if DB available) ───────────────────────────────────
    try:
        if settings.auto_start_pipeline and _is_db_available():
            fetcher = KlineFetcher(
                settings=settings, client=client, session_factory=AsyncSessionLocal
            )
            poller_task = asyncio.create_task(run_data_pipeline(fetcher))
    except Exception as exc:
        logger.warning("poller_skipped", error=str(exc)[:80])

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

    if poller_task is not None:
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            logger.info("poller_stopped")
    await client.close()
    await dispose_engine()


def _is_db_available() -> bool:
    from app.database import is_db_available
    return is_db_available()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# ── Routers ────────────────────────────────────────────────────────────────────
# Non-DB (always work): scanner, market, TA engine, coin detail, account
app.include_router(market_router,      prefix=settings.api_v1_prefix)
app.include_router(coin_detail_router, prefix=settings.api_v1_prefix)
app.include_router(account_router,     prefix=settings.api_v1_prefix)
app.include_router(trend_router,       prefix=settings.api_v1_prefix)
app.include_router(wyckoff_router,     prefix=settings.api_v1_prefix)
app.include_router(sr_router,          prefix=settings.api_v1_prefix)
app.include_router(pattern_router,     prefix=settings.api_v1_prefix)
app.include_router(trigger_router,     prefix=settings.api_v1_prefix)
app.include_router(signals_router,     prefix=settings.api_v1_prefix)
app.include_router(backtest_router,    prefix=settings.api_v1_prefix)

# DB-dependent (return 503 when PostgreSQL is down)
app.include_router(klines_router,      prefix=settings.api_v1_prefix)
app.include_router(positions_router,   prefix=settings.api_v1_prefix)
app.include_router(history_router,      prefix=settings.api_v1_prefix)
app.include_router(opportunity_router,  prefix=settings.api_v1_prefix)
app.include_router(futures_router,          prefix=settings.api_v1_prefix)
app.include_router(futures_learning_router, prefix=settings.api_v1_prefix)
app.include_router(market_context_router,  prefix=settings.api_v1_prefix)
app.include_router(binance_status_router,  prefix=settings.api_v1_prefix)


@app.websocket("/ws/positions")
async def ws_positions(websocket: WebSocket) -> None:
    await position_stream(websocket)


@app.websocket("/ws/opportunity")
async def ws_opportunity(websocket: WebSocket) -> None:
    await opportunity_stream(websocket)


@app.websocket("/ws/futures")
async def ws_futures(websocket: WebSocket) -> None:
    await futures_stream(websocket)


@app.get("/health")
async def health() -> dict:
    """Health check — DB + all 4 agent statuses."""
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
