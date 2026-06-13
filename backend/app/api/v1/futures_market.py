"""
Futures Market Overview API.

GET /market/futures-overview

Returns:
  - new_listings       : contracts listed in last N days (from exchangeInfo.onboardDate)
  - top_gainers        : top 15 by 24h price change %
  - top_losers         : bottom 15 by 24h price change %
  - top_volume         : top 15 by 24h quote volume
  - big_movers         : coins with |change| > 10% in 24h (alert level)
  - top_funding_long   : top 15 highest positive funding rate (crowded longs)
  - top_funding_short  : top 15 most negative funding rate (crowded shorts)
  - top_oi             : top 30 open interest in USDT (across all coins, F96)
  - market_stats       : total pairs, up/down count, avg change, total volume
  - sentiment          : avg funding rate, mood, pos/neg funding counts
"""

import asyncio
import json as _json
import time
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Query

from app.services.binance_urls import fapi

router  = APIRouter(tags=["futures-market"])
logger  = structlog.get_logger(__name__)

_cache:    Optional[dict] = None
_cache_ts: float          = 0.0
CACHE_TTL = 60  # seconds

_SKIP_BASE = {
    "USDC","FDUSD","TUSD","USDP","DAI","FRAX","USDD","RLUSD","USD1","UUSD",
    "BFUSD","USDE","BUSD","GUSD","HUSD","USDN","USTC","UST","EUR","AEUR","EURT",
    "EURS","SPY","PAXG","XAUT","COPPER","SILVER","GOLD","OIL","WTI","CORN",
    "WHEAT","NATGAS",
}


def _base(sym: str) -> str:
    s = sym.upper()
    return s[:-4] if s.endswith("USDT") else s


async def _get_oi(client: httpx.AsyncClient, sym: str) -> tuple[str, float]:
    """Fetch open interest for one symbol. Returns (symbol, openInterest base units)."""
    try:
        r = await client.get(fapi("/fapi/v1/openInterest"), params={"symbol": sym})
        r.raise_for_status()
        d = r.json()
        return sym, float(d.get("openInterest", 0))
    except Exception:
        return sym, 0.0


async def _fetch_overview() -> dict:
    now_ms   = int(time.time() * 1000)
    new_days = 30
    cutoff_ms = now_ms - new_days * 86400 * 1000

    async with httpx.AsyncClient(timeout=20) as client:
        # ── Step 1: exchangeInfo + premiumIndex in parallel ─────────────────────
        info_r, premium_r = await asyncio.gather(
            client.get(fapi("/fapi/v1/exchangeInfo")),
            client.get(fapi("/fapi/v1/premiumIndex")),
        )
        info_r.raise_for_status()
        premium_r.raise_for_status()

        info         = info_r.json()
        premium_list = premium_r.json()  # all symbols at once

        # ── Build symbol metadata ───────────────────────────────────────────────
        symbol_meta: dict[str, dict] = {}
        for s in info.get("symbols", []):
            sym = s.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if s.get("contractType") != "PERPETUAL":
                continue
            if s.get("status") != "TRADING":
                continue
            if _base(sym) in _SKIP_BASE:
                continue
            symbol_meta[sym] = {
                "symbol":       sym,
                "base":         _base(sym),
                "onboard_date": s.get("onboardDate", 0),
            }

        # ── Build funding rate map from premiumIndex ────────────────────────────
        funding_map: dict[str, dict] = {}
        if isinstance(premium_list, list):
            for p in premium_list:
                sym = p.get("symbol", "")
                if sym in symbol_meta:
                    funding_map[sym] = {
                        "funding_rate":      float(p.get("lastFundingRate", 0)),
                        "next_funding_time": int(p.get("nextFundingTime", 0)),
                        "mark_price":        float(p.get("markPrice", 0)),
                        "index_price":       float(p.get("indexPrice", 0)),
                    }

        # ── Step 2: 24H tickers ─────────────────────────────────────────────────
        syms_param = _json.dumps(list(symbol_meta.keys())[:200])
        ticker_r   = await client.get(
            fapi("/fapi/v1/ticker/24hr"),
            params={"symbols": syms_param},
        )
        ticker_r.raise_for_status()
        tickers = ticker_r.json() if ticker_r.status_code == 200 else []

        # ── Step 3: Merge ticker + funding ──────────────────────────────────────
        enriched: list[dict] = []
        up_count     = 0
        down_count   = 0
        total_vol    = 0.0
        changes      = []
        total_fr     = 0.0
        funding_pos  = 0
        funding_neg  = 0

        for t in (tickers if isinstance(tickers, list) else []):
            sym = t.get("symbol", "")
            if sym not in symbol_meta:
                continue

            meta = symbol_meta[sym]
            fr   = funding_map.get(sym, {})

            price_chg_pct = float(t.get("priceChangePercent", 0))
            price_chg     = float(t.get("priceChange", 0))
            last_price    = float(t.get("lastPrice", 0))
            high24h       = float(t.get("highPrice", 0))
            low24h        = float(t.get("lowPrice", 0))
            vol24h        = float(t.get("volume", 0))
            quote_vol24h  = float(t.get("quoteVolume", 0))
            count         = int(t.get("count", 0))

            funding_rate  = fr.get("funding_rate", 0.0)
            funding_pct   = round(funding_rate * 100, 4)   # e.g. 0.0100 → 0.01%
            mark_price    = fr.get("mark_price", last_price)
            next_funding  = fr.get("next_funding_time", 0)

            onboard_ms = meta["onboard_date"]
            is_new     = bool(onboard_ms and onboard_ms >= cutoff_ms)
            days_listed = max(0, round((now_ms - onboard_ms) / (86400 * 1000))) if onboard_ms else None

            if price_chg_pct > 0:
                up_count += 1
            elif price_chg_pct < 0:
                down_count += 1

            if funding_rate > 0:
                funding_pos += 1
            elif funding_rate < 0:
                funding_neg += 1

            total_vol += quote_vol24h
            total_fr  += funding_rate
            changes.append(price_chg_pct)

            enriched.append({
                "symbol":            sym,
                "base":              meta["base"],
                "last_price":        last_price,
                "mark_price":        mark_price,
                "price_change":      round(price_chg, 8),
                "change_pct":        round(price_chg_pct, 2),
                "high_24h":          high24h,
                "low_24h":           low24h,
                "volume_24h":        round(vol24h, 2),
                "quote_vol_24h":     round(quote_vol24h, 0),
                "trades_24h":        count,
                "is_new":            is_new,
                "onboard_date":      onboard_ms,
                "days_listed":       days_listed,
                # On-chain / futures-specific
                "funding_rate":      funding_pct,      # % annot: positive = longs pay
                "next_funding_time": next_funding,
                "open_interest":     None,             # filled below for top-50
                "open_interest_usdt": None,
            })

        avg_change  = round(sum(changes) / len(changes), 2) if changes else 0.0
        avg_funding = round((total_fr / len(enriched)) * 100, 4) if enriched else 0.0

        # ── Step 4: OI fetch for ALL symbols, throttled (F96 full coverage, F97 throttle) ──
        enriched_sorted_vol = sorted(enriched, key=lambda x: x["quote_vol_24h"], reverse=True)
        _oi_sem = asyncio.Semaphore(10)   # F97: cap concurrency to stay under rate limit

        async def _throttled_oi(sym: str) -> tuple[str, float]:
            async with _oi_sem:
                return await _get_oi(client, sym)

        all_syms   = [x["symbol"] for x in enriched]          # F96: every coin, not just top-50
        oi_results = await asyncio.gather(*[_throttled_oi(s) for s in all_syms])
        oi_map     = {sym: oi for sym, oi in oi_results}

        # Back-fill OI into enriched rows
        price_lookup = {x["symbol"]: x["last_price"] for x in enriched}
        for row in enriched:
            sym = row["symbol"]
            if sym in oi_map:
                oi_base = oi_map[sym]
                price   = price_lookup.get(sym, 0)
                oi_usdt = round(oi_base * price, 0)
                row["open_interest"]      = round(oi_base, 2)
                row["open_interest_usdt"] = oi_usdt

        # ── F98: attach Agent 1 pre-gainer score so overview links to the scanner ──
        try:
            from agents.futures import store as _futures_store
            a1_cache = _futures_store.get_result("agent1") or {}
            score_map: dict[str, float] = {}
            for r in a1_cache.get("results", []):
                _sym = r.get("symbol")
                _sc  = r.get("score", 0) or 0
                if _sym and _sc > score_map.get(_sym, 0):
                    score_map[_sym] = _sc
        except Exception:
            score_map = {}
        for row in enriched:
            row["agent1_score"] = score_map.get(row["symbol"])   # None if not in last scan

    # ── Sort + categorize ──────────────────────────────────────────────────────
    enriched_sorted_chg = sorted(enriched, key=lambda x: x["change_pct"], reverse=True)
    enriched_sorted_fr  = sorted(enriched, key=lambda x: x["funding_rate"], reverse=True)
    enriched_sorted_oi  = sorted(
        [x for x in enriched if x["open_interest_usdt"] is not None],
        key=lambda x: x["open_interest_usdt"] or 0,
        reverse=True,
    )

    top_gainers = [x for x in enriched_sorted_chg if x["change_pct"] > 0][:15]
    top_losers  = list(reversed([x for x in enriched_sorted_chg if x["change_pct"] < 0]))[:15]
    top_volume  = enriched_sorted_vol[:15]
    big_movers  = [x for x in enriched if abs(x["change_pct"]) >= 10.0]
    new_listings = sorted(
        [x for x in enriched if x["is_new"]],
        key=lambda x: x["onboard_date"] or 0,
        reverse=True,
    )
    top_funding_long  = [x for x in enriched_sorted_fr if x["funding_rate"] > 0][:15]
    top_funding_short = list(reversed([x for x in enriched_sorted_fr if x["funding_rate"] < 0]))[:15]
    top_oi            = enriched_sorted_oi[:30]

    # Sentiment
    if avg_funding > 0.05:
        mood = "extreme_greed"
    elif avg_funding > 0.02:
        mood = "greed"
    elif avg_funding > 0.005:
        mood = "bullish"
    elif avg_funding >= -0.005:
        mood = "neutral"
    elif avg_funding >= -0.02:
        mood = "bearish"
    else:
        mood = "fear"

    total_oi_usdt = sum(x["open_interest_usdt"] or 0 for x in top_oi)

    return {
        "new_listings":      new_listings,
        "top_gainers":       top_gainers,
        "top_losers":        top_losers,
        "top_volume":        top_volume,
        "big_movers":        big_movers,
        "top_funding_long":  top_funding_long,
        "top_funding_short": top_funding_short,
        "top_oi":            top_oi,
        "market_stats": {
            "total_pairs":     len(enriched),
            "up_count":        up_count,
            "down_count":      down_count,
            "neutral_count":   len(enriched) - up_count - down_count,
            "avg_change_pct":  avg_change,
            "total_vol_usdt":  round(total_vol, 0),
            "new_count":       len(new_listings),
            "big_mover_count": len(big_movers),
        },
        "sentiment": {
            "avg_funding_rate":  avg_funding,
            "funding_pos_count": funding_pos,
            "funding_neg_count": funding_neg,
            "funding_neu_count": len(enriched) - funding_pos - funding_neg,
            "market_mood":       mood,
            "total_oi_usdt":     round(total_oi_usdt, 0),
        },
        "generated_at": time.time(),
    }


@router.get("/market/futures-overview")
async def futures_overview(
    new_days: int  = Query(default=30, ge=1, le=90,  description="Days to consider new listing"),
    top_n:    int  = Query(default=15, ge=5, le=50,  description="Results per category"),
    refresh:  bool = Query(default=False,            description="Force refresh cache"),
) -> dict:
    """
    Binance Futures 24H perpetual market overview.

    Returns new listings, top gainers/losers, volume leaders, big movers,
    funding rate extremes, open interest leaders, and market sentiment.
    Cached 60 seconds.
    """
    global _cache, _cache_ts

    if not refresh and _cache and (time.time() - _cache_ts) < CACHE_TTL:
        return _cache

    try:
        result    = await _fetch_overview()
        _cache    = result
        _cache_ts = time.time()
        logger.info(
            "futures_market_overview",
            pairs=result["market_stats"]["total_pairs"],
            new=result["market_stats"]["new_count"],
            mood=result["sentiment"]["market_mood"],
            avg_fr=result["sentiment"]["avg_funding_rate"],
        )
        return result
    except Exception as exc:
        logger.error("futures_market_overview_error", error=str(exc)[:120])
        if _cache:
            return _cache
        raise
