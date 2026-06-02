"""
Trigger analyzer module (T4).

Combines candlestick pattern + Stochastic + volume confirmation for entry signal.
"""

from typing import List, Optional
from dataclasses import dataclass
from app.services.ta_engine.candlestick import detect_candlestick_pattern, CandlePattern
from app.services.ta_engine.stochastic import detect_stochastic_signal, get_latest_stochastic


@dataclass
class TriggerSignal:
    """Represents an entry trigger signal."""

    direction: str  # "buy" or "sell"
    confidence: float  # 0-100, based on confirmation count
    candlestick_pattern: Optional[str]  # Pattern name or None
    stochastic_signal: Optional[str]  # "buy", "sell", or None
    has_volume_spike: bool  # True if volume is above average
    taker_buy_pressure: Optional[float]  # 0-1, taker_buy / total_vol
    reasoning: str  # Explanation of the signal
    candle_index: int  # Index of the trigger candle


def _calculate_avg_volume(volumes: List[float], lookback: int = 7) -> float:
    """Calculate average volume over last N candles."""
    if not volumes or lookback == 0:
        return 0.0

    recent_volumes = volumes[-lookback:]
    return sum(recent_volumes) / len(recent_volumes)


def detect_trigger(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    taker_buy_volumes: Optional[List[float]] = None,
) -> Optional[TriggerSignal]:
    """
    Detect entry trigger signal.

    Three confirmations needed:
    1. Candlestick pattern (bullish engulfing, hammer, morning star, rejection)
    2. Stochastic signal (buy: oversold + cross up, sell: overbought + cross down)
    3. Volume spike (current vol > avg vol * 1.5)

    Note: Taker buy pressure only useful if we have that data from Binance.

    Returns:
        TriggerSignal if all 3 confirmations are present, None otherwise
    """
    if len(closes) < 3:
        return None

    # Check candlestick pattern
    candle_pattern = detect_candlestick_pattern(opens, highs, lows, closes)

    # Check stochastic signal
    stochastic_signal = detect_stochastic_signal(highs, lows, closes)

    # Check volume spike
    avg_volume = _calculate_avg_volume(volumes)
    current_volume = volumes[-1] if volumes else 0
    has_volume_spike = current_volume > avg_volume * 1.5 if avg_volume > 0 else False

    # Determine direction from candle pattern
    direction = None
    if candle_pattern in [CandlePattern.BULLISH_ENGULFING, CandlePattern.HAMMER, CandlePattern.MORNING_STAR]:
        direction = "buy"
    elif candle_pattern in [CandlePattern.BEARISH_ENGULFING, CandlePattern.SHOOTING_STAR, CandlePattern.EVENING_STAR]:
        direction = "sell"
    elif candle_pattern == CandlePattern.REJECTION_CANDLE:
        # Rejection can be bullish or bearish, check with stochastic
        if stochastic_signal == "buy":
            direction = "buy"
        elif stochastic_signal == "sell":
            direction = "sell"

    # If no direction from candle, use stochastic
    if direction is None:
        direction = stochastic_signal

    if direction is None:
        return None  # No clear signal

    # Calculate taker buy pressure
    taker_buy_pressure = None
    if taker_buy_volumes and len(taker_buy_volumes) > 0:
        total_vol = volumes[-1] if volumes else 0
        taker_vol = taker_buy_volumes[-1] if taker_buy_volumes else 0
        if total_vol > 0:
            taker_buy_pressure = taker_vol / total_vol

    # Count confirmations
    confirmations = 0
    confirmation_reasons = []

    if candle_pattern and candle_pattern != CandlePattern.NONE:
        confirmations += 1
        confirmation_reasons.append(f"Candlestick: {candle_pattern.value}")

    if stochastic_signal:
        confirmations += 1
        confirmation_reasons.append(f"Stochastic: {stochastic_signal.upper()}")

    if has_volume_spike:
        confirmations += 1
        vol_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        confirmation_reasons.append(f"Volume spike: {vol_ratio:.1f}x")

    # Confidence based on confirmation count
    confidence = (confirmations / 3.0) * 100  # 0-100

    # Build reasoning
    reasoning = f"{direction.upper()} signal from: {', '.join(confirmation_reasons)}"

    # Check for taker buy pressure
    if taker_buy_pressure is not None:
        if direction == "buy" and taker_buy_pressure > 0.6:
            reasoning += f" (strong buying pressure {taker_buy_pressure:.1%})"
            confidence = min(100.0, confidence + 10)
        elif direction == "sell" and taker_buy_pressure < 0.4:
            reasoning += f" (strong selling pressure {1-taker_buy_pressure:.1%})"
            confidence = min(100.0, confidence + 10)

    return TriggerSignal(
        direction=direction,
        confidence=confidence,
        candlestick_pattern=candle_pattern.value if candle_pattern else None,
        stochastic_signal=stochastic_signal,
        has_volume_spike=has_volume_spike,
        taker_buy_pressure=taker_buy_pressure,
        reasoning=reasoning,
        candle_index=len(closes) - 1,
    )


def validate_no_dry_volume(volumes: List[float], lookback: int = 3) -> bool:
    """
    Validate that there's no dry volume (very low volume that prevents entry).

    Dry volume = when volume is suspiciously low (< 30% of average).
    This is a safety check to avoid entering on low-liquidity candles.

    Returns:
        True if volume is healthy, False if dry
    """
    if not volumes or len(volumes) < lookback + 1:
        return True  # Can't validate, assume OK

    avg_volume = _calculate_avg_volume(volumes, lookback)
    current_volume = volumes[-1]

    # If current volume is less than 30% of average, it's dry
    if avg_volume > 0 and current_volume < avg_volume * 0.3:
        return False

    return True
