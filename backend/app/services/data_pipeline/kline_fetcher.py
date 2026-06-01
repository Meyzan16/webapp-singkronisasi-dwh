import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import ccxt
import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.schemas.kline import KlineCreate
from app.services.data_pipeline.binance_client import BinanceClient
from app.services.data_pipeline.kline_repository import KlineRepository

logger = structlog.get_logger(__name__)

TIMEFRAME_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}


class KlineFetcher:
    """Fetch historical and incremental klines into storage."""

    def __init__(
        self,
        settings: Settings,
        client: BinanceClient,
        session_factory: async_sessionmaker,
    ) -> None:
        self._settings = settings
        self._client = client
        self._session_factory = session_factory

    @staticmethod
    def _six_months_ago_ms() -> int:
        """Return an approximate timestamp for six months ago in milliseconds."""

        return int((datetime.now(UTC) - timedelta(days=183)).timestamp() * 1000)

    @staticmethod
    def _to_schema(pair: str, timeframe: str, raw: Sequence[Any]) -> KlineCreate:
        """Convert a CCXT OHLCV row into a KlineCreate schema."""

        return KlineCreate(
            pair=pair.upper(),
            timeframe=timeframe,
            open_time=int(raw[0]),
            open=Decimal(str(raw[1])),
            high=Decimal(str(raw[2])),
            low=Decimal(str(raw[3])),
            close=Decimal(str(raw[4])),
            volume=Decimal(str(raw[5])),
            close_time=int(raw[6]) if len(raw) > 6 and raw[6] is not None else None,
            taker_buy_volume=Decimal(str(raw[9])) if len(raw) > 9 and raw[9] is not None else None,
            number_of_trades=int(raw[8]) if len(raw) > 8 and raw[8] is not None else None,
        )

    async def fetch_and_store(self, pair: str, timeframe: str, since: int | None = None) -> int:
        """Fetch klines for one pair and timeframe and upsert them."""

        cursor = since
        total = 0
        timeframe_ms = TIMEFRAME_MS[timeframe]
        now_ms = int(datetime.now(UTC).timestamp() * 1000)

        while cursor is None or cursor <= now_ms:
            raw_klines = await self._client.fetch_klines(pair, timeframe, since=cursor)
            if not raw_klines:
                break

            klines = [self._to_schema(pair, timeframe, raw) for raw in raw_klines]
            async with self._session_factory() as session:
                repository = KlineRepository(session)
                total += await repository.upsert_many(klines)

            last_open_time = klines[-1].open_time
            next_cursor = last_open_time + timeframe_ms
            if cursor is None or next_cursor <= cursor or next_cursor > now_ms:
                break
            cursor = next_cursor

        return total

    async def backfill_all(self) -> None:
        """Backfill historical candles for all configured pairs and timeframes."""

        since = self._six_months_ago_ms()
        for pair in self._settings.trading_pairs:
            for timeframe in self._settings.timeframes:
                try:
                    count = await self.fetch_and_store(pair, timeframe, since=since)
                    logger.info("backfilled_klines", pair=pair, timeframe=timeframe, count=count)
                except (TimeoutError, ConnectionError, ValueError, ccxt.BaseError, SQLAlchemyError) as exc:
                    logger.warning("backfill_failed", pair=pair, timeframe=timeframe, error=str(exc))

    async def poll_forever(self) -> None:
        """Poll Binance for new candles until the task is cancelled."""

        while True:
            for pair in self._settings.trading_pairs:
                for timeframe in self._settings.timeframes:
                    try:
                        async with self._session_factory() as session:
                            repository = KlineRepository(session)
                            latest = await repository.get_latest_open_time(pair, timeframe)
                        since = latest if latest is not None else self._six_months_ago_ms()
                        count = await self.fetch_and_store(pair, timeframe, since=since)
                        logger.info("polled_klines", pair=pair, timeframe=timeframe, count=count)
                    except asyncio.CancelledError:
                        raise
                    except (TimeoutError, ConnectionError, ValueError, ccxt.BaseError, SQLAlchemyError) as exc:
                        logger.warning("poll_failed", pair=pair, timeframe=timeframe, error=str(exc))
            await asyncio.sleep(self._settings.polling_interval_seconds)
