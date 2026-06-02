import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.v1.klines import router as klines_router
from app.api.v1.trend import router as trend_router
from app.api.v1.wyckoff import router as wyckoff_router
from app.api.v1.support_resistance import router as sr_router
from app.api.v1.pattern import router as pattern_router
from app.api.v1.trigger import router as trigger_router
from app.api.v1.signals import router as signals_router
from app.config import get_settings
from app.database import AsyncSessionLocal, create_db_schema, dispose_engine
from app.services.data_pipeline.binance_client import BinanceClient
from app.services.data_pipeline.kline_fetcher import KlineFetcher

logger = structlog.get_logger(__name__)
settings = get_settings()


async def run_data_pipeline(fetcher: KlineFetcher) -> None:
    """Run historical backfill once, then continue polling new candles."""

    await fetcher.backfill_all()
    await fetcher.poll_forever()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create schema and start the background kline poller."""

    client = BinanceClient(settings)
    poller_task: asyncio.Task[None] | None = None
    try:
        await create_db_schema()
        if settings.auto_start_pipeline:
            fetcher = KlineFetcher(settings=settings, client=client, session_factory=AsyncSessionLocal)
            poller_task = asyncio.create_task(run_data_pipeline(fetcher))
        yield
    finally:
        if poller_task is not None:
            poller_task.cancel()
            try:
                await poller_task
            except asyncio.CancelledError:
                logger.info("poller_stopped")
        await client.close()
        await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(klines_router, prefix=settings.api_v1_prefix)
app.include_router(trend_router, prefix=settings.api_v1_prefix)
app.include_router(wyckoff_router, prefix=settings.api_v1_prefix)
app.include_router(sr_router, prefix=settings.api_v1_prefix)
app.include_router(pattern_router, prefix=settings.api_v1_prefix)
app.include_router(trigger_router, prefix=settings.api_v1_prefix)
app.include_router(signals_router, prefix=settings.api_v1_prefix)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return service health."""

    return {"status": "ok"}
