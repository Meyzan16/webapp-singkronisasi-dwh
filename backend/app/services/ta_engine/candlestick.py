"""
Candlestick pattern recognition module.

Detects entry confirmation patterns: engulfing, hammer, morning star, evening star.
"""

from typing import List, Optional
from enum import Enum


class CandlePattern(str, Enum):
    """Candlestick pattern types."""

    BULLISH_ENGULFING = "Bullish Engulfing"
    BEARISH_ENGULFING = "Bearish Engulfing"
    HAMMER = "Hammer"
    SHOOTING_STAR = "Shooting Star"
    MORNING_STAR = "Morning Star"
    EVENING_STAR = "Evening Star"
    REJECTION_CANDLE = "Rejection Candle"
    NONE = "None"


def _get_candle_direction(open_price: float, close_price: float) -> str:
    """Return 'bullish' or 'bearish' based on open/close."""
    if close_price > open_price:
        return "bullish"
    elif close_price < open_price:
        return "bearish"
    else:
        return "doji"


def _get_body_size(open_price: float, close_price: float) -> float:
    """Get absolute body size in price units."""
    return abs(close_price - open_price)


def _get_lower_wick(open_price: float, close_price: float, low_price: float) -> float:
    """Get lower wick size."""
    min_oc = min(open_price, close_price)
    return max(0, min_oc - low_price)


def _get_upper_wick(open_price: float, close_price: float, high_price: float) -> float:
    """Get upper wick size."""
    max_oc = max(open_price, close_price)
    return max(0, high_price - max_oc)


def detect_bullish_engulfing(
    prev_open: float,
    prev_close: float,
    curr_open: float,
    curr_close: float,
) -> bool:
    """
    Bullish engulfing: previous candle is bearish (close < open),
    current candle is bullish (close > open) and completely engulfs previous.
    """
    # Previous must be bearish
    if prev_close >= prev_open:
        return False

    # Current must be bullish
    if curr_close <= curr_open:
        return False

    # Current engulfs previous
    return curr_open <= prev_open and curr_close >= prev_close


def detect_bearish_engulfing(
    prev_open: float,
    prev_close: float,
    curr_open: float,
    curr_close: float,
) -> bool:
    """
    Bearish engulfing: previous candle is bullish (close > open),
    current candle is bearish (close < open) and completely engulfs previous.
    """
    # Previous must be bullish
    if prev_close <= prev_open:
        return False

    # Current must be bearish
    if curr_close >= curr_open:
        return False

    # Current engulfs previous
    return curr_open >= prev_open and curr_close <= prev_close


def detect_hammer(open_price: float, high_price: float, low_price: float, close_price: float) -> bool:
    """
    Hammer: small body near the top, long lower wick (2x body), small upper wick.
    Bullish reversal signal. Usually found at support.
    """
    body_size = _get_body_size(open_price, close_price)
    lower_wick = _get_lower_wick(open_price, close_price, low_price)
    upper_wick = _get_upper_wick(open_price, close_price, high_price)

    # Body must be small
    if body_size == 0:
        return False

    # Lower wick must be 2x+ the body
    if lower_wick < body_size * 2:
        return False

    # Upper wick must be small (< 0.5x body)
    if upper_wick > body_size * 0.5:
        return False

    # Close should be in upper half (bullish close)
    return close_price > open_price


def detect_shooting_star(open_price: float, high_price: float, low_price: float, close_price: float) -> bool:
    """
    Shooting star: small body near the bottom, long upper wick (2x body), small lower wick.
    Bearish reversal signal. Usually found at resistance.
    """
    body_size = _get_body_size(open_price, close_price)
    lower_wick = _get_lower_wick(open_price, close_price, low_price)
    upper_wick = _get_upper_wick(open_price, close_price, high_price)

    # Body must be small
    if body_size == 0:
        return False

    # Upper wick must be 2x+ the body
    if upper_wick < body_size * 2:
        return False

    # Lower wick must be small (< 0.5x body)
    if lower_wick > body_size * 0.5:
        return False

    # Close should be in lower half (bearish close)
    return close_price < open_price


def detect_morning_star(
    day1_open: float,
    day1_close: float,
    day2_open: float,
    day2_close: float,
    day2_high: float,
    day2_low: float,
    day3_open: float,
    day3_close: float,
) -> bool:
    """
    Morning star: bearish candle, small-body gap down, bullish candle closing above day1's midpoint.
    Bullish reversal signal.
    """
    # Day 1: bearish
    if day1_close >= day1_open:
        return False

    # Day 2: small body (gap down)
    day2_body = abs(day2_close - day2_open)
    day1_body = abs(day1_close - day1_open)

    if day2_body == 0 or day2_body > day1_body * 0.5:
        return False

    # Day 3: bullish, closes above day1's midpoint
    if day3_close <= day3_open:
        return False

    day1_midpoint = (day1_open + day1_close) / 2
    return day3_close > day1_midpoint


def detect_evening_star(
    day1_open: float,
    day1_close: float,
    day2_open: float,
    day2_close: float,
    day2_high: float,
    day2_low: float,
    day3_open: float,
    day3_close: float,
) -> bool:
    """
    Evening star: bullish candle, small-body gap up, bearish candle closing below day1's midpoint.
    Bearish reversal signal.
    """
    # Day 1: bullish
    if day1_close <= day1_open:
        return False

    # Day 2: small body (gap up)
    day2_body = abs(day2_close - day2_open)
    day1_body = abs(day1_close - day1_open)

    if day2_body == 0 or day2_body > day1_body * 0.5:
        return False

    # Day 3: bearish, closes below day1's midpoint
    if day3_close >= day3_open:
        return False

    day1_midpoint = (day1_open + day1_close) / 2
    return day3_close < day1_midpoint


def detect_rejection_candle(open_price: float, high_price: float, low_price: float, close_price: float) -> tuple[bool, str]:
    """
    Rejection candle: candle that tests a level but rejects it.
    - Bullish rejection: strong lower wick, close in upper half
    - Bearish rejection: strong upper wick, close in lower half

    Returns:
        (is_rejection, direction) where direction is "bullish" or "bearish"
    """
    body_size = _get_body_size(open_price, close_price)
    lower_wick = _get_lower_wick(open_price, close_price, low_price)
    upper_wick = _get_upper_wick(open_price, close_price, high_price)

    # Must have clear directional bias
    min_oc = min(open_price, close_price)
    max_oc = max(open_price, close_price)

    # Bullish rejection: long lower wick, close in upper 60%
    if lower_wick > body_size * 1.5 and close_price > (low_price + (high_price - low_price) * 0.4):
        return True, "bullish"

    # Bearish rejection: long upper wick, close in lower 40%
    if upper_wick > body_size * 1.5 and close_price < (low_price + (high_price - low_price) * 0.6):
        return True, "bearish"

    return False, "none"


def detect_candlestick_pattern(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
) -> Optional[CandlePattern]:
    """
    Detect candlestick patterns at the current candle (last in list).

    Checks (in order):
    1. Three-candle patterns (morning star, evening star)
    2. Two-candle patterns (engulfing)
    3. Single-candle patterns (hammer, shooting star, rejection)

    Returns the first matching pattern, or None.
    """
    if len(closes) < 3:
        return None

    # Check three-candle patterns
    if len(closes) >= 3:
        morning = detect_morning_star(
            opens[-3], closes[-3],
            opens[-2], closes[-2], highs[-2], lows[-2],
            opens[-1], closes[-1],
        )
        if morning:
            return CandlePattern.MORNING_STAR

        evening = detect_evening_star(
            opens[-3], closes[-3],
            opens[-2], closes[-2], highs[-2], lows[-2],
            opens[-1], closes[-1],
        )
        if evening:
            return CandlePattern.EVENING_STAR

    # Check two-candle patterns (engulfing)
    if len(closes) >= 2:
        bullish_eng = detect_bullish_engulfing(opens[-2], closes[-2], opens[-1], closes[-1])
        if bullish_eng:
            return CandlePattern.BULLISH_ENGULFING

        bearish_eng = detect_bearish_engulfing(opens[-2], closes[-2], opens[-1], closes[-1])
        if bearish_eng:
            return CandlePattern.BEARISH_ENGULFING

    # Check single-candle patterns
    hammer = detect_hammer(opens[-1], highs[-1], lows[-1], closes[-1])
    if hammer:
        return CandlePattern.HAMMER

    shooting = detect_shooting_star(opens[-1], highs[-1], lows[-1], closes[-1])
    if shooting:
        return CandlePattern.SHOOTING_STAR

    is_rejection, direction = detect_rejection_candle(opens[-1], highs[-1], lows[-1], closes[-1])
    if is_rejection:
        return CandlePattern.REJECTION_CANDLE

    return None
