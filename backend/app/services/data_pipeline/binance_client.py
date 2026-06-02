from collections.abc import Sequence
from typing import Any

import ccxt.async_support as ccxt
import structlog

from app.config import Settings

logger = structlog.get_logger(__name__)


class BinanceClient:
    """Async CCXT wrapper for Binance public market data."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        exchange_class = getattr(ccxt, settings.binance_exchange_id)
        self._exchange = exchange_class({
            "enableRateLimit": True,
            "urls": {
                "api": {
                    "public": "https://data-api.binance.vision/api/v3",
                    "private": "https://data-api.binance.vision/api/v3",
                    "v1": "https://data-api.binance.vision/api/v1",
                    "v3": "https://data-api.binance.vision/api/v3",
                },
            },
        })

    @staticmethod
    def to_binance_symbol(pair: str) -> str:
        """Convert BTCUSDT into BTC/USDT for CCXT."""

        if "/" in pair:
            return pair
        if pair.endswith("USDT"):
            return f"{pair[:-4]}/USDT"
        return pair

    async def fetch_klines(
        self,
        pair: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 1000,
    ) -> Sequence[list[Any]]:
        """Fetch raw Binance klines with trade and taker volume fields."""

        params: dict[str, Any] = {
            "symbol": pair.replace("/", "").upper(),
            "interval": timeframe,
            "limit": limit,
        }
        if since is not None:
            params["startTime"] = since

        logger.info("fetching_klines", pair=pair, timeframe=timeframe, since=since, limit=limit)
        public_get_klines = getattr(self._exchange, "public_get_klines", None)
        if public_get_klines is not None:
            return await public_get_klines(params)

        public_get_klines = getattr(self._exchange, "publicGetKlines")
        return await public_get_klines(params)

    async def close(self) -> None:
        """Close the underlying CCXT exchange connection."""

        await self._exchange.close()
