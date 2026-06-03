"""
24H Scanner Agent — scans all USDT futures for high-probability setups.

Scoring criteria:
- Volume spike vs 20-period avg
- Price momentum (RSI-like calculation)
- EMA crossover status
- Candle pattern
- Order flow (CVD direction)

Returns top recommendations with BUY/SELL direction + probability score.
"""

import asyncio
import time
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.binance_urls import fapi

router = APIRouter(tags=["scanner"])
logger = structlog.get_logger(__name__)

# Cache so we don't re-scan on every request
_cache: dict = {"data": None, "ts": 0}
CACHE_TTL = 300  # 5 minutes


class ScannerResult(BaseModel):
    symbol: str
    direction: str        # "LONG" | "SHORT"
    score: float          # 0–100 probability score
    change_24h: float
    volume_ratio: float   # current vol / avg vol
    momentum: str         # "strong_up" | "up" | "neutral" | "down" | "strong_down"
    trigger: str          # what caused the alert
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: str


class ScannerResponse(BaseModel):
    results: list[ScannerResult]
    scanned: int
    generated_at: int


def _simple_rsi(closes: list[float], period: int = 14) -> float:
    """Simplified RSI."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-period + i] - closes[-period + i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _ema(values: list[float], period: int) -> float:
    """Latest EMA value."""
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _score_symbol(
    symbol: str,
    closes: list[float],
    volumes: list[float],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    change_24h: float,
) -> Optional[ScannerResult]:
    """Score a single symbol and return result if score > threshold."""
    if len(closes) < 25:
        return None

    score = 0.0
    triggers = []
    direction = "LONG"

    last_close = closes[-1]
    last_open = opens[-1]
    last_vol = volumes[-1]
    avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else last_vol
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0

    # 1. Volume spike
    if vol_ratio > 5:
        score += 25
        triggers.append(f"Vol spike {vol_ratio:.1f}x")
    elif vol_ratio > 3:
        score += 18
        triggers.append(f"Vol surge {vol_ratio:.1f}x")
    elif vol_ratio > 2:
        score += 10
        triggers.append(f"Vol {vol_ratio:.1f}x avg")

    # 2. RSI momentum
    rsi = _simple_rsi(closes)
    if rsi < 30:
        score += 20
        direction = "LONG"
        triggers.append(f"RSI oversold {rsi:.0f}")
    elif rsi > 70:
        score += 20
        direction = "SHORT"
        triggers.append(f"RSI overbought {rsi:.0f}")
    elif 40 <= rsi <= 60:
        score += 5

    # 3. EMA trend
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else ema21

    if ema9 > ema21 > ema50:
        score += 15
        direction = "LONG"
        triggers.append("EMA9>21>50 aligned")
    elif ema9 < ema21 < ema50:
        score += 15
        direction = "SHORT"
        triggers.append("EMA9<21<50 aligned")
    elif ema9 > ema21:
        score += 8
        direction = "LONG"

    # 4. 24h momentum
    abs_change = abs(change_24h)
    if abs_change > 20:
        score += 15
        direction = "LONG" if change_24h > 0 else "SHORT"
        triggers.append(f"{'+' if change_24h > 0 else ''}{change_24h:.1f}% 24h")
    elif abs_change > 10:
        score += 8
        direction = "LONG" if change_24h > 0 else "SHORT"

    # 5. Last candle pattern
    body = abs(last_close - last_open)
    candle_range = highs[-1] - lows[-1]
    if candle_range > 0:
        body_ratio = body / candle_range
        if body_ratio > 0.7 and last_vol > avg_vol:
            if last_close > last_open:
                score += 10
                triggers.append("Strong bull candle")
                direction = "LONG"
            else:
                score += 10
                triggers.append("Strong bear candle")
                direction = "SHORT"

    # 6. Price near recent high/low breakout
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    if last_close > recent_high * 0.99 and change_24h > 0:
        score += 12
        triggers.append("Near 20-period high")
        direction = "LONG"
    elif last_close < recent_low * 1.01 and change_24h < 0:
        score += 12
        triggers.append("Near 20-period low")
        direction = "SHORT"

    if score < 20:
        return None

    # Momentum label
    if change_24h > 15:
        momentum = "strong_up"
    elif change_24h > 5:
        momentum = "up"
    elif change_24h < -15:
        momentum = "strong_down"
    elif change_24h < -5:
        momentum = "down"
    else:
        momentum = "neutral"

    # ATR-based SL/TP
    atr = sum(h - l for h, l in zip(highs[-14:], lows[-14:])) / min(14, len(highs))

    if direction == "LONG":
        sl = last_close - atr * 1.5
        tp = last_close + atr * 4.5
    else:
        sl = last_close + atr * 1.5
        tp = last_close - atr * 4.5

    risk = abs(last_close - sl)
    reward = abs(tp - last_close)
    rr = f"1:{reward/risk:.1f}" if risk > 0 else "1:3.0"

    return ScannerResult(
        symbol=symbol,
        direction=direction,
        score=round(min(score, 100), 1),
        change_24h=round(change_24h, 2),
        volume_ratio=round(vol_ratio, 2),
        momentum=momentum,
        trigger=" | ".join(triggers[:3]),
        entry=round(last_close, 8),
        stop_loss=round(sl, 8),
        take_profit=round(tp, 8),
        risk_reward=rr,
    )


async def _fetch_klines_fast(
    client: httpx.AsyncClient, symbol: str, interval: str = "1h", limit: int = 60
) -> list:
    try:
        r = await client.get(
            fapi(f"/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}")
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                return data
    except Exception:
        pass
    return []


@router.get("/scanner/scan", response_model=ScannerResponse)
async def scan_market() -> ScannerResponse:
    """Scan all USDT futures for high-probability setups. Results cached 5 min."""
    now = int(time.time())
    if _cache["data"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["data"]

    # Step 1: Get all tickers
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(fapi("/fapi/v1/ticker/24hr"))
        if r.status_code != 200:
            return ScannerResponse(results=[], scanned=0, generated_at=now)
        tickers = r.json()

    usdt_tickers = [t for t in tickers if t.get("symbol", "").endswith("USDT")]

    # Step 2: Pick top candidates by volume + absolute change
    def _priority(t: dict) -> float:
        vol = float(t.get("quoteVolume", 0))
        chg = abs(float(t.get("priceChangePercent", 0)))
        count = int(t.get("count", 0))
        return vol * 0.4 + chg * 1000 + count * 0.001

    candidates = sorted(usdt_tickers, key=_priority, reverse=True)[:80]

    # Step 3: Fetch 1H klines concurrently for top candidates
    async with httpx.AsyncClient(timeout=20) as client:
        klines_results = await asyncio.gather(
            *[_fetch_klines_fast(client, t["symbol"], "1h", 60) for t in candidates],
            return_exceptions=True,
        )

    results: list[ScannerResult] = []
    for ticker, klines in zip(candidates, klines_results):
        if isinstance(klines, Exception) or not klines:
            continue
        try:
            opens  = [float(k[1]) for k in klines]
            highs  = [float(k[2]) for k in klines]
            lows   = [float(k[3]) for k in klines]
            closes = [float(k[4]) for k in klines]
            vols   = [float(k[5]) for k in klines]
            change = float(ticker.get("priceChangePercent", 0))

            result = _score_symbol(ticker["symbol"], closes, vols, opens, highs, lows, change)
            if result:
                results.append(result)
        except Exception:
            continue

    # Sort by score desc, then keep top 20
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:20]

    response = ScannerResponse(
        results=results,
        scanned=len(candidates),
        generated_at=now,
    )
    _cache["data"] = response
    _cache["ts"] = now

    logger.info("scanner_done", found=len(results), scanned=len(candidates))
    return response
