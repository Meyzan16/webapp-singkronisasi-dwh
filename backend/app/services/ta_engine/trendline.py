"""
Trendline detection module.

Detects swing points and validates trendlines for trend analysis.
"""

from typing import List, Tuple, Optional
from dataclasses import dataclass
import math


@dataclass
class SwingPoint:
    """Represents a swing point (high or low)."""
    index: int
    price: float
    is_high: bool  # True for swing high, False for swing low


@dataclass
class Trendline:
    """Represents a trendline with validation metrics."""
    is_valid: bool
    is_uptrend: bool  # True for uptrend, False for downtrend
    num_touches: int
    slope: float  # Price change per candle
    first_touch_index: int
    latest_touch_index: int
    is_broken: bool  # True if price has broken the line
    breakout_price: float  # Price at which the break occurred (if broken)


def detect_swing_points(highs: List[float], lows: List[float], min_period: int = 2) -> List[SwingPoint]:
    """
    Detect swing highs and lows in price data.

    Uses simple logic: a swing low is when a candle's low is lower than
    the previous and next candle's lows. Swing high is the opposite.

    Args:
        highs: List of high prices (oldest first)
        lows: List of low prices
        min_period: Minimum bars to look back and forward for swing detection

    Returns:
        List of SwingPoint objects sorted by index
    """
    if len(highs) < 3:
        return []

    swings = []

    # Check each candle (skip first and last min_period candles)
    for i in range(min_period, len(lows) - min_period):
        current_low = lows[i]
        current_high = highs[i]

        # Check if swing low
        prev_min = min(lows[i - min_period : i])
        next_min = min(lows[i + 1 : i + min_period + 1])

        if current_low < prev_min and current_low < next_min:
            swings.append(SwingPoint(index=i, price=current_low, is_high=False))

        # Check if swing high
        prev_max = max(highs[i - min_period : i])
        next_max = max(highs[i + 1 : i + min_period + 1])

        if current_high > prev_max and current_high > next_max:
            swings.append(SwingPoint(index=i, price=current_high, is_high=True))

    return swings


def _distance_to_line(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """
    Calculate perpendicular distance from point (x, y) to line defined by (x1, y1) and (x2, y2).
    """
    numerator = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1)
    denominator = math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)
    if denominator == 0:
        return float("inf")
    return numerator / denominator


def _count_trendline_touches(
    swing_points: List[SwingPoint], x1: int, y1: float, x2: int, y2: float, tolerance: float = 0.002
) -> Tuple[int, int, int]:
    """
    Count how many swing points touch a trendline (within tolerance).

    Args:
        swing_points: List of swing points to check
        x1, y1, x2, y2: Two points defining the trendline
        tolerance: Percentage tolerance for touch detection (default 0.2%)

    Returns:
        Tuple of (num_touches, first_touch_idx, latest_touch_idx)
    """
    touches = []

    for sp in swing_points:
        # Distance in percentage terms
        price_range = y2 - y1 if y2 > 0 else 1
        distance_pct = _distance_to_line(sp.index, sp.price, x1, y1, x2, y2) / abs(y1) if y1 != 0 else 0

        if distance_pct <= tolerance:
            touches.append(sp.index)

    if not touches:
        return 0, -1, -1

    return len(touches), touches[0], touches[-1]


def detect_trendline(
    highs: List[float], lows: List[float], is_uptrend: Optional[bool] = None
) -> Optional[Trendline]:
    """
    Detect and validate a trendline from price data.

    Args:
        highs: List of high prices
        lows: List of low prices
        is_uptrend: If None, auto-detect. If True, look for uptrend line. If False, downtrend.

    Returns:
        Trendline object if valid, None otherwise
    """
    swings = detect_swing_points(highs, lows)

    if len(swings) < 2:
        return None

    # Auto-detect trend direction if not specified
    if is_uptrend is None:
        # Simple heuristic: if latest swing is higher than first, likely uptrend
        is_uptrend = swings[-1].price > swings[0].price

    # Filter swing points by type
    if is_uptrend:
        # For uptrend, connect swing lows
        relevant_swings = [sp for sp in swings if not sp.is_high]
    else:
        # For downtrend, connect swing highs
        relevant_swings = [sp for sp in swings if sp.is_high]

    if len(relevant_swings) < 2:
        return None

    # Use first two valid swings to define the trendline
    sp1, sp2 = relevant_swings[0], relevant_swings[1]
    x1, y1, x2, y2 = sp1.index, sp1.price, sp2.index, sp2.price

    # Calculate slope and touches
    slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
    num_touches, first_touch_idx, latest_touch_idx = _count_trendline_touches(relevant_swings, x1, y1, x2, y2)

    # Trendline is valid with minimum 2 touches
    is_valid = num_touches >= 2

    # Check if price has broken the trendline (latest candle)
    is_broken = False
    breakout_price = 0.0

    if is_valid and len(highs) > 0:
        current_idx = len(highs) - 1
        # Calculate expected price at current index
        expected_price = y1 + slope * (current_idx - x1)

        if is_uptrend:
            # For uptrend, if low closes below the line, it's broken
            is_broken = lows[-1] < expected_price * 0.998  # 0.2% tolerance
            breakout_price = lows[-1] if is_broken else 0.0
        else:
            # For downtrend, if high closes above the line, it's broken
            is_broken = highs[-1] > expected_price * 1.002  # 0.2% tolerance
            breakout_price = highs[-1] if is_broken else 0.0

    return Trendline(
        is_valid=is_valid,
        is_uptrend=is_uptrend,
        num_touches=num_touches,
        slope=slope,
        first_touch_index=first_touch_idx,
        latest_touch_index=latest_touch_idx,
        is_broken=is_broken,
        breakout_price=breakout_price,
    )
