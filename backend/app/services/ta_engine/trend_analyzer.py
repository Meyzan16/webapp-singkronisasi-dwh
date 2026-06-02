"""
Trend analyzer module.

Combines EMA and trendline analysis to determine trend state (up/down/sideways).
"""

from typing import List, Optional
from dataclasses import dataclass
from .ema import get_ema_pair
from .trendline import detect_trendline, Trendline


@dataclass
class TrendState:
    """Represents the current trend state for a price series."""

    direction: str  # 'uptrend', 'downtrend', or 'sideways'
    ema_13: float  # Latest EMA 13
    ema_21: float  # Latest EMA 21
    ema_cross: bool  # True if EMA 13 just crossed EMA 21
    ema_distance_pct: float  # Distance between EMA13 and EMA21 as % of EMA21
    trendline: Optional[Trendline]  # Trendline validation
    confidence: float  # 0-100, higher = stronger trend
    reasoning: str  # Human-readable description


def analyze_trend(opens: List[float], highs: List[float], lows: List[float], closes: List[float]) -> Optional[TrendState]:
    """
    Analyze trend using EMA and trendline.

    Args:
        opens: List of open prices (oldest first)
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices

    Returns:
        TrendState object with comprehensive trend analysis, or None if insufficient data
    """
    if len(closes) < 21:
        return None

    # Calculate EMA
    ema_data = get_ema_pair(closes)
    ema_13 = ema_data["latest_ema_13"]
    ema_21 = ema_data["latest_ema_21"]

    if ema_13 is None or ema_21 is None:
        return None

    # Detect trendline
    trendline = detect_trendline(highs, lows)

    # Determine trend direction based on EMA
    # EMA13 > EMA21 → uptrend, EMA13 < EMA21 → downtrend
    ema_uptrend = ema_13 > ema_21
    ema_distance_pct = ((ema_13 - ema_21) / ema_21 * 100) if ema_21 != 0 else 0

    # Check for EMA cross (simplified: check if previous was opposite)
    ema_cross = False
    if len(closes) >= 22:
        ema_data_prev = get_ema_pair(closes[:-1])
        if ema_data_prev["latest_ema_13"] and ema_data_prev["latest_ema_21"]:
            prev_uptrend = ema_data_prev["latest_ema_13"] > ema_data_prev["latest_ema_21"]
            ema_cross = prev_uptrend != ema_uptrend

    # Determine overall direction
    if abs(ema_distance_pct) < 0.5:  # EMA very close = sideways
        direction = "sideways"
    elif ema_uptrend:
        direction = "uptrend"
    else:
        direction = "downtrend"

    # Calculate confidence score (0-100)
    confidence = _calculate_confidence(ema_uptrend, ema_distance_pct, trendline, ema_cross)

    # Generate reasoning
    reasoning = _generate_reasoning(direction, ema_13, ema_21, ema_distance_pct, trendline, ema_cross)

    return TrendState(
        direction=direction,
        ema_13=ema_13,
        ema_21=ema_21,
        ema_cross=ema_cross,
        ema_distance_pct=ema_distance_pct,
        trendline=trendline,
        confidence=confidence,
        reasoning=reasoning,
    )


def _calculate_confidence(ema_uptrend: bool, ema_distance_pct: float, trendline: Optional[Trendline], ema_cross: bool) -> float:
    """Calculate confidence score for the trend (0-100)."""
    score = 50.0

    # EMA distance score (wider = more confident, max +25)
    distance_score = min(abs(ema_distance_pct) / 2, 25)  # Cap at 25
    score += distance_score

    # Trendline validation score (max +25)
    if trendline and trendline.is_valid:
        touch_score = min(trendline.num_touches * 5, 25)  # 5 points per touch, cap at 25
        if trendline.is_broken:
            touch_score *= 0.5  # Reduce confidence if broken
        score += touch_score

    # EMA cross penalty (fresh cross less confident)
    if ema_cross:
        score -= 10

    # Normalize to 0-100
    return max(0, min(100, score))


def _generate_reasoning(
    direction: str,
    ema_13: float,
    ema_21: float,
    ema_distance_pct: float,
    trendline: Optional[Trendline],
    ema_cross: bool,
) -> str:
    """Generate human-readable reasoning for the trend."""
    parts = []

    # EMA analysis
    if abs(ema_distance_pct) < 0.5:
        parts.append(f"EMA 13/21 converged (distance: {ema_distance_pct:.2f}%) → sideways")
    else:
        if ema_13 > ema_21:
            parts.append(f"EMA 13 ({ema_13:.2f}) > EMA 21 ({ema_21:.2f}) → uptrend signal")
        else:
            parts.append(f"EMA 13 ({ema_13:.2f}) < EMA 21 ({ema_21:.2f}) → downtrend signal")

        strength = "strong" if abs(ema_distance_pct) > 2.0 else "moderate" if abs(ema_distance_pct) > 0.5 else "weak"
        parts.append(f"Distance: {ema_distance_pct:+.2f}% ({strength})")

    if ema_cross:
        parts.append("⚠ Fresh EMA cross detected")

    # Trendline analysis
    if trendline and trendline.is_valid:
        strength = "strong" if trendline.num_touches >= 3 else "valid"
        direction_text = "uptrend" if trendline.is_uptrend else "downtrend"
        parts.append(f"Trendline {direction_text} ({strength}, {trendline.num_touches} touches)")

        if trendline.is_broken:
            parts.append(f"⚠ Trendline broken at {trendline.breakout_price:.2f}")
    elif trendline:
        parts.append(f"Trendline forming ({trendline.num_touches} touches, needs 2+)")
    else:
        parts.append("No valid trendline yet")

    return " | ".join(parts)
