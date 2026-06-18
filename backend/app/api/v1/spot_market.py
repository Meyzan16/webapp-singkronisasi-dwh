"""
Spot Market Overview API.

GET /market/spot-overview          — cached 60 s
GET /market/spot-overview?refresh=true — force refresh

Returns:
  - top_gainers    : top 20 by 24h price change %
  - top_losers     : bottom 20 by 24h price change %
  - top_volume     : top 20 by 24h quote volume (USDT)
  - big_movers     : coins with |change| > 8% in 24h
  - market_stats   : total pairs, up/down count, avg change, total volume
  - generated_at   : unix timestamp ms
"""

import time
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Query

from app.services.binance_urls import spot

router  = APIRouter(tags=["spot-market"])
logger  = structlog.get_logger(__name__)

_cache:    Optional[dict] = None
_cache_ts: float          = 0.0
CACHE_TTL = 60  # seconds

_SKIP_BASE = {
    "USDC", "FDUSD", "TUSD", "USDP", "DAI", "FRAX", "USDD", "RLUSD", "USD1",
    "BUSD", "GUSD", "HUSD", "USDN", "USTC", "UST", "EUR", "AEUR", "EURT",
    "EURS", "PAXG", "XAUT",
}

TOP_N = 20
BIG_MOVER_THRESHOLD = 8.0


def _base(sym: str) -> str:
    s = sym.upper()
    return s[:-4] if s.endswith("USDT") else s


async def _fetch_overview() -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(spot("/api/v3/ticker/24hr"))
        r.raise_for_status()
        tickers = r.json()

    now_ms = int(time.time() * 1000)

    enriched: list[dict] = []
    up_count   = 0
    down_count = 0
    total_vol  = 0.0
    changes: list[float] = []

    for t in (tickers if isinstance(tickers, list) else []):
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = _base(sym)
        if base in _SKIP_BASE:
            continue

        change_pct  = float(t.get("priceChangePercent", 0))
        price_chg   = float(t.get("priceChange", 0))
        last_price  = float(t.get("lastPrice", 0))
        high24h     = float(t.get("highPrice", 0))
        low24h      = float(t.get("lowPrice", 0))
        vol24h      = float(t.get("volume", 0))
        quote_vol   = float(t.get("quoteVolume", 0))
        count       = int(t.get("count", 0))

        if last_price <= 0:
            continue

        if change_pct > 0:
            up_count += 1
        elif change_pct < 0:
            down_count += 1
        total_vol += quote_vol
        changes.append(change_pct)

        enriched.append({
            "symbol":       sym,
            "base":         base,
            "last_price":   last_price,
            "price_change": round(price_chg, 8),
            "change_pct":   round(change_pct, 2),
            "high_24h":     high24h,
            "low_24h":      low24h,
            "volume_24h":   round(vol24h, 2),
            "quote_vol_24h": round(quote_vol, 0),
            "trades_24h":   count,
        })

    avg_change = round(sum(changes) / len(changes), 2) if changes else 0.0
    neutral    = len(enriched) - up_count - down_count
    big_mover_count = sum(1 for c in enriched if abs(c["change_pct"]) >= BIG_MOVER_THRESHOLD)

    top_gainers = sorted(enriched, key=lambda c: c["change_pct"],   reverse=True)[:TOP_N]
    top_losers  = sorted(enriched, key=lambda c: c["change_pct"])[:TOP_N]
    top_volume  = sorted(enriched, key=lambda c: c["quote_vol_24h"], reverse=True)[:TOP_N]
    big_movers  = sorted(
        [c for c in enriched if abs(c["change_pct"]) >= BIG_MOVER_THRESHOLD],
        key=lambda c: abs(c["change_pct"]), reverse=True,
    )

    return {
        "top_gainers":  top_gainers,
        "top_losers":   top_losers,
        "top_volume":   top_volume,
        "big_movers":   big_movers,
        "market_stats": {
            "total_pairs":      len(enriched),
            "up_count":         up_count,
            "down_count":       down_count,
            "neutral_count":    neutral,
            "avg_change_pct":   avg_change,
            "total_vol_usdt":   round(total_vol, 0),
            "big_mover_count":  big_mover_count,
        },
        "generated_at": now_ms,
    }


@router.get("/market/spot-overview")
async def get_spot_overview(refresh: bool = Query(False)) -> dict:
    """Get Binance SPOT market overview — gainers, losers, volume, big movers."""
    global _cache, _cache_ts
    now = time.time()
    if not refresh and _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache
    try:
        data = await _fetch_overview()
        _cache    = data
        _cache_ts = now
        return data
    except Exception as exc:
        logger.warning("spot_overview_error", error=str(exc)[:120])
        if _cache:
            return _cache
        return {"error": str(exc), "top_gainers": [], "top_losers": [], "top_volume": [], "big_movers": [], "market_stats": {}}
