"""Coin detail — klines, info, and multi-timeframe TA analysis by trading style."""

import asyncio

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# SignalPipeline not used here — multi-TF gate logic is inline in quick_analysis

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
    stop_explanation: str | None   # human-readable: why it stopped + what to watch for
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
    """
    Multi-timeframe T0→T4 analysis.
    Each layer runs on its own correct timeframe per trading style.
    Gates check alignment across layers using real multi-TF data.
    """
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
        validate_no_dry_volume,
    )
    from app.services.signal_generator.risk_calculator import (
        calculate_stop_loss, calculate_take_profit, calculate_risk_metrics,
    )

    layers: list[TALayer] = []
    skip_reason: str | None = None
    stop_explanation: str | None = None

    def _no_signal(reason: str, explanation: str, failed_layer: str) -> QuickAnalysisResponse:
        """Mark gate_failed + blocked and return no-signal response."""
        failed_idx = next((i for i, l in enumerate(layers) if l.name == failed_layer), None)
        if failed_idx is not None:
            for i, layer in enumerate(layers):
                if i == failed_idx:
                    layer.status = "gate_failed"
                elif i > failed_idx:
                    layer.status = "blocked"
        return QuickAnalysisResponse(
            symbol=sym, style=style, timeframes=tfs,
            direction=None, entry=None, stop_loss=None, sl_basis=None,
            take_profits=[], risk_reward=None, confidence=None,
            skip_reason=reason, stop_explanation=explanation,
            layers=layers,
        )

    try:
        # ── T0: Wyckoff phase ──────────────────────────────────────────────────
        tf0 = tfs["t0"]
        _, h0, l0, c0, v0 = _parse(klines[tf0])
        wyckoff = detect_wyckoff_phase(h0, l0, c0, v0, "sideways")
        if not wyckoff:
            layers.append(TALayer(name="T0 Wyckoff", timeframe=tf0.upper(), status="failed",
                                  detail="Cannot determine Wyckoff phase"))
            return _no_signal(
                "T0: Cannot determine Wyckoff phase",
                f"Data {tf0.upper()} tidak cukup untuk menentukan fase Wyckoff. "
                "Pastikan koin ini aktif diperdagangkan dengan volume yang cukup.",
                "T0 Wyckoff",
            )
        wyckoff_phase = wyckoff.phase.value
        layers.append(TALayer(
            name="T0 Wyckoff", timeframe=tf0.upper(), status="passed",
            signal=wyckoff_phase,
            detail=f"Strength {wyckoff.strength:.0f}% | {wyckoff.description}",
        ))

        # ── T1: Trend ──────────────────────────────────────────────────────────
        tf1 = tfs["t1"]
        o1, h1, l1, c1, _ = _parse(klines[tf1])
        trend = analyze_trend(o1, h1, l1, c1)
        if not trend:
            layers.append(TALayer(name="T1 Trend", timeframe=tf1.upper(), status="failed",
                                  detail="Insufficient data for trend"))
            return _no_signal(
                "T1: Cannot determine trend",
                f"Data {tf1.upper()} tidak cukup untuk analisis trend EMA.",
                "T1 Trend",
            )
        trend_dir = trend.direction
        tl_note = f" | Trendline {trend.trendline.num_touches}x" if trend.trendline and trend.trendline.is_valid else ""
        layers.append(TALayer(
            name="T1 Trend", timeframe=tf1.upper(), status="passed",
            signal=trend_dir,
            detail=f"EMA13={trend.ema_13:.4f} | EMA21={trend.ema_21:.4f}{tl_note}",
        ))

        # Gate T0→T1: Wyckoff phase vs trend direction
        # Mark Up harus uptrend. Mark Down harus downtrend.
        # Accumulation/Distribution boleh any trend (fase transisi).
        contradiction = False
        gate_explanation = ""
        if wyckoff_phase == "Mark Up" and trend_dir == "downtrend":
            contradiction = True
            gate_explanation = (
                f"T0 mendeteksi fase Mark Up ({tf0.upper()}) — harga seharusnya naik kuat. "
                f"Namun T1 menunjukkan downtrend ({tf1.upper()}, EMA13 < EMA21). "
                "Ini kontradiksi kuat: jika Mark Up tapi trend sudah berbalik turun, "
                "kemungkinan markup sudah selesai dan distribusi mulai. "
                "Tunggu konfirmasi: EMA13 harus kembali di atas EMA21 sebelum entry LONG."
            )
        elif wyckoff_phase == "Mark Down" and trend_dir == "uptrend":
            contradiction = True
            gate_explanation = (
                f"T0 mendeteksi fase Mark Down ({tf0.upper()}) — harga seharusnya turun. "
                f"Namun T1 menunjukkan uptrend ({tf1.upper()}, EMA13 > EMA21). "
                "Ini kontradiksi: jika Mark Down tapi trend sudah berbalik naik, "
                "kemungkinan markdown selesai dan akumulasi mulai. "
                "Tunggu konfirmasi: EMA13 harus kembali di bawah EMA21 sebelum entry SHORT."
            )

        if contradiction:
            return _no_signal(
                f"Gate T0→T1: {wyckoff_phase} ({tf0.upper()}) tidak selaras dengan {trend_dir} ({tf1.upper()})",
                gate_explanation,
                "T1 Trend",
            )

        # Determine trade direction from Wyckoff + trend combo
        if wyckoff_phase in ("Accumulation", "Mark Up"):
            trade_direction = "uptrend"
        elif wyckoff_phase in ("Distribution", "Mark Down"):
            trade_direction = "downtrend"
        else:
            trade_direction = trend_dir  # Sideways: follow T1 trend

        # ── T2: Support/Resistance ─────────────────────────────────────────────
        tf2 = tfs["t2"]
        _, h2, l2, c2, _ = _parse(klines[tf2])
        sr_data = detect_support_resistance(h2, l2, c2, lookback_days=30)
        if not sr_data:
            layers.append(TALayer(name="T2 S/R Zones", timeframe=tf2.upper(), status="failed",
                                  detail="No S/R zones found"))
            return _no_signal(
                "T2: No support/resistance zones detected",
                f"Tidak ada zona S/R yang jelas pada {tf2.upper()}. "
                "Koin ini mungkin baru listing atau kurang data historis. "
                "Tunggu beberapa minggu hingga pola S/R terbentuk.",
                "T2 S/R Zones",
            )
        sup_txt = (f"Support ${sr_data.strongest_support.midpoint:.6g} ({sr_data.strongest_support.num_bounces}x)"
                   if sr_data.strongest_support else "No support")
        res_txt = (f"Resist ${sr_data.strongest_resistance.midpoint:.6g} ({sr_data.strongest_resistance.num_bounces}x)"
                   if sr_data.strongest_resistance else "No resistance")
        layers.append(TALayer(
            name="T2 S/R Zones", timeframe=tf2.upper(), status="passed",
            detail=f"{sup_txt} | {res_txt}",
        ))

        # ── T3: Pattern ────────────────────────────────────────────────────────
        tf3 = tfs["t3"]
        _, h3, l3, _, _ = _parse(klines[tf3])
        pattern = detect_patterns(h3, l3)
        structure = analyze_market_structure(h3, l3)
        bias = structure.structure.value if structure else "Unknown"
        hh = structure.hh_count if structure else 0
        ll_count = structure.ll_count if structure else 0

        if pattern:
            pat_name = pattern.pattern_type.value
            breakout_dir = pattern.potential_breakout
            str_pct = f" ({pattern.formation_strength:.0f}%)"

            # Gate T3: pattern must confirm intended trade direction
            is_long = trade_direction == "uptrend"
            pattern_ok = (
                (is_long and breakout_dir in ("up", "bidirectional")) or
                (not is_long and breakout_dir in ("down", "bidirectional"))
            )
            if not pattern_ok:
                layers.append(TALayer(
                    name="T3 Pattern", timeframe=tf3.upper(), status="gate_failed",
                    signal=f"{pat_name} → {breakout_dir}",
                    detail=f"Bias: {bias} | HH:{hh} LL:{ll_count}{str_pct}",
                ))
                expected = "LONG (up)" if is_long else "SHORT (down)"
                explanation = (
                    f"T3 mendeteksi pola {pat_name} ({tf3.upper()}) dengan potensi breakout ke {breakout_dir.upper()}. "
                    f"Ini BERLAWANAN dengan arah trade yang diharapkan ({expected}). "
                    f"Pola {pat_name} ini memberi sinyal bahwa harga kemungkinan akan bergerak {breakout_dir}, "
                    "bukan arah yang kita harapkan. "
                    f"Tunggu hingga pola ini selesai/invalid atau cari entry di arah {breakout_dir}."
                )
                return _no_signal(
                    f"Gate T3: {pat_name} breakout {breakout_dir} berlawanan dengan {trade_direction}",
                    explanation,
                    "T3 Pattern",
                )
            layers.append(TALayer(
                name="T3 Pattern", timeframe=tf3.upper(), status="passed",
                signal=f"{pat_name} → {breakout_dir}",
                detail=f"Bias: {bias} | HH:{hh} LL:{ll_count}{str_pct}",
            ))
        else:
            layers.append(TALayer(
                name="T3 Pattern", timeframe=tf3.upper(), status="skipped",
                signal="No clear pattern",
                detail=f"Bias: {bias} | HH:{hh} LL:{ll_count} — No pattern, using structure bias",
            ))

        # ── T4: Trigger ────────────────────────────────────────────────────────
        tf4 = tfs["t4"]
        o4, h4, l4, c4, v4 = _parse(klines[tf4])
        trigger = detect_trigger(o4, h4, l4, c4, v4)

        if not trigger:
            layers.append(TALayer(name="T4 Trigger", timeframe=tf4.upper(), status="gate_failed",
                                  detail="No trigger signal on this candle"))
            return _no_signal(
                "T4: Tidak ada trigger signal",
                f"Semua layer T0-T3 lolos, tapi belum ada sinyal entry di {tf4.upper()}. "
                "Ini artinya setup sudah bagus tapi timing belum tepat. "
                "Yang perlu diperhatikan: tunggu munculnya candlestick reversal (Hammer, Engulfing, Doji) "
                "atau Stochastic oversold/overbought di timeframe ini. "
                "Setup ini masih valid — cek ulang dalam beberapa jam.",
                "T4 Trigger",
            )

        # Gate T4 volume
        if not validate_no_dry_volume(v4):
            layers.append(TALayer(
                name="T4 Trigger", timeframe=tf4.upper(), status="gate_failed",
                signal=trigger.direction.upper(),
                detail=f"Volume sangat rendah (< 30% rata-rata) — sinyal tidak valid",
            ))
            return _no_signal(
                "Gate T4: Volume terlalu rendah",
                f"Trigger ada ({trigger.candlestick_pattern}) di {tf4.upper()}, tapi volume < 30% dari rata-rata. "
                "Sinyal tanpa volume = false signal. "
                "Tunggu konfirmasi dengan volume normal sebelum entry.",
                "T4 Trigger",
            )

        # Gate T4: trigger direction harus sesuai trade_direction
        trigger_dir = trigger.direction.lower()
        expected_dir = "long" if trade_direction == "uptrend" else "short"
        if trigger_dir != expected_dir and trade_direction != "sideways":
            candle_name = trigger.candlestick_pattern or "sinyal"
            layers.append(TALayer(
                name="T4 Trigger", timeframe=tf4.upper(), status="gate_failed",
                signal=trigger.direction.upper(),
                detail=f"Candle: {candle_name} | arah {trigger.direction} ≠ expected {expected_dir}",
            ))
            return _no_signal(
                f"Gate T4: Trigger {trigger.direction.upper()} berlawanan dengan trade direction {expected_dir.upper()}",
                f"T4 mendeteksi {candle_name} ({trigger.direction.upper()}) di {tf4.upper()}, "
                f"tapi berdasarkan T0-T1, kita mencari setup {expected_dir.upper()}. "
                "Ini bisa berarti: harga sedang koreksi kecil sebelum lanjut, atau momentum berbalik. "
                f"Tunggu candle {expected_dir} yang konfirmasi arah utama.",
                "T4 Trigger",
            )

        candle = trigger.candlestick_pattern or "N/A"
        stoch = trigger.stochastic_signal or "N/A"
        layers.append(TALayer(
            name="T4 Trigger", timeframe=tf4.upper(), status="passed",
            signal=trigger.direction.upper(),
            detail=f"Candle: {candle} | Stoch: {stoch} | Conf: {trigger.confidence:.0f}%",
        ))

        # ── T5: Order Flow ─────────────────────────────────────────────────────
        from app.services.ta_engine import analyze_order_flow
        order_flow = analyze_order_flow(o4, h4, l4, c4, v4)
        if order_flow:
            of_signal_map = {
                "strong_buy": "STRONG BUY 🔥", "buy": "BUY",
                "strong_sell": "STRONG SELL 🔥", "sell": "SELL", "neutral": "NEUTRAL",
            }
            of_status = "passed" if order_flow.direction in ("bullish", "bearish") else "skipped"
            # Gate: order flow direction should align with trade direction
            of_aligned = (
                (trade_direction == "uptrend" and order_flow.direction == "bullish") or
                (trade_direction == "downtrend" and order_flow.direction == "bearish") or
                order_flow.direction == "neutral"
            )
            if not of_aligned:
                of_status = "gate_failed"
            layers.append(TALayer(
                name="T5 Order Flow", timeframe=tf4.upper(), status=of_status,
                signal=of_signal_map.get(order_flow.signal, order_flow.signal),
                detail=order_flow.description,
            ))
            # If T5 gate fails, still allow signal but reduce confidence
            if not of_aligned:
                # Don't block signal from T5, just warn
                pass
        else:
            layers.append(TALayer(
                name="T5 Order Flow", timeframe=tf4.upper(), status="skipped",
                detail="Insufficient data for order flow",
            ))

        # ── Risk Management ────────────────────────────────────────────────────
        current_price = c4[-1]
        direction_str = "long" if trade_direction == "uptrend" else "short"
        direction_out = "LONG" if direction_str == "long" else "SHORT"

        support_level = sr_data.strongest_support.midpoint if sr_data.strongest_support else None
        resistance_level = sr_data.strongest_resistance.midpoint if sr_data.strongest_resistance else None
        sr_zone = (
            (sr_data.strongest_support.price_low, sr_data.strongest_support.price_high)
            if sr_data.strongest_support else None
        )

        stop_loss_price = calculate_stop_loss(
            entry_price=current_price,
            direction=direction_str,
            support_level=support_level if direction_str == "long" else resistance_level,
            resistance_level=resistance_level if direction_str == "short" else support_level,
            sr_zone=sr_zone,
        )
        risk_amount = abs(current_price - stop_loss_price)
        take_profit_price = calculate_take_profit(current_price, direction_str, risk_amount, 3.0)
        risk_calc = calculate_risk_metrics(current_price, stop_loss_price, take_profit_price, direction_str)

        if not risk_calc.is_valid:
            return _no_signal(
                f"Gate Risk: R:R {risk_calc.risk_reward_ratio:.1f} < 1:3 minimum",
                f"Semua layer lolos! Tapi R:R hanya 1:{risk_calc.risk_reward_ratio:.1f}. "
                "Sistem membutuhkan minimum 1:3 (reward = 3x risiko). "
                f"Entry: ${current_price:.4g} | SL: ${stop_loss_price:.4g} | TP: ${take_profit_price:.4g}. "
                "Coba style dengan timeframe lebih besar untuk SL yang lebih jauh dari noise.",
                "T4 Trigger",
            )

        # ── Build multi-TP ─────────────────────────────────────────────────────
        res_prices: list[float] = []
        sup_prices: list[float] = []
        for zone in getattr(sr_data, "resistance_zones", []):
            res_prices.append(float(zone.midpoint))
        for zone in getattr(sr_data, "support_zones", []):
            sup_prices.append(float(zone.midpoint))
        if sr_data.strongest_resistance:
            res_prices.insert(0, float(sr_data.strongest_resistance.midpoint))
        if sr_data.strongest_support:
            sup_prices.insert(0, float(sr_data.strongest_support.midpoint))

        take_profits = _calc_multi_tp(current_price, stop_loss_price, direction_out, res_prices, sup_prices)
        sl_basis = "Below strongest support zone" if direction_out == "LONG" else "Above strongest resistance zone"
        best_tp = take_profits[1] if len(take_profits) >= 2 else (take_profits[0] if take_profits else None)

        # Confidence: weighted average of layer signals (T0-T5)
        of_score = 0.0
        if order_flow:
            of_map = {"strong_buy": 90, "buy": 70, "neutral": 50, "sell": 30, "strong_sell": 10}
            of_raw = of_map.get(order_flow.signal, 50)
            if trade_direction == "downtrend":
                of_raw = 100 - of_raw  # invert for shorts
            of_score = of_raw

        confidence = min(99.0, (
            wyckoff.strength * 0.15 +
            trigger.confidence * 0.30 +
            (pattern.formation_strength if pattern else 50) * 0.15 +
            risk_calc.risk_reward_ratio * 5 * 0.15 +
            of_score * 0.25
        ))

        return QuickAnalysisResponse(
            symbol=sym, style=style, timeframes=tfs,
            direction=direction_out,
            entry=round(current_price, 8),
            stop_loss=round(stop_loss_price, 8),
            sl_basis=sl_basis,
            take_profits=take_profits,
            risk_reward=best_tp.rr if best_tp else f"1:{risk_calc.risk_reward_ratio:.1f}",
            confidence=round(confidence, 1),
            skip_reason=None,
            stop_explanation=None,
            layers=layers,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analysis_failed", symbol=sym, style=style, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
