"""
Market Regime Detection — BTC-based.

Returns one of:
  "trending_up"   — EMA9 > EMA21 > EMA50, price rising
  "trending_down" — EMA9 < EMA21 < EMA50, price falling
  "ranging"       — Price compressed inside BB, low volatility
  "volatile"      — High ATR relative to price

Used by:
  - agents/futures/weight_updater.py  (tag each closed trade with regime)
  - agents/futures/scheduler.py       (stored in paper_trade.regime at entry)
"""

import asyncio
import math
import time
from typing import Optional

import httpx
import structlog

from app.services.binance_urls import fapi

logger = structlog.get_logger(__name__)

CACHE_TTL = 30 * 60   # refresh every 30 min
_cached_regime: Optional[str]  = None
_cached_at:     Optional[float] = None


# ── Math helpers ──────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    tail = trs[-period:] if len(trs) >= period else trs
    return sum(tail) / len(tail) if tail else 0.0


def _bb_width(closes: list[float], period: int = 20) -> float:
    if len(closes) < period:
        return 1.0
    tail = closes[-period:]
    mean = sum(tail) / period
    std  = math.sqrt(sum((v - mean) ** 2 for v in tail) / period)
    return (std * 4) / mean if mean > 0 else 1.0


# ── Core detection ─────────────────────────────────────────────────────────────

def detect_from_ohlcv(
    opens:   list[float],
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
) -> str:
    """
    Classify regime from raw OHLCV data.

    Priority: volatile > trending_up > trending_down > ranging
    """
    if len(closes) < 50:
        return "ranging"

    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)
    atr   = _atr(highs, lows, closes, 14)
    price = closes[-1]
    atr_pct = atr / price * 100 if price > 0 else 0
    bbw   = _bb_width(closes)

    # Volatile: ATR > 4% or very wide BB
    if atr_pct > 4.0 or bbw > 0.08:
        return "volatile"

    # Strong trend up
    if ema9 > ema21 > ema50:
        return "trending_up"

    # Strong trend down
    if ema9 < ema21 < ema50:
        return "trending_down"

    # Default: ranging (mixed EMAs, compressed BB)
    return "ranging"


# ── Fetch BTC 4H and detect ────────────────────────────────────────────────────

async def fetch_regime() -> str:
    """
    Fetch BTC 4H candles and detect market regime.
    Returns cached value if fresh (< 30 min).
    """
    global _cached_regime, _cached_at

    if _cached_regime and _cached_at and (time.time() - _cached_at) < CACHE_TTL:
        return _cached_regime

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(fapi("/fapi/v1/klines?symbol=BTCUSDT&interval=4h&limit=100"))
        if r.status_code != 200:
            return _cached_regime or "ranging"

        klines = r.json()
        if not isinstance(klines, list) or len(klines) < 50:
            return _cached_regime or "ranging"

        opens  = [float(k[1]) for k in klines]
        highs  = [float(k[2]) for k in klines]
        lows   = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]

        regime = detect_from_ohlcv(opens, highs, lows, closes)
        _cached_regime = regime
        _cached_at     = time.time()

        logger.info("regime_detected", regime=regime)
        return regime

    except Exception as exc:
        logger.warning("regime_detection_failed", error=str(exc)[:60])
        return _cached_regime or "ranging"


def get_cached_regime() -> str:
    """Return last known regime without fetching (for sync contexts)."""
    return _cached_regime or "ranging"
