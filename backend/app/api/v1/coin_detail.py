"""Coin detail endpoints — klines, info, and quick TA analysis for any futures symbol."""

import hashlib
import hmac
import time
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
SPOT_BASE = "https://api.binance.com"


def _sign(secret: str, query_string: str) -> str:
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def _signed_qs(secret: str) -> str:
    ts = int(time.time() * 1000)
    qs = f"timestamp={ts}&recvWindow=10000"
    return f"{qs}&signature={_sign(secret, qs)}"


# ── Schemas ──────────────────────────────────────────────────────────────────

class Candle(BaseModel):
    time: int       # Unix timestamp seconds
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
    status: str       # passed / failed / skipped
    signal: str | None = None
    detail: str | None = None

class QuickAnalysisResponse(BaseModel):
    symbol: str
    interval: str
    direction: str | None       # LONG / SHORT / None
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: str | None
    confidence: float | None
    skip_reason: str | None
    layers: list[TALayer]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/coin/{symbol}/klines", response_model=KlinesResponse)
async def get_coin_klines(
    symbol: str,
    interval: str = Query(default="1h", description="1m 5m 15m 1h 4h 1d 1w"),
    limit: int = Query(default=100, le=500),
) -> KlinesResponse:
    """Fetch OHLCV candlestick data for a futures symbol."""

    url = f"{FAPI_BASE}/fapi/v1/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text[:200])
        raw = r.json()

    candles = [
        Candle(
            time=int(c[0]) // 1000,
            open=float(c[1]),
            high=float(c[2]),
            low=float(c[3]),
            close=float(c[4]),
            volume=float(c[5]),
        )
        for c in raw
    ]

    return KlinesResponse(symbol=symbol.upper(), interval=interval, candles=candles)


@router.get("/coin/{symbol}/info", response_model=CoinInfo)
async def get_coin_info(symbol: str) -> CoinInfo:
    """Fetch detailed market info for a futures coin — funding rate, OI, 24h stats."""

    sym = symbol.upper()
    async with httpx.AsyncClient(timeout=15) as client:
        ticker_r, mark_r, oi_r, funding_r = await _gather(client, [
            f"{FAPI_BASE}/fapi/v1/ticker/24hr?symbol={sym}",
            f"{FAPI_BASE}/fapi/v1/premiumIndex?symbol={sym}",
            f"{FAPI_BASE}/fapi/v1/openInterest?symbol={sym}",
            f"{FAPI_BASE}/fapi/v1/fundingRate?symbol={sym}&limit=1",
        ])

    ticker = ticker_r
    mark = mark_r
    oi = oi_r
    funding_list = funding_r

    funding_rate = float(funding_list[0]["fundingRate"]) if funding_list else float(mark.get("lastFundingRate", 0))
    next_funding = int(mark.get("nextFundingTime", 0))

    return CoinInfo(
        symbol=sym,
        last_price=float(ticker.get("lastPrice", 0)),
        mark_price=float(mark.get("markPrice", 0)),
        index_price=float(mark.get("indexPrice", 0)),
        change_24h=round(float(ticker.get("priceChangePercent", 0)), 2),
        high_24h=float(ticker.get("highPrice", 0)),
        low_24h=float(ticker.get("lowPrice", 0)),
        volume_24h=round(float(ticker.get("volume", 0)), 2),
        quote_volume_24h=round(float(ticker.get("quoteVolume", 0)), 0),
        open_interest=round(float(oi.get("openInterest", 0)), 2),
        funding_rate=round(funding_rate * 100, 4),
        next_funding_time=next_funding,
        count_24h=int(ticker.get("count", 0)),
    )


@router.get("/coin/{symbol}/analyze", response_model=QuickAnalysisResponse)
async def quick_analysis(
    symbol: str,
    interval: str = Query(default="1h"),
    limit: int = Query(default=100, le=500),
) -> QuickAnalysisResponse:
    """Run T0→T4 TA pipeline on a futures symbol and return BUY/SELL/SKIP signal."""

    sym = symbol.upper()
    url = f"{FAPI_BASE}/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}"

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text[:200])
        raw = r.json()

    if len(raw) < 30:
        raise HTTPException(status_code=422, detail="Not enough candle data")

    opens  = [float(c[1]) for c in raw]
    highs  = [float(c[2]) for c in raw]
    lows   = [float(c[3]) for c in raw]
    closes = [float(c[4]) for c in raw]
    vols   = [float(c[5]) for c in raw]

    # Run pipeline with layer tracking
    layers: list[TALayer] = []

    from app.services.ta_engine import (
        analyze_trend, detect_wyckoff_phase, detect_support_resistance,
        detect_patterns, analyze_market_structure, detect_trigger, validate_no_dry_volume,
    )
    from app.services.signal_generator.risk_calculator import (
        calculate_stop_loss, calculate_take_profit, calculate_risk_metrics,
    )
    from app.services.signal_generator.signal_card import build_signal_card

    try:
        # T0 Wyckoff
        wyckoff = detect_wyckoff_phase(highs, lows, closes, vols, "sideways")
        if wyckoff:
            layers.append(TALayer(name="T0 Wyckoff", status="passed",
                                  signal=wyckoff.phase.value,
                                  detail=f"Strength: {wyckoff.strength:.0f}% | {wyckoff.description}"))
        else:
            layers.append(TALayer(name="T0 Wyckoff", status="failed", detail="Cannot determine phase"))

        # T1 Trend
        trend = analyze_trend(opens, highs, lows, closes)
        if trend:
            tl_info = f" | Trendline: {trend.trendline.num_touches} touches" if trend.trendline and trend.trendline.is_valid else ""
            layers.append(TALayer(name="T1 Trend", status="passed",
                                  signal=trend.direction,
                                  detail=f"EMA13={trend.ema_13:.4f} | EMA21={trend.ema_21:.4f}{tl_info}"))
        else:
            layers.append(TALayer(name="T1 Trend", status="failed", detail="Insufficient data for EMA"))

        # T2 S/R
        sr = detect_support_resistance(highs, lows, closes, lookback_days=30)
        if sr:
            sup = (f"Support ${sr.strongest_support.midpoint:.4f} "
                   f"({sr.strongest_support.num_bounces} bounces, "
                   f"str={sr.strongest_support.strength:.0f})") if sr.strongest_support else "No support"
            res = (f"Resist ${sr.strongest_resistance.midpoint:.4f} "
                   f"({sr.strongest_resistance.num_bounces} bounces)") if sr.strongest_resistance else "No resistance"
            layers.append(TALayer(name="T2 S/R Zones", status="passed", detail=f"{sup} | {res}"))
        else:
            layers.append(TALayer(name="T2 S/R Zones", status="failed", detail="No clear S/R found"))

        # T3 Pattern
        pattern = detect_patterns(highs, lows)
        structure = analyze_market_structure(highs, lows)
        pat_name = pattern.pattern_type.value if pattern else "No chart pattern"
        breakout = f" → {pattern.potential_breakout}" if pattern else ""
        strength_str = f" ({pattern.formation_strength:.0f}%)" if pattern else ""
        bias = structure.structure.value if structure else "Unknown"
        hh = structure.hh_count if structure else 0
        ll = structure.ll_count if structure else 0
        layers.append(TALayer(name="T3 Pattern", status="passed" if pattern else "skipped",
                               signal=f"{pat_name}{breakout}",
                               detail=f"Bias: {bias} | HH:{hh} LL:{ll}{strength_str}"))

        # T4 Trigger
        trigger = detect_trigger(opens, highs, lows, closes, vols)
        if trigger:
            candle = trigger.candle_pattern.value if trigger.candle_pattern else "N/A"
            stoch = trigger.stochastic_signal or "N/A"
            layers.append(TALayer(name="T4 Trigger", status="passed",
                                  signal=trigger.direction.upper(),
                                  detail=f"Candle: {candle} | Stoch: {stoch} | Confidence: {trigger.confidence:.0f}%"))
        else:
            layers.append(TALayer(name="T4 Trigger", status="failed", detail="No trigger signal detected"))

        # Run full pipeline for final decision
        pipeline = SignalPipeline(sym, interval)
        signal = pipeline.run(opens, highs, lows, closes, vols)

        if signal:
            return QuickAnalysisResponse(
                symbol=sym,
                interval=interval,
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
                symbol=sym,
                interval=interval,
                direction=None,
                entry=None,
                stop_loss=None,
                take_profit=None,
                risk_reward=None,
                confidence=None,
                skip_reason=pipeline.skip_reason,
                layers=layers,
            )

    except Exception as exc:
        logger.error("analysis_failed", symbol=sym, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


async def _gather(client: httpx.AsyncClient, urls: list[str]) -> list:
    """Fetch multiple URLs concurrently."""
    import asyncio
    async def _fetch(url: str):
        r = await client.get(url)
        if r.status_code == 200:
            return r.json()
        return {}
    return await asyncio.gather(*[_fetch(u) for u in urls])
