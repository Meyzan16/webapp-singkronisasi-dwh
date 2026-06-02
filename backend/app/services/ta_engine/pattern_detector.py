"""
Pattern detection module (T3).

Detects chart patterns and market structure (HH/HL/LH/LL, CHoCH, BOS).
"""

from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


class PatternType(str, Enum):
    """Types of chart patterns."""

    DOUBLE_BOTTOM = "Double Bottom"
    DOUBLE_TOP = "Double Top"
    HEAD_SHOULDERS = "Head & Shoulders"
    INVERSE_HEAD_SHOULDERS = "Inverse H&S"
    ASCENDING_WEDGE = "Ascending Wedge"
    DESCENDING_WEDGE = "Descending Wedge"
    BULL_FLAG = "Bull Flag"
    BEAR_FLAG = "Bear Flag"
    ASCENDING_TRIANGLE = "Ascending Triangle"
    DESCENDING_TRIANGLE = "Descending Triangle"
    SYMMETRIC_TRIANGLE = "Symmetric Triangle"
    NONE = "None"


class MarketStructure(str, Enum):
    """Market structure states."""

    BULLISH = "Bullish"  # HH + HL
    BEARISH = "Bearish"  # LH + LL
    TRANSITIONAL = "Transitional"  # Formation of new structure


@dataclass
class SwingStructure:
    """Represents swing highs and lows for structure analysis."""

    index: int
    price: float
    is_high: bool  # True = swing high, False = swing low


@dataclass
class PatternDetection:
    """Represents detected pattern."""

    pattern_type: PatternType
    start_index: int
    end_index: int
    formation_strength: float  # 0-100, based on pattern clarity
    potential_breakout: str  # "up" or "down" or "bidirectional"
    confirmation_needed: bool  # True if awaiting breakout confirmation


@dataclass
class MarketStructureAnalysis:
    """Market structure with recent swings and bias."""

    structure: MarketStructure
    recent_high: float
    recent_low: float
    hh_count: int  # Higher Highs in current trend
    ll_count: int  # Lower Lows in current trend
    has_choch: bool  # Change of Character detected
    has_bos: bool  # Break of Structure detected
    breakout_level: Optional[float]  # Level that, if broken, confirms BOS/CHoCH
    bias_strength: float  # 0-100, confidence in current bias


def _find_swing_points(highs: List[float], lows: List[float], lookback: int = 10) -> List[SwingStructure]:
    """
    Find recent swing highs and lows.

    lookback: how many candles back to scan.
    """
    swings = []
    recent_data_start = max(0, len(highs) - lookback)

    for i in range(recent_data_start + 1, len(highs) - 1):
        # Swing high: high > adjacent highs
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swings.append(SwingStructure(index=i, price=highs[i], is_high=True))

        # Swing low: low < adjacent lows
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swings.append(SwingStructure(index=i, price=lows[i], is_high=False))

    # Sort by index
    swings.sort(key=lambda s: s.index)
    return swings


def _detect_double_pattern(highs: List[float], lows: List[float], is_bottom: bool = True) -> Optional[PatternDetection]:
    """
    Detect double bottom or double top patterns.

    Double bottom: two lows approximately at same price, with intermediate high.
    Double top: two highs approximately at same price, with intermediate low.
    """
    lookback = 30
    recent_data = highs[-lookback:] if is_bottom is False else lows[-lookback:]
    data_to_check = lows[-lookback:] if is_bottom else highs[-lookback:]

    if len(recent_data) < 10:
        return None

    tolerance = 0.015  # 1.5% tolerance

    # Find two similar extremes
    for i in range(2, len(data_to_check) - 2):
        for j in range(i + 2, len(data_to_check)):
            first_extreme = data_to_check[i]
            second_extreme = data_to_check[j]

            # Check if extremes are similar (within tolerance)
            pct_diff = abs(first_extreme - second_extreme) / first_extreme if first_extreme != 0 else float("inf")
            if pct_diff < tolerance:
                # Check if there's an intermediate peak/valley
                intermediate_values = recent_data[i : j + 1]
                if is_bottom:
                    has_intermediate = max(intermediate_values) > first_extreme * 1.01
                else:
                    has_intermediate = min(intermediate_values) < first_extreme * 0.99

                if has_intermediate:
                    pattern_type = PatternType.DOUBLE_BOTTOM if is_bottom else PatternType.DOUBLE_TOP
                    breakout = "up" if is_bottom else "down"
                    return PatternDetection(
                        pattern_type=pattern_type,
                        start_index=len(highs) - lookback + i,
                        end_index=len(highs) - lookback + j,
                        formation_strength=min(100.0, (1 - pct_diff) * 100),
                        potential_breakout=breakout,
                        confirmation_needed=True,
                    )

    return None


def _detect_head_shoulders(highs: List[float], lows: List[float], is_inverse: bool = False) -> Optional[PatternDetection]:
    """
    Detect head & shoulders or inverse H&S patterns.

    H&S: left shoulder, head higher, right shoulder lower, neckline support.
    Inverse H&S: bearish reversal pattern.
    """
    lookback = 40
    if len(highs) < lookback:
        return None

    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]

    # Find three major peaks/valleys
    if is_inverse:
        # Looking for: valley, lower valley, valley (three lows)
        extremes = [
            (i, recent_lows[i])
            for i in range(1, len(recent_lows) - 1)
            if recent_lows[i] < recent_lows[i - 1] and recent_lows[i] < recent_lows[i + 1]
        ]
    else:
        # Looking for: peak, higher peak, peak (three highs)
        extremes = [
            (i, recent_highs[i])
            for i in range(1, len(recent_highs) - 1)
            if recent_highs[i] > recent_highs[i - 1] and recent_highs[i] > recent_highs[i + 1]
        ]

    if len(extremes) >= 3:
        # Check if middle extreme is highest/lowest
        sorted_by_value = sorted(extremes, key=lambda x: x[1], reverse=not is_inverse)
        middle_extreme = extremes[1]

        if (is_inverse and middle_extreme[1] == sorted_by_value[0][1]) or (
            not is_inverse and middle_extreme[1] == sorted_by_value[0][1]
        ):
            pattern_type = PatternType.INVERSE_HEAD_SHOULDERS if is_inverse else PatternType.HEAD_SHOULDERS
            breakout = "up" if is_inverse else "down"
            return PatternDetection(
                pattern_type=pattern_type,
                start_index=len(highs) - lookback + extremes[0][0],
                end_index=len(highs) - lookback + extremes[2][0],
                formation_strength=75.0,
                potential_breakout=breakout,
                confirmation_needed=True,
            )

    return None


def _detect_wedge_or_flag(highs: List[float], lows: List[float]) -> Optional[PatternDetection]:
    """
    Detect wedge and flag patterns.

    Wedges: prices converge to apex, breakout expected.
    Flags: small consolidation after strong move.
    """
    lookback = 30
    if len(highs) < lookback:
        return None

    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]

    # Check if range is converging (upper and lower lines approaching)
    first_half_range = max(recent_highs[: lookback // 2]) - min(recent_lows[: lookback // 2])
    second_half_range = max(recent_highs[lookback // 2 :]) - min(recent_lows[lookback // 2 :])

    if first_half_range > 0 and second_half_range < first_half_range * 0.7:
        # Range converging
        slope_high = (recent_highs[-1] - recent_highs[0]) / lookback if lookback > 0 else 0
        slope_low = (recent_lows[-1] - recent_lows[0]) / lookback if lookback > 0 else 0

        # Ascending wedge: both slopes up, but high slope > low slope
        if slope_high > 0 and slope_low > 0 and slope_high > slope_low:
            return PatternDetection(
                pattern_type=PatternType.ASCENDING_WEDGE,
                start_index=len(highs) - lookback,
                end_index=len(highs) - 1,
                formation_strength=70.0,
                potential_breakout="down",  # Wedges typically break in opposite direction of slope
                confirmation_needed=True,
            )

        # Descending wedge: both slopes down, but high slope < low slope (more negative)
        if slope_high < 0 and slope_low < 0 and slope_high < slope_low:
            return PatternDetection(
                pattern_type=PatternType.DESCENDING_WEDGE,
                start_index=len(highs) - lookback,
                end_index=len(highs) - 1,
                formation_strength=70.0,
                potential_breakout="up",
                confirmation_needed=True,
            )

    return None


def detect_patterns(highs: List[float], lows: List[float]) -> Optional[PatternDetection]:
    """
    Detect any chart pattern in the price data.

    Checks in order: double patterns, H&S, wedges/flags.
    Returns the most confident pattern found.
    """
    if len(highs) < 15:
        return None

    # Try to detect patterns in priority order
    double_bottom = _detect_double_pattern(highs, lows, is_bottom=True)
    double_top = _detect_double_pattern(highs, lows, is_bottom=False)
    head_shoulders = _detect_head_shoulders(highs, lows, is_inverse=False)
    inverse_hs = _detect_head_shoulders(highs, lows, is_inverse=True)
    wedge_flag = _detect_wedge_or_flag(highs, lows)

    patterns = [p for p in [double_bottom, double_top, head_shoulders, inverse_hs, wedge_flag] if p is not None]

    if patterns:
        # Return highest confidence pattern
        return max(patterns, key=lambda p: p.formation_strength)

    return None


def analyze_market_structure(highs: List[float], lows: List[float]) -> MarketStructureAnalysis:
    """
    Analyze market structure: HH/HL, LH/LL, CHoCH, BOS.

    HH + HL = bullish structure
    LH + LL = bearish structure
    CHoCH = change of character (structure flip)
    BOS = break of structure (trend confirmation)
    """
    if len(highs) < 10:
        return MarketStructureAnalysis(
            structure=MarketStructure.TRANSITIONAL,
            recent_high=highs[-1],
            recent_low=lows[-1],
            hh_count=0,
            ll_count=0,
            has_choch=False,
            has_bos=False,
            breakout_level=None,
            bias_strength=0.0,
        )

    swings = _find_swing_points(highs, lows, lookback=20)

    if len(swings) < 4:
        return MarketStructureAnalysis(
            structure=MarketStructure.TRANSITIONAL,
            recent_high=highs[-1],
            recent_low=lows[-1],
            hh_count=0,
            ll_count=0,
            has_choch=False,
            has_bos=False,
            breakout_level=None,
            bias_strength=0.0,
        )

    # Analyze last 4 swings
    recent_swings = swings[-4:]

    hh_count = 0
    ll_count = 0
    lh_count = 0
    hl_count = 0

    # Compare adjacent swings
    for i in range(len(recent_swings) - 1):
        curr = recent_swings[i]
        next_swing = recent_swings[i + 1]

        if curr.is_high and next_swing.is_high:
            if next_swing.price > curr.price:
                hh_count += 1
            else:
                lh_count += 1

        elif not curr.is_high and not next_swing.is_high:
            if next_swing.price > curr.price:
                hl_count += 1
            else:
                ll_count += 1

    # Determine structure
    if hh_count >= 2 or (hh_count >= 1 and hl_count >= 1):
        structure = MarketStructure.BULLISH
        bias_strength = min(100.0, (hh_count + hl_count) * 30)
    elif ll_count >= 2 or (ll_count >= 1 and lh_count >= 1):
        structure = MarketStructure.BEARISH
        bias_strength = min(100.0, (ll_count + lh_count) * 30)
    else:
        structure = MarketStructure.TRANSITIONAL
        bias_strength = 0.0

    # Detect CHoCH (Change of Character) - structure flip
    has_choch = (hh_count == 0 and lh_count >= 2) or (ll_count == 0 and hl_count >= 2)

    # Detect BOS (Break of Structure) - beyond previous extreme
    has_bos = False
    breakout_level = None

    if len(swings) >= 2:
        last_swing = swings[-1]
        second_last = swings[-2]

        if last_swing.is_high and last_swing.price > second_last.price:
            has_bos = True
            breakout_level = last_swing.price
        elif not last_swing.is_high and last_swing.price < second_last.price:
            has_bos = True
            breakout_level = last_swing.price

    return MarketStructureAnalysis(
        structure=structure,
        recent_high=highs[-1],
        recent_low=lows[-1],
        hh_count=hh_count,
        ll_count=ll_count,
        has_choch=has_choch,
        has_bos=has_bos,
        breakout_level=breakout_level,
        bias_strength=bias_strength,
    )


def validate_pattern_with_trend(
    pattern: Optional[PatternDetection],
    structure: MarketStructureAnalysis,
    trend_direction: str,  # "uptrend", "downtrend", "sideways"
) -> tuple[bool, str]:
    """
    Validate if detected pattern aligns with trend direction.

    Rules:
    - Uptrend + bullish structure + upside breakout pattern = VALID
    - Downtrend + bearish structure + downside breakout pattern = VALID
    - Contradiction = INVALID

    Returns:
        (is_valid, reasoning)
    """
    if pattern is None:
        return True, "No clear pattern detected"

    # Pattern breakout direction
    breakout_dir = pattern.potential_breakout  # "up", "down", "bidirectional"

    # Check alignment
    if trend_direction == "uptrend" and structure.structure == MarketStructure.BULLISH:
        if breakout_dir in ["up", "bidirectional"]:
            return True, f"{pattern.pattern_type} confirms uptrend bias"
        else:
            return False, f"{pattern.pattern_type} suggests downside breakout — contradicts uptrend"

    elif trend_direction == "downtrend" and structure.structure == MarketStructure.BEARISH:
        if breakout_dir in ["down", "bidirectional"]:
            return True, f"{pattern.pattern_type} confirms downtrend bias"
        else:
            return False, f"{pattern.pattern_type} suggests upside breakout — contradicts downtrend"

    elif trend_direction == "sideways":
        # Sideways trend: either pattern direction OK as long as structure supports
        if structure.structure != MarketStructure.TRANSITIONAL:
            return True, f"{pattern.pattern_type} forming in {structure.structure.value} structure"
        return True, f"{pattern.pattern_type} in sideways consolidation"

    # Default: mismatch
    return False, f"{pattern.pattern_type} ({breakout_dir}) contradicts {trend_direction}"
