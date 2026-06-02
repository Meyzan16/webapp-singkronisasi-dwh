"""
EMA (Exponential Moving Average) calculation module.

Provides EMA 13 and EMA 21 calculation for trend analysis.
"""

from typing import List


def calculate_ema(closes: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average (EMA).

    Args:
        closes: List of closing prices (in chronological order, oldest first)
        period: EMA period (e.g., 13 or 21)

    Returns:
        List of EMA values (None for insufficient data, then calculated values)
    """
    if len(closes) < period:
        return [None] * len(closes)

    ema_values = [None] * period
    multiplier = 2 / (period + 1)

    # Initialize with SMA for first value
    sma = sum(closes[:period]) / period
    ema_values[period - 1] = sma

    # Calculate EMA for remaining values
    for i in range(period, len(closes)):
        ema = (closes[i] - ema_values[i - 1]) * multiplier + ema_values[i - 1]
        ema_values.append(ema)

    return ema_values


def get_latest_ema(closes: List[float], period: int) -> float | None:
    """
    Get the latest EMA value.

    Args:
        closes: List of closing prices
        period: EMA period

    Returns:
        Latest EMA value or None if insufficient data
    """
    if len(closes) < period:
        return None

    multiplier = 2 / (period + 1)

    # Initialize with SMA
    ema = sum(closes[:period]) / period

    # Calculate EMA for remaining values
    for i in range(period, len(closes)):
        ema = (closes[i] - ema) * multiplier + ema

    return ema


def get_ema_pair(closes: List[float]) -> dict:
    """
    Calculate both EMA 13 and EMA 21.

    Args:
        closes: List of closing prices

    Returns:
        Dict with ema_13, ema_21, and latest values
    """
    if len(closes) < 21:
        return {
            "ema_13": None,
            "ema_21": None,
            "latest_ema_13": None,
            "latest_ema_21": None,
        }

    ema_13 = calculate_ema(closes, 13)
    ema_21 = calculate_ema(closes, 21)

    return {
        "ema_13": ema_13,
        "ema_21": ema_21,
        "latest_ema_13": ema_13[-1] if ema_13[-1] is not None else None,
        "latest_ema_21": ema_21[-1] if ema_21[-1] is not None else None,
    }
