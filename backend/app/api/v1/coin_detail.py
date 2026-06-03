"""Coin detail — klines, info, and multi-timeframe TA analysis by trading style."""

import asyncio

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.signal_generator.pipeline import SignalPipeline

router = APIRouter(tags=["coin_detail"])
logger = structlog.get_logger(__name__)

from app.services.binance_urls import get_fapi_url, get_fallback_url, fapi, spot

async def _fetch_klines_with_fallback(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list:
    """Try fapi (binance.bh) first, fallback to vision for klines."""
    urls = [
        fapi(f"/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"),
        spot(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"),
        f"{get_fallback_url()}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
    ]
    last_error = "all URLs failed"
    for url in urls:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            last_error = str(e)
    raise HTTPException(status_code=503, detail=f"Klines unavailable for {symbol} {interval}: {last_error}")

STYLE_TIMEFRAMES: dict[str, dict[str, str]] = {
    "scalping":   {"t0": "4h",  "t1": "1h",  "t2": "1h",  "t3": "15m", "t4": "15m"},
    "daytrading": {"t0": "1d",  "t1": "4h",  "t2": "4h",  "t3": "1h",  "t4": "1h"},
    "swing":      {"t0": "1w",  "t1": "1d",  "t2": "1d",  "t3": "4h",  "t4": "4h"},
    "position":   {"t0": "1w",  "t1": "1w",  "t2": "1d",  "t3": "1d",  "t4": "1d"},
}

STYLE_LIMITS: dict[str, int] = {
    "scalping": 300, "daytrading": 200, "swing": 150, "position": 100,
}

GATE_LAYER_MAP = {
    "Gate (T0": "T1 Trend",
    "Gate (T2": "T2 S/R Zones",
    "Gate (T3": "T3 Pattern",
    "Gate (T4": "T4 Trigger",
    "T4: No trigger": "T4 Trigger",
    "T4: Dry volume": "T4 Trigger",
}

LAYER_ORDER = ["T0 Wyckoff", "T1 Trend", "T2 S/R Zones", "T3 Pattern", "T4 Trigger"]


class Candle(BaseModel):
    time: int; open: float; high: float; low: float; close: float; volume: float

class KlinesResponse(BaseModel):
    symbol: str; interval: str; candles: list[Candle]

class CoinInfo(BaseModel):
    symbol: str; last_price: float; mark_price: float; index_price: float
    change_24h: float; high_24h: float; low_24h: float; volume_24h: float
    quote_volume_24h: float; open_interest: float; funding_rate: float
    next_funding_time: int; count_24h: int

class TALayer(BaseModel):
    name: str; timeframe: str
    status: str   # passed | failed | skipped | gate_failed | blocked
    signal: str | None = None
    detail: str | None = None

class TakeProfit(BaseModel):
    level: int; price: float; rr: str; basis: str

class QuickAnalysisResponse(BaseModel):
    symbol: str; style: str; timeframes: dict[str, str]
    direction: str | None
    entry: float | None
    stop_loss: float | None
    sl_basis: str | None
    take_profits: list[TakeProfit]
    risk_reward: str | None
    confidence: float | None
    skip_reason: str | None
    layers: list[TALayer]


async def _fetch_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list:
    return await _fetch_klines_with_fallback(client, symbol, interval, limit)

def _parse(raw: list) -> tuple[list, list, list, list, list]:
    return (
        [float(c[1]) for c in raw], [float(c[2]) for c in raw],
        [float(c[3]) for c in raw], [float(c[4]) for c in raw],
        [float(c[5]) for c in raw],
    )

async def _gather_urls(client: httpx.AsyncClient, urls: list[str]) -> list:
    async def _get(url: str):
        r = await client.get(url)
        return r.json() if r.status_code == 200 else {}
    return await asyncio.gather(*[_get(u) for u in urls])

def _apply_gate_status(layers: list[TALayer], skip_reason: str | None) -> list[TALayer]:
    """Mark gate_failed on the blocking layer, blocked on all subsequent layers."""
    if not skip_reason:
        return layers
    failed_name: str | None = None
    for prefix, layer_name in GATE_LAYER_MAP.items():
        if skip_reason.startswith(prefix) or prefix in skip_reason:
            failed_name = layer_name
            break
    if not failed_name:
        return layers
    failed_idx = next((i for i, l in enumerate(layers) if l.name == failed_name), None)
    if failed_idx is None:
        return layers
    for i, layer in enumerate(layers):
        if i == failed_idx:
            layer.status = "gate_failed"
        elif i > failed_idx:
            layer.status = "blocked"
    return layers

def _calc_multi_tp(
    entry: float, sl: float, direction: str,
    resistance_prices: list[float], support_prices: list[float],
) -> list[TakeProfit]:
    """TP1/TP2/TP3 from S/R zones + Fibonacci extensions (1.272, 1.618, 2.618)."""
    risk = abs(entry - sl)
    if risk <= 0:
        return []

    is_long = direction == "LONG"
    tps: list[TakeProfit] = []
    used: set[float] = set()
    level = 1

    # S/R based targets
    zone_prices = sorted(
        [z for z in resistance_prices if z > entry],
    ) if is_long else sorted(
        [z for z in support_prices if z < entry], reverse=True
    )

    for price in zone_prices[:2]:
        rr = abs(price - entry) / risk
        if rr >= 1.5:
            tps.append(TakeProfit(
                level=level, price=round(price, 8),
                rr=f"1:{rr:.1f}",
                basis="Resistance zone" if is_long else "Support zone",
            ))
            used.add(round(price, 4))
            level += 1
            if level > 3:
                break

    # Fibonacci extension fallback / fill
    for fib_mult, fib_label in [(1.272, "Fib 1.272"), (1.618, "Fib 1.618"), (2.618, "Fib 2.618")]:
        if level > 3:
            break
        tp_price = entry + risk * fib_mult if is_long else entry - risk * fib_mult
        rounded = round(tp_price, 4)
        if any(abs(rounded - p) / max(entry, 1e-10) < 0.005 for p in used):
            continue
        rr = abs(tp_price - entry) / risk
        if rr >= 1.5:
            tps.append(TakeProfit(
                level=level, price=round(tp_price, 8),
                rr=f"1:{rr:.1f}", basis=fib_label,
            ))
            used.add(rounded)
            level += 1

    # Ensure 3 TPs using simple R:R multiples if needed
    for rr_mult in [2.0, 3.0, 5.0]:
        if level > 3:
            break
        tp_price = entry + risk * rr_mult if is_long else entry - risk * rr_mult
        rounded = round(tp_price, 4)
        if any(abs(rounded - p) / max(entry, 1e-10) < 0.005 for p in used):
            continue
        tps.append(TakeProfit(
            level=level, price=round(tp_price, 8),
            rr=f"1:{rr_mult:.1f}", basis=f"R:R {rr_mult}x",
        ))
        used.add(rounded)
        level += 1

    return sorted(tps, key=lambda t: t.level)


@router.get("/coin/{symbol}/klines", response_model=KlinesResponse)
async def get_coin_klines(
    symbol: str,
    interval: str = Query(default="1h"),
    limit: int = Query(default=100, le=500),
) -> KlinesResponse:
    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        raw = await _fetch_klines(client, symbol.upper(), interval, limit)
    candles = [Candle(time=int(c[0])//1000, open=float(c[1]), high=float(c[2]),
                      low=float(c[3]), close=float(c[4]), volume=float(c[5])) for c in raw]
    return KlinesResponse(symbol=symbol.upper(), interval=interval, candles=candles)


@router.get("/coin/{symbol}/info", response_model=CoinInfo)
async def get_coin_info(symbol: str) -> CoinInfo:
    sym = symbol.upper()
    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        ticker_r, mark_r, oi_r, funding_r = await _gather_urls(client, [
            fapi(f"/fapi/v1/ticker/24hr?symbol={sym}"),
            fapi(f"/fapi/v1/premiumIndex?symbol={sym}"),
            fapi(f"/fapi/v1/openInterest?symbol={sym}"),
            fapi(f"/fapi/v1/fundingRate?symbol={sym}&limit=1"),
        ])
    last_price = float(ticker_r.get("lastPrice", 0))
    mark_price = float(mark_r.get("markPrice", last_price))
    index_price = float(mark_r.get("indexPrice", last_price))
    funding_rate = 0.0
    if isinstance(funding_r, list) and funding_r:
        funding_rate = float(funding_r[0].get("fundingRate", 0))
    elif isinstance(funding_r, dict):
        funding_rate = float(funding_r.get("lastFundingRate", mark_r.get("lastFundingRate", 0)))

    return CoinInfo(
        symbol=sym, last_price=last_price,
        mark_price=mark_price, index_price=index_price,
        change_24h=round(float(ticker_r.get("priceChangePercent", 0)), 2),
        high_24h=float(ticker_r.get("highPrice", 0)), low_24h=float(ticker_r.get("lowPrice", 0)),
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
    style: str = Query(default="swing"),
) -> QuickAnalysisResponse:
    """Multi-timeframe T0→T4. Gate failures visible per layer. Multi-TP from S/R + Fibonacci."""

    sym = symbol.upper()
    style = style.lower()
    if style not in STYLE_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Unknown style: {style}")

    tfs = STYLE_TIMEFRAMES[style]
    limit = STYLE_LIMITS[style]
    unique_tfs = list(dict.fromkeys(tfs.values()))

    async with httpx.AsyncClient(timeout=25, verify=False) as client:
        results = await asyncio.gather(
            *[_fetch_klines(client, sym, tf, limit) for tf in unique_tfs],
            return_exceptions=True,
        )

    klines: dict[str, list] = {}
    for tf, result in zip(unique_tfs, results):
        if isinstance(result, Exception):
            raise HTTPException(status_code=503, detail=f"Failed {tf}: {result}")
        klines[tf] = result

    from app.services.ta_engine import (
        analyze_trend, detect_wyckoff_phase, detect_support_resistance,
        detect_patterns, analyze_market_structure, detect_trigger,
    )

    layers: list[TALayer] = []
    sr_data = None

    try:
        # T0
        tf0 = tfs["t0"]
        _, h0, l0, c0, v0 = _parse(klines[tf0])
        wyckoff = detect_wyckoff_phase(h0, l0, c0, v0, "sideways")
        if wyckoff:
            layers.append(TALayer(name="T0 Wyckoff", timeframe=tf0.upper(), status="passed",
                                  signal=wyckoff.phase.value,
                                  detail=f"Strength {wyckoff.strength:.0f}% | {wyckoff.description}"))
        else:
            layers.append(TALayer(name="T0 Wyckoff", timeframe=tf0.upper(), status="failed",
                                  detail="Cannot determine phase"))

        # T1
        tf1 = tfs["t1"]
        o1, h1, l1, c1, _ = _parse(klines[tf1])
        trend = analyze_trend(o1, h1, l1, c1)
        if trend:
            tl = f" | Trendline {trend.trendline.num_touches}x" if trend.trendline and trend.trendline.is_valid else ""
            layers.append(TALayer(name="T1 Trend", timeframe=tf1.upper(), status="passed",
                                  signal=trend.direction,
                                  detail=f"EMA13={trend.ema_13:.4f} | EMA21={trend.ema_21:.4f}{tl}"))
        else:
            layers.append(TALayer(name="T1 Trend", timeframe=tf1.upper(), status="failed",
                                  detail="Insufficient data"))

        # T2
        tf2 = tfs["t2"]
        _, h2, l2, c2, _ = _parse(klines[tf2])
        sr_data = detect_support_resistance(h2, l2, c2, lookback_days=30)
        if sr_data:
            sup = (f"Support ${sr_data.strongest_support.midpoint:.4f} ({sr_data.strongest_support.num_bounces}x)"
                   if sr_data.strongest_support else "No support")
            res = (f"Resist ${sr_data.strongest_resistance.midpoint:.4f} ({sr_data.strongest_resistance.num_bounces}x)"
                   if sr_data.strongest_resistance else "No resistance")
            layers.append(TALayer(name="T2 S/R Zones", timeframe=tf2.upper(), status="passed",
                                  detail=f"{sup} | {res}"))
        else:
            layers.append(TALayer(name="T2 S/R Zones", timeframe=tf2.upper(), status="failed",
                                  detail="No S/R found"))

        # T3
        tf3 = tfs["t3"]
        _, h3, l3, _, _ = _parse(klines[tf3])
        pattern = detect_patterns(h3, l3)
        structure = analyze_market_structure(h3, l3)
        pat_name = pattern.pattern_type.value if pattern else "No pattern"
        breakout = f" → {pattern.potential_breakout}" if pattern else ""
        str_pct = f" ({pattern.formation_strength:.0f}%)" if pattern else ""
        bias = structure.structure.value if structure else "Unknown"
        hh = structure.hh_count if structure else 0
        ll = structure.ll_count if structure else 0
        layers.append(TALayer(name="T3 Pattern", timeframe=tf3.upper(),
                               status="passed" if pattern else "skipped",
                               signal=f"{pat_name}{breakout}",
                               detail=f"Bias: {bias} | HH:{hh} LL:{ll}{str_pct}"))

        # T4
        tf4 = tfs["t4"]
        o4, h4, l4, c4, v4 = _parse(klines[tf4])
        trigger = detect_trigger(o4, h4, l4, c4, v4)
        if trigger:
            candle = trigger.candlestick_pattern or "N/A"
            stoch = trigger.stochastic_signal or "N/A"
            layers.append(TALayer(name="T4 Trigger", timeframe=tf4.upper(), status="passed",
                                  signal=trigger.direction.upper(),
                                  detail=f"Candle: {candle} | Stoch: {stoch} | Conf: {trigger.confidence:.0f}%"))
        else:
            layers.append(TALayer(name="T4 Trigger", timeframe=tf4.upper(), status="failed",
                                  detail="No trigger signal"))

        # Full pipeline (T4 data for gate check)
        pipeline = SignalPipeline(sym, tf4)
        signal = pipeline.run(o4, h4, l4, c4, v4)
        skip_reason = pipeline.skip_reason if not signal else None

        # Apply gate status to layers so UI shows exactly which gate blocked
        layers = _apply_gate_status(layers, skip_reason)

        if signal:
            entry = float(signal.entry)
            sl = float(signal.stop_loss)
            direction = signal.direction.upper()

            # Collect all S/R prices for multi-TP
            res_prices: list[float] = []
            sup_prices: list[float] = []
            if sr_data:
                for zone in getattr(sr_data, "resistance_zones", []):
                    res_prices.append(float(zone.midpoint))
                for zone in getattr(sr_data, "support_zones", []):
                    sup_prices.append(float(zone.midpoint))
                if sr_data.strongest_resistance:
                    res_prices.insert(0, float(sr_data.strongest_resistance.midpoint))
                if sr_data.strongest_support:
                    sup_prices.insert(0, float(sr_data.strongest_support.midpoint))

            take_profits = _calc_multi_tp(entry, sl, direction, res_prices, sup_prices)
            sl_basis = "Below strongest support" if direction == "LONG" else "Above strongest resistance"
            best_tp = take_profits[1] if len(take_profits) >= 2 else (take_profits[0] if take_profits else None)

            return QuickAnalysisResponse(
                symbol=sym, style=style, timeframes=tfs,
                direction=direction, entry=entry, stop_loss=sl, sl_basis=sl_basis,
                take_profits=take_profits,
                risk_reward=best_tp.rr if best_tp else signal.risk_reward,
                confidence=float(signal.confidence),
                skip_reason=None, layers=layers,
            )
        else:
            return QuickAnalysisResponse(
                symbol=sym, style=style, timeframes=tfs,
                direction=None, entry=None, stop_loss=None, sl_basis=None,
                take_profits=[], risk_reward=None, confidence=None,
                skip_reason=skip_reason, layers=layers,
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analysis_failed", symbol=sym, style=style, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
