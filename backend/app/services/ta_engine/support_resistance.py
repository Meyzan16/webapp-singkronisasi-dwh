"""
Support/Resistance zone detection module (T2).

Scans historical price data to find bounce zones and confluence areas.
Stronger zones have more bounces = more reliable support/resistance.
"""

from typing import List, Optional
from dataclasses import dataclass
from enum import Enum


class ZoneType(str, Enum):
    """Type of support/resistance zone."""

    SUPPORT = "Support"
    RESISTANCE = "Resistance"


@dataclass
class SRZone:
    """Represents a support or resistance zone."""

    zone_type: ZoneType
    price_low: float  # Bottom of the zone
    price_high: float  # Top of the zone
    midpoint: float  # Center of the zone
    num_bounces: int  # How many times price bounced off this zone
    strength: float  # 0-100, based on bounces and recency
    is_fibonacci: bool  # True if this aligns with 0.618 retracement
    last_touch_index: int  # Index of most recent bounce


@dataclass
class SRAnalysis:
    """Represents complete S/R analysis for a price series."""

    support_zones: List[SRZone]
    resistance_zones: List[SRZone]
    strongest_support: Optional[SRZone]
    strongest_resistance: Optional[SRZone]
    current_price: float


def _is_bounce(high: float, low: float, zone_low: float, zone_high: float, tolerance: float = 0.01) -> bool:
    """
    Check if a candle bounced off a zone.

    A bounce is when:
    - Low touches the zone but close is above it (support bounce)
    - High touches the zone but close is below it (resistance bounce)
    """
    zone_range = zone_high - zone_low
    zone_mid = (zone_low + zone_high) / 2

    # Check if candle touches the zone
    touches_zone = (low <= zone_low * (1 + tolerance) and high >= zone_low * (1 - tolerance)) or (
        low <= zone_high * (1 + tolerance) and high >= zone_high * (1 - tolerance)
    )

    return touches_zone


def _cluster_zones(prices: List[float], tolerance: float = 0.005) -> List[tuple[float, float]]:
    """
    Cluster similar prices into zones.

    Prices within tolerance% of each other are grouped into one zone.
    Returns list of (zone_low, zone_high) tuples.
    """
    if not prices:
        return []

    sorted_prices = sorted(prices)
    zones = []
    current_cluster = [sorted_prices[0]]

    for price in sorted_prices[1:]:
        # Check if price is within tolerance of cluster
        if price <= current_cluster[-1] * (1 + tolerance):
            current_cluster.append(price)
        else:
            # Start new cluster
            zone_low = current_cluster[0]
            zone_high = current_cluster[-1]
            zones.append((zone_low, zone_high))
            current_cluster = [price]

    # Add final cluster
    if current_cluster:
        zone_low = current_cluster[0]
        zone_high = current_cluster[-1]
        zones.append((zone_low, zone_high))

    return zones


def _calculate_fibonacci_level(swing_low: float, swing_high: float, retracement: float = 0.618) -> float:
    """
    Calculate Fibonacci retracement level.

    Common level: 0.618 (61.8%)
    """
    return swing_high - (swing_high - swing_low) * retracement


def detect_support_resistance(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback_days: int = 30,
) -> Optional[SRAnalysis]:
    """
    Detect support and resistance zones from historical price data.

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        lookback_days: How many candles back to scan (30-100 typical)

    Returns:
        SRAnalysis with identified zones
    """
    if len(highs) < lookback_days:
        return None

    current_price = closes[-1]
    lookback_start = max(0, len(highs) - lookback_days)

    # Get historical highs and lows for zone detection
    historical_highs = highs[lookback_start:]
    historical_lows = lows[lookback_start:]
    historical_closes = closes[lookback_start:]

    # Collect bounce points: local highs as potential resistance, local lows as potential support
    support_candidates = []
    resistance_candidates = []

    for i in range(1, len(historical_lows) - 1):
        # Local low = support candidate
        if historical_lows[i] < historical_lows[i - 1] and historical_lows[i] < historical_lows[i + 1]:
            support_candidates.append(historical_lows[i])

        # Local high = resistance candidate
        if historical_highs[i] > historical_highs[i - 1] and historical_highs[i] > historical_highs[i + 1]:
            resistance_candidates.append(historical_highs[i])

    # Cluster candidates into zones (±0.5% tolerance)
    support_zone_ranges = _cluster_zones(support_candidates, tolerance=0.005)
    resistance_zone_ranges = _cluster_zones(resistance_candidates, tolerance=0.005)

    # Calculate Fibonacci level
    swing_low = min(historical_lows)
    swing_high = max(historical_highs)
    fib_618 = _calculate_fibonacci_level(swing_low, swing_high)

    # Create zone objects with bounce counts
    support_zones = []
    for zone_low, zone_high in support_zone_ranges:
        num_bounces = sum(1 for i, l in enumerate(historical_lows) if _is_bounce(historical_highs[i], l, zone_low, zone_high))

        if num_bounces >= 2:  # Minimum 2 bounces for valid zone
            is_fib = abs((zone_low + zone_high) / 2 - fib_618) < swing_high * 0.01  # Within 1% of fib
            strength = min(100.0, (num_bounces - 1) * 20)  # 20 points per bounce, cap at 100

            zone = SRZone(
                zone_type=ZoneType.SUPPORT,
                price_low=zone_low,
                price_high=zone_high,
                midpoint=(zone_low + zone_high) / 2,
                num_bounces=num_bounces,
                strength=strength,
                is_fibonacci=is_fib,
                last_touch_index=len(historical_lows) - 1,
            )
            support_zones.append(zone)

    resistance_zones = []
    for zone_low, zone_high in resistance_zone_ranges:
        num_bounces = sum(1 for i, h in enumerate(historical_highs) if _is_bounce(h, historical_lows[i], zone_low, zone_high))

        if num_bounces >= 2:  # Minimum 2 bounces for valid zone
            is_fib = abs((zone_low + zone_high) / 2 - fib_618) < swing_high * 0.01  # Within 1% of fib
            strength = min(100.0, (num_bounces - 1) * 20)

            zone = SRZone(
                zone_type=ZoneType.RESISTANCE,
                price_low=zone_low,
                price_high=zone_high,
                midpoint=(zone_low + zone_high) / 2,
                num_bounces=num_bounces,
                strength=strength,
                is_fibonacci=is_fib,
                last_touch_index=len(historical_highs) - 1,
            )
            resistance_zones.append(zone)

    # Sort by strength (strongest first)
    support_zones.sort(key=lambda z: z.strength, reverse=True)
    resistance_zones.sort(key=lambda z: z.strength, reverse=True)

    strongest_support = support_zones[0] if support_zones else None
    strongest_resistance = resistance_zones[0] if resistance_zones else None

    return SRAnalysis(
        support_zones=support_zones,
        resistance_zones=resistance_zones,
        strongest_support=strongest_support,
        strongest_resistance=strongest_resistance,
        current_price=current_price,
    )


def validate_entry_with_sr(
    current_price: float,
    sr_analysis: Optional[SRAnalysis],
    direction: str,  # "long" or "short"
) -> tuple[bool, str]:
    """
    Validate if entry is appropriate based on S/R zones.

    Rules:
    - Long + at support = VALID
    - Long + at resistance = INVALID
    - Short + at support = INVALID
    - Short + at resistance = VALID
    - Counter-trend allowed only if zone has 4+ bounces (very strong)

    Returns:
        (is_valid, reason)
    """
    if sr_analysis is None or (not sr_analysis.support_zones and not sr_analysis.resistance_zones):
        return True, "No S/R zones detected yet"

    # Check if price is near support or resistance (within 2% of zone)
    near_support = False
    near_resistance = False
    support_strength = 0
    resistance_strength = 0

    if sr_analysis.strongest_support:
        zone_range = sr_analysis.strongest_support.price_high - sr_analysis.strongest_support.price_low
        tolerance = max(zone_range, sr_analysis.strongest_support.midpoint * 0.02)

        if abs(current_price - sr_analysis.strongest_support.midpoint) <= tolerance:
            near_support = True
            support_strength = sr_analysis.strongest_support.strength

    if sr_analysis.strongest_resistance:
        zone_range = sr_analysis.strongest_resistance.price_high - sr_analysis.strongest_resistance.price_low
        tolerance = max(zone_range, sr_analysis.strongest_resistance.midpoint * 0.02)

        if abs(current_price - sr_analysis.strongest_resistance.midpoint) <= tolerance:
            near_resistance = True
            resistance_strength = sr_analysis.strongest_resistance.strength

    # Apply rules
    if direction == "long":
        if near_resistance:
            return False, f"Price at resistance ({resistance_strength:.0f} strength) - long invalid"
        if near_support:
            return True, f"Price at support ({support_strength:.0f} strength) - valid long setup"
        return True, "Price away from key zones - long allowed"

    elif direction == "short":
        if near_support:
            return False, f"Price at support ({support_strength:.0f} strength) - short invalid"
        if near_resistance:
            return True, f"Price at resistance ({resistance_strength:.0f} strength) - valid short setup"
        return True, "Price away from key zones - short allowed"

    return True, "Direction not recognized"
