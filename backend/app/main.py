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
from app.api.v1.scanner import router as scanner_router
from app.api.v1.history import router as history_router
from app.api.v1.opportunity import router as opportunity_router
from app.models.paper_trade import PaperTrade as _PaperTrade  # noqa: F401 — register table
from app.config import get_settings
from app.database import AsyncSessionLocal, create_db_schema, dispose_engine, set_db_available
from app.services.data_pipeline.binance_client import BinanceClient
from app.services.data_pipeline.kline_fetcher import KlineFetcher
from agents.scanner.scheduler import run_scanner_loop, get_state as scheduler_state
from agents.opportunity.scheduler import run_opportunity_loop
from app.ws.position_stream import position_stream

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

    # ── Background scanner scheduler (24/7, all 4 styles, every 15 min) ───────
    scheduler_task    = asyncio.create_task(run_scanner_loop())
    opportunity_task  = asyncio.create_task(run_opportunity_loop())

    yield  # ← app is running

    # ── Shutdown ───────────────────────────────────────────────────────────────
    for task in [scheduler_task, opportunity_task]:
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
app.include_router(scanner_router,     prefix=settings.api_v1_prefix)
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


@app.websocket("/ws/positions")
async def ws_positions(websocket: WebSocket) -> None:
    await position_stream(websocket)


@app.get("/health")
async def health() -> dict:
    """Health check — shows DB + scheduler status."""
    import time
    from app.database import is_db_available
    sched = scheduler_state()
    next_in = None
    if sched["next_scan"]:
        next_in = max(0, round((sched["next_scan"] - time.time()) / 60, 1))
    return {
        "status":           "ok",
        "database":         "connected" if is_db_available() else "unavailable",
        "scheduler": {
            "running":           sched["running"],
            "cycle_count":       sched["cycle_count"],
            "interval_minutes":  sched["interval_minutes"],
            "next_scan_in_min":  next_in,
            "total_logged":      sched["total_logged"],
            "last_error":        sched["last_error"],
        },
    }


@app.get("/api/v1/scheduler/status")
async def scheduler_status() -> dict:
    """Detailed background scanner scheduler status."""
    import time, datetime
    sched = scheduler_state()
    def fmt(ts):
        return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else None
    next_in = None
    if sched["next_scan"]:
        next_in = max(0, round((sched["next_scan"] - time.time()) / 60, 1))
    return {
        **sched,
        "last_scan_fmt":  fmt(sched["last_scan"]),
        "next_scan_fmt":  fmt(sched["next_scan"]),
        "next_in_minutes": next_in,
    }
