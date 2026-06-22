"""
BC3 — ExchangeInfo Symbol Constraints Cache.

Caches Binance Futures symbol-level constraints from /fapi/v1/exchangeInfo:
  - tickSize:    minimum price granularity (PRICE_FILTER)
  - minNotional: minimum order value in USDT (MIN_NOTIONAL filter)
  - maxLeverage: safe cap; real brackets come from a separate endpoint,
                 so we default to 125 and rely on Binance to reject higher values.

Cache TTL: 1 hour. Stale data is served on refresh failure.
"""

import time
from decimal import ROUND_DOWN, Decimal

import httpx
import structlog

from app.services.binance_urls import fapi

logger = structlog.get_logger(__name__)

_CACHE: dict[str, dict] = {}
_cache_ts: float = 0.0
CACHE_TTL_SEC = 3600.0

# Defaults — used when a symbol is absent from cache or on fetch failure
_DEFAULTS: dict = {
    "tick_size":    Decimal("0.0001"),
    "min_notional": Decimal("5"),
    "max_leverage": 125,
}


async def _refresh() -> None:
    global _cache_ts
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(fapi("/fapi/v1/exchangeInfo"))
            if r.status_code != 200:
                return
            data = r.json()

        new: dict[str, dict] = {}
        for sym in data.get("symbols", []):
            s = sym.get("symbol", "")
            if not s.endswith("USDT"):
                continue
            tick_size    = _DEFAULTS["tick_size"]
            min_notional = _DEFAULTS["min_notional"]
            for f in sym.get("filters", []):
                ft = f.get("filterType", "")
                if ft == "PRICE_FILTER":
                    raw = f.get("tickSize", "")
                    if raw:
                        tick_size = Decimal(str(raw))
                elif ft == "MIN_NOTIONAL":
                    raw = f.get("notional", "")
                    if raw:
                        min_notional = Decimal(str(raw))
            new[s] = {
                "tick_size":    tick_size,
                "min_notional": min_notional,
                "max_leverage": 125,
            }

        _CACHE.update(new)
        _cache_ts = time.time()
        logger.debug("exchange_info_refreshed", symbols=len(new))
    except Exception as exc:
        logger.warning("exchange_info_refresh_error", error=str(exc)[:120])


async def get_symbol_constraints(symbol: str) -> dict:
    """Return {tick_size: Decimal, min_notional: Decimal, max_leverage: int}."""
    if time.time() - _cache_ts > CACHE_TTL_SEC or symbol not in _CACHE:
        await _refresh()
    return _CACHE.get(symbol, dict(_DEFAULTS))


def round_to_tick(price: float, tick_size: Decimal) -> float:
    """Round price down to the nearest tick_size boundary."""
    if not price or tick_size <= 0:
        return price
    d = Decimal(str(price))
    return float((d / tick_size).to_integral_value(rounding=ROUND_DOWN) * tick_size)
