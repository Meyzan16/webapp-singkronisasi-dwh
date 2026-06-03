"""
24H Scanner Agent — detects coins BEFORE a big move happens.

Early-warning signals:
1. Volatility Squeeze   — BB tight, price coiling before explosion
2. Volume Accumulation  — volume rising while price is flat/down (smart money buying)
3. Breakout Zone        — price within 1-2% of key resistance
4. Momentum Divergence  — higher lows on volume while price flat (hidden bullish)
5. Order Flow Shift     — buy pressure increasing over last 5 candles
6. Low Float Spike      — volume suddenly 2-3x avg without major price move yet

Returns coins scored by "probability of big move soon" NOT "already moved".
"""

import asyncio
import math
import time

import httpx
import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.binance_urls import fapi

router = APIRouter(tags=["scanner"])
logger = structlog.get_logger(__name__)

_cache: dict[str, dict] = {}
CACHE_TTL = 300  # 5 min


# ── Schemas ────────────────────────────────────────────────────────────────────

class ScanSignal(BaseModel):
    symbol: str
    direction: str          # "LONG" | "SHORT"
    probability: float      # 0–100 — likelihood of imminent big move
    current_price: float
    change_24h: float
    volume_ratio: float     # current volume vs 20-period avg
    signals: list[str]      # list of triggered early-warning signals
    key_level: float | None  # breakout level to watch
    stop_loss: float
    take_profit: float
    risk_reward: str
    alert_type: str         # "squeeze" | "accumulation" | "breakout" | "reversal"


class ScannerResponse(BaseModel):
    results: list[ScanSignal]
    scanned: int
    style: str
    generated_at: int


# ── Math helpers ───────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    return 100 - (100 / (1 + ag / al)) if al > 0 else 100.0


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    trs = []
    for i in range(1, min(period + 1, len(closes))):
        tr = max(highs[-i] - lows[-i],
                 abs(highs[-i] - closes[-i - 1]),
                 abs(lows[-i] - closes[-i - 1]))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else closes[-1] * 0.02


# ── Core scoring ──────────────────────────────────────────────────────────────

def _analyze(
    symbol: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    change_24h: float,
) -> ScanSignal | None:
    if len(closes) < 30:
        return None

    price = closes[-1]
    signals: list[str] = []
    score = 0.0
    alert_type = "accumulation"
    direction = "LONG"

    # ── 1. Volatility Squeeze (Bollinger Band) ─────────────────────────────────
    # Low BB width = coiling = potential explosion soon
    bb_period = 20
    bb_closes = closes[-bb_period:]
    bb_mid = sum(bb_closes) / bb_period
    bb_std = _stddev(bb_closes)
    bb_width = (bb_std * 4) / bb_mid if bb_mid > 0 else 1.0  # (2σ range) / price

    if bb_width < 0.04:  # < 4% width = very tight squeeze
        score += 25
        signals.append(f"🔵 BB Squeeze {bb_width*100:.1f}% — ready to explode")
        alert_type = "squeeze"
    elif bb_width < 0.07:
        score += 12
        signals.append(f"BB tightening {bb_width*100:.1f}%")

    # ── 2. Volume Accumulation — rising volume, price flat/down ───────────────
    # Smart money quietly buying before the move
    avg_vol_20 = sum(volumes[-21:-1]) / 20
    last_vol = volumes[-1]
    vol_ratio = last_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

    # Volume trend over last 5 candles
    vol5 = volumes[-5:]
    vol_slope = (vol5[-1] - vol5[0]) / vol5[0] if vol5[0] > 0 else 0
    price_slope = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0

    if vol_slope > 0.3 and abs(price_slope) < 0.05:
        # Volume rising 30%+ but price flat — accumulation
        score += 22
        signals.append(f"📦 Accumulation: vol +{vol_slope*100:.0f}% price flat")
        alert_type = "accumulation"
    elif vol_slope > 0.15 and price_slope < 0:
        # Volume rising while price drops = hidden strength
        score += 18
        signals.append(f"💪 Vol rising on dip (smart money)")
    elif vol_ratio > 1.5 and abs(price_slope) < 0.03:
        score += 12
        signals.append(f"Vol {vol_ratio:.1f}x avg with flat price")

    # ── 3. Near Key Resistance (Breakout Zone) ─────────────────────────────────
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    range_size = recent_high - recent_low

    dist_to_high = (recent_high - price) / price
    dist_to_low = (price - recent_low) / price

    if 0 < dist_to_high < 0.02:  # within 2% of 20-period high
        score += 20
        signals.append(f"🎯 Near breakout: ${recent_high:.4g} resistance")
        alert_type = "breakout"
        direction = "LONG"
    elif 0 < dist_to_low < 0.02:  # within 2% of 20-period low (potential reversal)
        score += 15
        signals.append(f"🎯 Near support: ${recent_low:.4g} — reversal zone")
        alert_type = "reversal"

    # ── 4. RSI Coiling in 40–60 zone (neutral = energy building) ─────────────
    rsi = _rsi(closes)
    if 35 <= rsi <= 50:
        score += 12
        signals.append(f"RSI {rsi:.0f} — building energy (oversold recovery)")
        direction = "LONG"
    elif 50 <= rsi <= 65:
        score += 8
        signals.append(f"RSI {rsi:.0f} — momentum building")
    elif rsi < 30:
        score += 15
        signals.append(f"RSI {rsi:.0f} oversold — reversal imminent")
        direction = "LONG"
        alert_type = "reversal"
    elif rsi > 75:
        score -= 10  # already extended, less likely to break out higher

    # ── 5. EMA Compression (EMAs converging = breakout coming) ────────────────
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else ema21
    ema_spread = abs(ema9 - ema21) / price if price > 0 else 0

    if ema_spread < 0.005:  # EMAs within 0.5% = compressed
        score += 15
        signals.append(f"⚡ EMA compression (9/21 gap {ema_spread*100:.2f}%)")
        alert_type = "squeeze"
    elif ema9 > ema21 and ema21 > ema50:
        score += 8
        signals.append("EMA bullish alignment (9>21>50)")
        direction = "LONG"
    elif ema9 < ema21 and ema21 < ema50:
        score += 8
        signals.append("EMA bearish alignment")
        direction = "SHORT"

    # ── 6. Buy pressure shift (last 5 candles more bullish than prior 5) ──────
    def _bull_vol_pct(o_list, c_list, v_list):
        bull = sum(v for o, c, v in zip(o_list, c_list, v_list) if c >= o)
        total = sum(v_list) or 1
        return bull / total

    if len(opens) >= 10:
        bp_recent = _bull_vol_pct(opens[-5:], closes[-5:], volumes[-5:])
        bp_prior  = _bull_vol_pct(opens[-10:-5], closes[-10:-5], volumes[-10:-5])
        if bp_recent > bp_prior + 0.15:
            score += 15
            signals.append(f"🟢 Buy pressure rising ({bp_recent*100:.0f}% vs {bp_prior*100:.0f}%)")
        elif bp_recent < bp_prior - 0.15:
            score += 10
            signals.append(f"🔴 Sell pressure rising ({bp_recent*100:.0f}%)")
            direction = "SHORT"

    # ── 7. Candle body shrinking (indecision = breakout coming) ───────────────
    bodies = [abs(c - o) for o, c in zip(opens[-6:], closes[-6:])]
    if len(bodies) >= 4:
        body_slope = (bodies[-1] - bodies[0]) / (bodies[0] + 1e-10)
        if body_slope < -0.5:  # bodies getting smaller = energy compressing
            score += 10
            signals.append("Candle bodies shrinking (coiling)")

    # ── 8. Already pumped penalty — avoid "late" entries ─────────────────────
    # If already up big in 24h, less potential remaining
    if abs(change_24h) > 20:
        score -= 20
        signals.append(f"⚠️ Already moved {change_24h:+.1f}% (late)")
    elif abs(change_24h) > 10:
        score -= 8

    # Not enough signals
    if score < 30 or len(signals) < 2:
        return None

    # ── Direction from preponderance of signals ────────────────────────────────
    long_signals = sum(1 for s in signals if any(k in s for k in ["bullish", "LONG", "oversold", "Buy", "rising"]))
    short_signals = sum(1 for s in signals if any(k in s for k in ["bearish", "SHORT", "Sell", "sell pressure"]))
    if short_signals > long_signals:
        direction = "SHORT"

    # ── SL / TP ────────────────────────────────────────────────────────────────
    atr = _atr(highs, lows, closes)
    if direction == "LONG":
        sl = price - atr * 1.5
        tp = price + atr * 4.5
        key_level = recent_high
    else:
        sl = price + atr * 1.5
        tp = price - atr * 4.5
        key_level = recent_low

    risk = abs(price - sl)
    reward = abs(tp - price)
    rr = f"1:{reward/risk:.1f}" if risk > 0 else "1:3.0"

    return ScanSignal(
        symbol=symbol,
        direction=direction,
        probability=round(min(score, 99), 1),
        current_price=round(price, 8),
        change_24h=round(change_24h, 2),
        volume_ratio=round(vol_ratio, 2),
        signals=signals[:4],  # top 4 signals
        key_level=round(key_level, 8),
        stop_loss=round(sl, 8),
        take_profit=round(tp, 8),
        risk_reward=rr,
        alert_type=alert_type,
    )


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list:
    try:
        r = await client.get(fapi(f"/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"))
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list) and d:
                return d
    except Exception:
        pass
    return []


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/scanner/scan", response_model=ScannerResponse)
async def scan_market(
    style: str = Query(default="4h", description="Candle timeframe: 15m | 1h | 4h | 1d"),
    limit: int = Query(default=100, description="Candles to analyze"),
) -> ScannerResponse:
    """
    Scan USDT futures for early-warning breakout setups.
    Detects coins about to move BEFORE the big candle.
    """
    cache_key = f"{style}_{limit}"
    now = int(time.time())
    if cache_key in _cache and now - _cache[cache_key].get("ts", 0) < CACHE_TTL:
        return _cache[cache_key]["data"]

    # Step 1: get all tickers, pick top 100 by volume (active coins)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(fapi("/fapi/v1/ticker/24hr"))
        if r.status_code != 200:
            return ScannerResponse(results=[], scanned=0, style=style, generated_at=now)
        tickers = [t for t in r.json() if str(t.get("symbol", "")).endswith("USDT")]

    # Sort by quote volume (most active = best signals)
    tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    candidates = tickers[:100]

    # Step 2: fetch klines for all candidates concurrently
    async with httpx.AsyncClient(timeout=25) as client:
        kline_results = await asyncio.gather(
            *[_klines(client, t["symbol"], style, limit) for t in candidates],
            return_exceptions=True,
        )

    # Step 3: score each
    results: list[ScanSignal] = []
    for ticker, kdata in zip(candidates, kline_results):
        if isinstance(kdata, Exception) or not kdata:
            continue
        try:
            opens  = [float(k[1]) for k in kdata]
            highs  = [float(k[2]) for k in kdata]
            lows   = [float(k[3]) for k in kdata]
            closes = [float(k[4]) for k in kdata]
            vols   = [float(k[5]) for k in kdata]
            change = float(ticker.get("priceChangePercent", 0))

            sig = _analyze(ticker["symbol"], opens, highs, lows, closes, vols, change)
            if sig:
                results.append(sig)
        except Exception:
            continue

    # Sort by probability, top 25
    results.sort(key=lambda r: r.probability, reverse=True)
    results = results[:25]

    response = ScannerResponse(
        results=results,
        scanned=len(candidates),
        style=style,
        generated_at=now,
    )
    _cache[cache_key] = {"data": response, "ts": now}
    logger.info("scanner_done", found=len(results), scanned=len(candidates), style=style)
    return response
