"""
Binance Futures data helpers — OHLCV + Funding Rate + Open Interest + Liquidations.

All endpoints use /fapi/v1/... (Binance USDT-M Futures).
Fetched concurrently per symbol.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.services.binance_urls import fapi

CANDLE_LIMIT = 100


# ── Data container ─────────────────────────────────────────────────────────────

@dataclass
class FuturesData:
    symbol: str
    tf: str

    # OHLCV
    opens:   list[float] = field(default_factory=list)
    highs:   list[float] = field(default_factory=list)
    lows:    list[float] = field(default_factory=list)
    closes:  list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)

    # Futures-specific
    funding_rate:     float = 0.0   # latest funding rate (e.g. 0.001 = 0.1%)
    funding_rate_avg: float = 0.0   # 8h avg funding rate
    oi_usdt:          float = 0.0   # current open interest in USDT
    oi_change_pct:    float = 0.0   # OI change % last 1h
    liq_long_usdt:    float = 0.0   # long liquidations last 1h (USDT)
    liq_short_usdt:   float = 0.0   # short liquidations last 1h (USDT)


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _fetch_klines(client: httpx.AsyncClient, symbol: str, tf: str) -> list:
    try:
        r = await client.get(
            fapi(f"/fapi/v1/klines?symbol={symbol}&interval={tf}&limit={CANDLE_LIMIT}")
        )
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list) and len(d) >= 30:
                return d
    except Exception:
        pass
    return []


async def _fetch_funding(client: httpx.AsyncClient, symbol: str) -> tuple[float, float]:
    """(latest_rate, 8h_avg). Positive = longs pay, Negative = shorts pay."""
    try:
        r = await client.get(fapi(f"/fapi/v1/fundingRate?symbol={symbol}&limit=8"))
        if r.status_code == 200:
            data = r.json()
            if data:
                rates  = [float(d["fundingRate"]) for d in data]
                return rates[-1], sum(rates) / len(rates)
    except Exception:
        pass
    return 0.0, 0.0


async def _fetch_oi(client: httpx.AsyncClient, symbol: str) -> tuple[float, float]:
    """(current_oi_usdt, oi_change_pct_1h)."""
    try:
        r1 = await client.get(fapi(f"/fapi/v1/openInterest?symbol={symbol}"))
        if r1.status_code != 200:
            return 0.0, 0.0
        current_oi = float(r1.json().get("openInterest", 0))

        r2 = await client.get(
            fapi(f"/futures/data/openInterestHist?symbol={symbol}&period=1h&limit=2")
        )
        if r2.status_code == 200:
            hist = r2.json()
            if isinstance(hist, list) and len(hist) >= 2:
                prev = float(hist[0]["sumOpenInterest"])
                curr = float(hist[-1]["sumOpenInterest"])
                change = (curr - prev) / prev * 100 if prev > 0 else 0.0
                return current_oi, change
        return current_oi, 0.0
    except Exception:
        return 0.0, 0.0


async def _fetch_liquidations(client: httpx.AsyncClient, symbol: str) -> tuple[float, float]:
    """
    Proxy liquidation pressure via globalLongShortAccountRatio (public, no auth).
    /fapi/v1/forceOrders requires signed API key (401 on public access).
    We use the L/S ratio shift: a drop in longRatio over 5m ≈ long liquidation pressure.
    Returns (long_liq_proxy, short_liq_proxy) as synthetic USDT values (0 if unavailable).
    """
    try:
        r = await client.get(
            fapi(f"/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=5m&limit=3")
        )
        if r.status_code != 200:
            return 0.0, 0.0
        data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            return 0.0, 0.0
        # ratio drop → long liquidation pressure; ratio rise → short liq pressure
        ratio_prev = float(data[0].get("longShortRatio", 1.0))
        ratio_now  = float(data[-1].get("longShortRatio", 1.0))
        shift      = ratio_now - ratio_prev
        # Convert to synthetic "pressure" (arbitrary scale, used for comparison only)
        long_liq_proxy  = max(0.0, -shift * 1_000_000)   # longs liquidated → ratio drops
        short_liq_proxy = max(0.0,  shift * 1_000_000)   # shorts liquidated → ratio rises
        return long_liq_proxy, short_liq_proxy
    except Exception:
        return 0.0, 0.0


# ── Main fetch ─────────────────────────────────────────────────────────────────

async def fetch_symbol_data(
    symbol: str,
    timeframes: list[str] = None,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, FuturesData]:
    """
    Fetch OHLCV + Futures signals for a symbol across multiple TFs.
    Returns {tf: FuturesData}.
    Futures signals (funding, OI, liquidations) are shared across all TFs.
    """
    if timeframes is None:
        timeframes = ["15m", "1h", "4h"]

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15)

    try:
        # All futures-specific data fetched once (same regardless of TF)
        kline_tasks   = {tf: asyncio.create_task(_fetch_klines(client, symbol, tf)) for tf in timeframes}
        funding_task  = asyncio.create_task(_fetch_funding(client, symbol))
        oi_task       = asyncio.create_task(_fetch_oi(client, symbol))
        liq_task      = asyncio.create_task(_fetch_liquidations(client, symbol))

        klines_map   = {tf: await task for tf, task in kline_tasks.items()}
        funding, f_avg = await funding_task
        oi_usdt, oi_chg = await oi_task
        liq_l, liq_s    = await liq_task

    finally:
        if own_client:
            await client.aclose()

    result: dict[str, FuturesData] = {}
    for tf, klines in klines_map.items():
        if not klines or len(klines) < 50:   # F2: need ≥50 candles for EMA50/indicators
            continue
        d = FuturesData(
            symbol   = symbol,
            tf       = tf,
            opens    = [float(k[1]) for k in klines],
            highs    = [float(k[2]) for k in klines],
            lows     = [float(k[3]) for k in klines],
            closes   = [float(k[4]) for k in klines],
            volumes  = [float(k[5]) for k in klines],
            funding_rate     = funding,
            funding_rate_avg = f_avg,
            oi_usdt          = oi_usdt,
            oi_change_pct    = oi_chg,
            liq_long_usdt    = liq_l,
            liq_short_usdt   = liq_s,
        )
        result[tf] = d
    return result


async def fetch_top100_futures() -> list[dict]:
    """
    Top-100 USDT perpetual pairs.

    Strategy (rate-limit safe):
      1. GET /fapi/v1/exchangeInfo  → weight=1  → list all USDT perp symbols
      2. GET /fapi/v2/ticker/24hr?symbols=[...] → weight=~20 for 100 symbols
         (compared to weight=40 for the no-param full-market call)

    This avoids the heavy weight=40 all-ticker call that triggers IP bans.
    """
    async with httpx.AsyncClient(timeout=20) as c:
        # Step 1: get all active USDT perpetual symbols (weight=1)
        info_r = await c.get(fapi("/fapi/v1/exchangeInfo"))
        if info_r.status_code != 200:
            return []

        info = info_r.json()
        symbols = [
            s["symbol"] for s in info.get("symbols", [])
            if s.get("symbol", "").endswith("USDT")
            and s.get("contractType") == "PERPETUAL"
            and s.get("status") == "TRADING"
        ]
        if not symbols:
            return []

        # Step 2: fetch 24h ticker — v1 with symbols param (v2 returns 404 on binance.bh)
        # weight = 2×N for N≤20, proportional for more (much lighter than no-param weight=40)
        import json as _json
        syms_param = _json.dumps(symbols[:200])  # cap at 200
        ticker_r = await c.get(
            fapi("/fapi/v1/ticker/24hr"),
            params={"symbols": syms_param},
        )
        if ticker_r.status_code != 200:
            return []

        tickers = ticker_r.json()
        if not isinstance(tickers, list):
            return []

        # Filter 1: stablecoin perpetuals
        _STABLE = {
            "USDC","FDUSD","TUSD","USDP","DAI","FRAX","USDD","RLUSD",
            "USD1","UUSD","BFUSD","USDE","BUSD","GUSD","HUSD","USDN",
            "USTC","UST","EUR","AEUR","EURT","EURS",
        }

        # Filter 2: commodity / TradFi index perpetuals
        # These instruments don't respond to crypto TA signals (Wyckoff/EMA/BB)
        _COMMODITY = {
            "SPY",     # S&P 500 ETF
            "PAXG",    # Tokenized Gold
            "XAUT",    # Tether Gold
            "COPPER",  # Copper futures
            "SILVER",  # Silver
            "GOLD",    # Gold
            "OIL",     # Oil
            "WTI",     # WTI Crude
            "CORN",    # Corn
            "WHEAT",   # Wheat
            "NATGAS",  # Natural gas
        }

        _SKIP = _STABLE | _COMMODITY

        def _base(sym: str) -> str:
            """Extract base asset: 'SPYUSDT' → 'SPY'."""
            s = sym.upper()
            return s[:-4] if s.endswith("USDT") else s

        tickers = [t for t in tickers if _base(t.get("symbol", "")) not in _SKIP]
        tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
        return tickers[:200]  # caller slices to desired universe size
