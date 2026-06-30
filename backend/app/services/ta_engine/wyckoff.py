"""
Wyckoff phase detection module.

Detects market cycle phases: Accumulation, Mark Up, Distribution, Mark Down.
Based on price structure (swing highs/lows) and volume patterns.
"""

from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


class WyckoffPhase(str, Enum):
    """Wyckoff market cycle phases."""

    ACCUMULATION = "Accumulation"
    MARK_UP = "Mark Up"
    DISTRIBUTION = "Distribution"
    MARK_DOWN = "Mark Down"


@dataclass
class WyckoffState:
    """Represents the current Wyckoff phase state."""

    phase: WyckoffPhase
    strength: float  # 0-100, how confident we are in this phase
    description: str
    support_level: float  # Key support for current phase
    resistance_level: float  # Key resistance for current phase
    volume_trend: str  # "increasing", "decreasing", "divergence"


def detect_swing_structure(highs: List[float], lows: List[float], period: int = 5) -> tuple[list[bool], list[bool]]:
    """
    Detect Higher Highs (HH), Lower Highs (LH), Higher Lows (HL), Lower Lows (LL).

    Returns:
        (higher_highs, higher_lows) - boolean arrays indicating trend direction
    """
    if len(highs) < period * 2:
        return [], []

    higher_highs = [None] * period
    higher_lows = [None] * period

    # Compare recent swings
    for i in range(period, len(highs)):
        # Check if current high is higher than previous high
        prev_high = max(highs[i - period : i])
        higher_highs.append(highs[i] > prev_high)

        # Check if current low is higher than previous low
        prev_low = min(lows[i - period : i])
        higher_lows.append(lows[i] > prev_low)

    return higher_highs, higher_lows


def detect_spring_shakeout(lows: List[float], closes: List[float], period: int = 10) -> tuple[bool, bool]:
    """
    Detect spring (temporary dip below support) and shakeout (temporary break above resistance).

    Spring = price dips below support but closes above it (accumulation signature)
    Shakeout = price breaks above resistance but closes below it (distribution signature)

    Returns:
        (has_spring, has_shakeout)
    """
    if len(lows) < period:
        return False, False

    # Get recent support/resistance
    support = min(lows[-period:])
    resistance = max(lows[-period:])  # Using recent range

    # Check recent candles for spring/shakeout
    recent_lows = lows[-3:]
    recent_closes = closes[-3:]

    # Spring: low below support but close above it
    has_spring = any(l < support and c > support for l, c in zip(recent_lows, recent_closes))

    # Shakeout: similar but for resistance (less common in lower timeframes)
    has_shakeout = any(l < resistance and c > resistance for l, c in zip(recent_lows, recent_closes))

    return has_spring, has_shakeout


def calculate_volume_trend(volumes: List[float], period: int = 10) -> str:
    """
    Calculate volume trend: increasing, decreasing, or divergence.

    Divergence = volume not confirming price movement (warning sign)
    """
    if len(volumes) < period:
        return "unknown"

    recent_volumes = volumes[-period:]
    avg_volume = sum(recent_volumes) / len(recent_volumes)

    # Volume increasing or decreasing
    if recent_volumes[-1] > avg_volume * 1.2:
        return "increasing"
    elif recent_volumes[-1] < avg_volume * 0.8:
        return "decreasing"
    else:
        return "normal"


def detect_wyckoff_phase(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    trend_direction: str,  # "uptrend", "downtrend", "sideways"
) -> Optional[WyckoffState]:
    """
    Detect Wyckoff market cycle phase.

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        volumes: List of volume values
        trend_direction: Current trend from T1 analyzer

    Returns:
        WyckoffState with phase detection and metrics
    """
    if len(highs) < 20:
        return None

    # Detect price structure
    higher_highs, higher_lows = detect_swing_structure(highs, lows, period=5)
    has_spring, has_shakeout = detect_spring_shakeout(lows, closes)
    volume_trend = calculate_volume_trend(volumes)

    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    current_price = closes[-1]

    # Count HH and HL from recent candles
    if higher_highs:
        hh_count = sum(1 for x in higher_highs[-10:] if x is True)
        hl_count = sum(1 for x in higher_lows[-10:] if x is True)
    else:
        hh_count = 0
        hl_count = 0

    # Determine phase
    phase = None
    strength = 0.0
    description = ""

    if trend_direction == "sideways":
        # Sideways = accumulation or distribution
        if has_spring and volume_trend == "increasing":
            phase = WyckoffPhase.ACCUMULATION
            strength = 70.0
            description = "Sideways with spring detected — accumulation phase"
        elif has_shakeout:
            phase = WyckoffPhase.DISTRIBUTION
            strength = 60.0
            description = "Sideways with shakeout detected — distribution phase"
        else:
            # Default to accumulation in sideways if recent trend was down
            phase = WyckoffPhase.ACCUMULATION
            strength = 40.0
            description = "Sideways consolidation — likely accumulation"

    elif trend_direction == "uptrend":
        # Uptrend = mark up or mark down prep
        if hh_count >= 2 and hl_count >= 2:
            phase = WyckoffPhase.MARK_UP
            strength = 80.0
            description = f"Clear HH + HL forming — mark up phase ({hh_count} HH, {hl_count} HL)"
        elif current_price > (recent_low + (recent_high - recent_low) * 0.7):
            # Price in upper range after uptrend
            phase = WyckoffPhase.DISTRIBUTION
            strength = 50.0
            description = "Price extended high — entering distribution"
        else:
            phase = WyckoffPhase.MARK_UP
            strength = 60.0
            description = "Uptrend continuing — mark up phase"

    elif trend_direction == "downtrend":
        # Downtrend = mark down or accumulation prep
        if has_spring:
            phase = WyckoffPhase.ACCUMULATION
            strength = 65.0
            description = "Downtrend with spring — accumulation likely soon"
        else:
            phase = WyckoffPhase.MARK_DOWN
            strength = 75.0
            description = "Clear downtrend — mark down phase"

    if phase is None:
        phase = WyckoffPhase.ACCUMULATION
        strength = 50.0
        description = "Unclear phase — defaulting to accumulation"

    # Set support/resistance based on phase
    support_level = recent_low
    resistance_level = recent_high

    return WyckoffState(
        phase=phase,
        strength=strength,
        description=description,
        support_level=support_level,
        resistance_level=resistance_level,
        volume_trend=volume_trend,
    )
