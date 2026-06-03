"""Coin detail endpoints — klines, info, and multi-timeframe TA analysis by trading style."""

import hashlib
import hmac
import time
import asyncio
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import get_settings
from app.services.signal_generator.pipeline import SignalPipeline

router = APIRouter(tags=["coin_detail"])
logger = structlog.get_logger(__name__)

FAPI_BASE = "https://fapi.binance.com"


# ── Trading style → timeframe mapping ────────────────────────────────────────

STYLE_TIMEFRAMES: dict[str, dict[str, str]] = {
    "scalping":  {"t0": "4h",  "t1": "1h",  "t2": "1h",  "t3": "15m", "t4": "15m", "chart": "15m"},
    "daytrading":{"t0": "1d",  "t1": "4h",  "t2": "4h",  "t3": "1h",  "t4": "1h",  "chart": "1h"},
    "swing":     {"t0": "1w",  "t1": "1d",  "t2": "1d",  "t3": "4h",  "t4": "4h",  "chart": "4h"},
    "position":  {"t0": "1w",  "t1": "1w",  "t2": "1d",  "t3": "1d",  "t4": "1d",  "chart": "1d"},
}

STYLE_LIMITS: dict[str, int] = {
    "scalping":   300,
    "daytrading": 200,
    "swing":      150,
    "position":   100,
}


# ── Schemas ──────────────────────────────────────────────────────────────────

class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class KlinesResponse(BaseModel):
    symbol: str
    interval: str
    candles: list[Candle]


class CoinInfo(BaseModel):
    symbol: str
    last_price: float
    mark_price: float
    index_price: float
    change_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float
    quote_volume_24h: float
    open_interest: float
    funding_rate: float
    next_funding_time: int
    count_24h: int


class TALayer(BaseModel):
    name: str
    timeframe: str
    status: str   # passed / failed / skipped
    signal: str | None = None
    detail: str | None = None


class QuickAnalysisResponse(BaseModel):
    symbol: str
    style: str
    timeframes: dict[str, str]   # {"t0": "4h", "t1": "1h", ...}
    direction: str | None
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: str | None
    confidence: float | None
    skip_reason: str | None
    layers: list[TALayer]


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _fetch_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list:
    url = f"{FAPI_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    r = await client.get(url)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=f"Binance {interval}: {r.text[:100]}")
    return r.json()


def _parse(raw: list) -> tuple[list, list, list, list, list]:
    opens  = [float(c[1]) for c in raw]
    highs  = [float(c[2]) for c in raw]
    lows   = [float(c[3]) for c in raw]
    closes = [float(c[4]) for c in raw]
    vols   = [float(c[5]) for c in raw]
    return opens, highs, lows, closes, vols


async def _gather(client: httpx.AsyncClient, urls: list[str]) -> list:
    async def _get(url: str):
        r = await client.get(url)
        return r.json() if r.status_code == 200 else {}
    return await asyncio.gather(*[_get(u) for u in urls])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/coin/{symbol}/klines", response_model=KlinesResponse)
async def get_coin_klines(
    symbol: str,
    interval: str = Query(default="1h"),
    limit: int = Query(default=100, le=500),
) -> KlinesResponse:
    """Fetch OHLCV candles for any futures symbol."""
    async with httpx.AsyncClient(timeout=15) as client:
        raw = await _fetch_klines(client, symbol.upper(), interval, limit)
    candles = [
        Candle(time=int(c[0]) // 1000, open=float(c[1]), high=float(c[2]),
               low=float(c[3]), close=float(c[4]), volume=float(c[5]))
        for c in raw
    ]
    return KlinesResponse(symbol=symbol.upper(), interval=interval, candles=candles)


@router.get("/coin/{symbol}/info", response_model=CoinInfo)
async def get_coin_info(symbol: str) -> CoinInfo:
    """Fetch funding rate, OI, and 24h stats."""
    sym = symbol.upper()
    async with httpx.AsyncClient(timeout=15) as client:
        ticker_r, mark_r, oi_r, funding_r = await _gather(client, [
            f"{FAPI_BASE}/fapi/v1/ticker/24hr?symbol={sym}",
            f"{FAPI_BASE}/fapi/v1/premiumIndex?symbol={sym}",
            f"{FAPI_BASE}/fapi/v1/openInterest?symbol={sym}",
            f"{FAPI_BASE}/fapi/v1/fundingRate?symbol={sym}&limit=1",
        ])
    funding_rate = float(funding_r[0]["fundingRate"]) if funding_r else float(mark_r.get("lastFundingRate", 0))
    return CoinInfo(
        symbol=sym,
        last_price=float(ticker_r.get("lastPrice", 0)),
        mark_price=float(mark_r.get("markPrice", 0)),
        index_price=float(mark_r.get("indexPrice", 0)),
        change_24h=round(float(ticker_r.get("priceChangePercent", 0)), 2),
        high_24h=float(ticker_r.get("highPrice", 0)),
        low_24h=float(ticker_r.get("lowPrice", 0)),
        volume_24h=round(float(ticker_r.get("volume", 0)), 2),
        quote_volume_24h=round(float(ticker_r.get("quoteVolume", 0)), 0),
        open_interest=round(float(oi_r.get("openInterest", 0)), 2),
        funding_rate=round(funding_rate * 100, 4),
        next_funding_time=int(mark_r.get("nextFundingTime", 0)),
        count_24h=int(ticker_r.get("count", 0)),
    )


@router.get("/coin/{symbol}/analyze", response_model=QuickAnalysisResponse)
async def quick_analysis(
    symbol: str,
    style: str = Query(default="swing", description="scalping | daytrading | swing | position"),
) -> QuickAnalysisResponse:
    """Run multi-timeframe T0→T4 pipeline based on trading style."""

    sym = symbol.upper()
    style = style.lower()

    if style not in STYLE_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Unknown style '{style}'. Use: scalping, daytrading, swing, position")

    tfs = STYLE_TIMEFRAMES[style]
    limit = STYLE_LIMITS[style]
    layers: list[TALayer] = []

    # Fetch all needed timeframes concurrently (deduplicated)
    unique_tfs = list(dict.fromkeys([tfs["t0"], tfs["t1"], tfs["t2"], tfs["t3"], tfs["t4"]]))

    async with httpx.AsyncClient(timeout=20) as client:
        results = await asyncio.gather(
            *[_fetch_klines(client, sym, tf, limit) for tf in unique_tfs],
            return_exceptions=True,
        )

    klines: dict[str, list] = {}
    for tf, result in zip(unique_tfs, results):
        if isinstance(result, Exception):
            raise HTTPException(status_code=503, detail=f"Failed to fetch {tf} data: {result}")
        klines[tf] = result

    from app.services.ta_engine import (
        analyze_trend, detect_wyckoff_phase, detect_support_resistance,
        detect_patterns, analyze_market_structure, detect_trigger, validate_no_dry_volume,
    )

    try:
        # ── T0 Wyckoff ────────────────────────────────────────────
        tf0 = tfs["t0"]
        _, highs0, lows0, closes0, vols0 = _parse(klines[tf0])
        wyckoff = detect_wyckoff_phase(highs0, lows0, closes0, vols0, "sideways")
        if wyckoff:
            layers.append(TALayer(name="T0 Wyckoff", timeframe=tf0.upper(), status="passed",
                                  signal=wyckoff.phase.value,
                                  detail=f"Strength {wyckoff.strength:.0f}% | {wyckoff.description}"))
        else:
            layers.append(TALayer(name="T0 Wyckoff", timeframe=tf0.upper(), status="failed",
                                  detail="Cannot determine phase"))

        # ── T1 Trend ──────────────────────────────────────────────
        tf1 = tfs["t1"]
        opens1, highs1, lows1, closes1, _ = _parse(klines[tf1])
        trend = analyze_trend(opens1, highs1, lows1, closes1)
        if trend:
            tl = f" | Trendline {trend.trendline.num_touches}x" if trend.trendline and trend.trendline.is_valid else ""
            layers.append(TALayer(name="T1 Trend", timeframe=tf1.upper(), status="passed",
                                  signal=trend.direction,
                                  detail=f"EMA13={trend.ema_13:.4f} | EMA21={trend.ema_21:.4f}{tl}"))
        else:
            layers.append(TALayer(name="T1 Trend", timeframe=tf1.upper(), status="failed",
                                  detail="Insufficient data"))

        # ── T2 S/R ────────────────────────────────────────────────
        tf2 = tfs["t2"]
        _, highs2, lows2, closes2, _ = _parse(klines[tf2])
        sr = detect_support_resistance(highs2, lows2, closes2, lookback_days=30)
        if sr:
            sup = (f"Support ${sr.strongest_support.midpoint:.4f} ({sr.strongest_support.num_bounces}x)"
                   if sr.strongest_support else "No support")
            res = (f"Resist ${sr.strongest_resistance.midpoint:.4f} ({sr.strongest_resistance.num_bounces}x)"
                   if sr.strongest_resistance else "No resistance")
            layers.append(TALayer(name="T2 S/R Zones", timeframe=tf2.upper(), status="passed",
                                  detail=f"{sup} | {res}"))
        else:
            layers.append(TALayer(name="T2 S/R Zones", timeframe=tf2.upper(), status="failed",
                                  detail="No clear S/R found"))

        # ── T3 Pattern ────────────────────────────────────────────
        tf3 = tfs["t3"]
        _, highs3, lows3, _, _ = _parse(klines[tf3])
        pattern = detect_patterns(highs3, lows3)
        structure = analyze_market_structure(highs3, lows3)
        pat_name = pattern.pattern_type.value if pattern else "No chart pattern"
        breakout = f" → {pattern.potential_breakout}" if pattern else ""
        str_pct = f" ({pattern.formation_strength:.0f}%)" if pattern else ""
        bias = structure.structure.value if structure else "Unknown"
        hh = structure.hh_count if structure else 0
        ll = structure.ll_count if structure else 0
        layers.append(TALayer(name="T3 Pattern", timeframe=tf3.upper(),
                               status="passed" if pattern else "skipped",
                               signal=f"{pat_name}{breakout}",
                               detail=f"Bias: {bias} | HH:{hh} LL:{ll}{str_pct}"))

        # ── T4 Trigger ────────────────────────────────────────────
        tf4 = tfs["t4"]
        opens4, highs4, lows4, closes4, vols4 = _parse(klines[tf4])
        trigger = detect_trigger(opens4, highs4, lows4, closes4, vols4)
        if trigger:
            candle = trigger.candlestick_pattern or "N/A"
            stoch = trigger.stochastic_signal or "N/A"
            layers.append(TALayer(name="T4 Trigger", timeframe=tf4.upper(), status="passed",
                                  signal=trigger.direction.upper(),
                                  detail=f"Candle: {candle} | Stoch: {stoch} | Conf: {trigger.confidence:.0f}%"))
        else:
            layers.append(TALayer(name="T4 Trigger", timeframe=tf4.upper(), status="failed",
                                  detail="No trigger signal"))

        # ── Full pipeline for final signal ────────────────────────
        # Use T4 timeframe data for the final pipeline run
        pipeline = SignalPipeline(sym, tf4)
        signal = pipeline.run(opens4, highs4, lows4, closes4, vols4)

        if signal:
            return QuickAnalysisResponse(
                symbol=sym, style=style, timeframes=tfs,
                direction=signal.direction.upper(),
                entry=float(signal.entry),
                stop_loss=float(signal.stop_loss),
                take_profit=float(signal.take_profit),
                risk_reward=signal.risk_reward,
                confidence=float(signal.confidence),
                skip_reason=None,
                layers=layers,
            )
        else:
            return QuickAnalysisResponse(
                symbol=sym, style=style, timeframes=tfs,
                direction=None, entry=None, stop_loss=None,
                take_profit=None, risk_reward=None, confidence=None,
                skip_reason=pipeline.skip_reason,
                layers=layers,
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analysis_failed", symbol=sym, style=style, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
