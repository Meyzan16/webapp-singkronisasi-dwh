"""
Stochastic oscillator module (5,3,3).

Calculates %K and %D for entry signal confirmation.
The ONLY oscillator used in this system.
"""

from typing import List, Optional
from dataclasses import dataclass


@dataclass
class StochasticValue:
    """Represents one Stochastic reading."""

    percent_k: float  # 0-100
    percent_d: float  # 0-100 (smoothed %K)
    is_oversold: bool  # %K and %D both < 20
    is_overbought: bool  # %K and %D both > 80
    crossed_up: bool  # %K crosses above %D from below
    crossed_down: bool  # %K crosses below %D from above


def _sma(values: List[float], period: int) -> List[Optional[float]]:
    """
    Calculate Simple Moving Average.

    Returns list with None for insufficient data.
    """
    if len(values) < period:
        return [None] * len(values)

    sma_values = [None] * (period - 1)

    for i in range(period - 1, len(values)):
        sma = sum(values[i - period + 1 : i + 1]) / period
        sma_values.append(sma)

    return sma_values


def calculate_stochastic(highs: List[float], lows: List[float], closes: List[float], k_period: int = 5, d_period: int = 3) -> List[Optional[StochasticValue]]:
    """
    Calculate Stochastic oscillator (5, 3, 3).

    k_period = 5 (lookback for %K calculation)
    d_period = 3 (SMA period for %D smoothing)

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        k_period: Period for %K calculation (default 5)
        d_period: Period for %D calculation (default 3)

    Returns:
        List of StochasticValue, with None for insufficient data
    """
    if len(closes) < k_period:
        return [None] * len(closes)

    # Calculate %K
    percent_k_values = []

    for i in range(len(closes)):
        if i < k_period - 1:
            percent_k_values.append(None)
        else:
            # Lowest low and highest high over the period
            lowest_low = min(lows[i - k_period + 1 : i + 1])
            highest_high = max(highs[i - k_period + 1 : i + 1])

            # %K = (close - lowest_low) / (highest_high - lowest_low) * 100
            if highest_high - lowest_low != 0:
                percent_k = ((closes[i] - lowest_low) / (highest_high - lowest_low)) * 100
            else:
                percent_k = 50.0  # If no range, assume middle

            percent_k_values.append(percent_k)

    # Calculate %D (SMA of %K)
    percent_d_values = _sma([v if v is not None else 50.0 for v in percent_k_values], d_period)

    # Build results with cross detection
    results = []
    for i in range(len(closes)):
        if percent_k_values[i] is None or percent_d_values[i] is None:
            results.append(None)
        else:
            k = percent_k_values[i]
            d = percent_d_values[i]

            # Oversold/overbought
            is_oversold = k < 20 and d < 20
            is_overbought = k > 80 and d > 80

            # Cross detection
            crossed_up = False
            crossed_down = False

            if i > 0 and percent_k_values[i - 1] is not None and percent_d_values[i - 1] is not None:
                prev_k = percent_k_values[i - 1]
                prev_d = percent_d_values[i - 1]

                # %K crosses above %D
                if prev_k <= prev_d and k > d:
                    crossed_up = True

                # %K crosses below %D
                if prev_k >= prev_d and k < d:
                    crossed_down = True

            results.append(
                StochasticValue(
                    percent_k=k,
                    percent_d=d,
                    is_oversold=is_oversold,
                    is_overbought=is_overbought,
                    crossed_up=crossed_up,
                    crossed_down=crossed_down,
                )
            )

    return results


def get_latest_stochastic(highs: List[float], lows: List[float], closes: List[float]) -> Optional[StochasticValue]:
    """Get the most recent Stochastic reading."""
    stochastics = calculate_stochastic(highs, lows, closes)

    if not stochastics:
        return None

    # Find the last non-None value
    for i in range(len(stochastics) - 1, -1, -1):
        if stochastics[i] is not None:
            return stochastics[i]

    return None


def detect_stochastic_signal(highs: List[float], lows: List[float], closes: List[float]) -> Optional[str]:
    """
    Detect Stochastic entry signal.

    Rules:
    - BUY: %K and %D both below 20 (oversold), then %K crosses ABOVE %D. Wait for candle close.
    - SELL: %K and %D both above 80 (overbought), then %K crosses BELOW %D. Wait for candle close.
    - NONE: No signal

    Returns:
        "buy", "sell", or None
    """
    stochastic = get_latest_stochastic(highs, lows, closes)

    if stochastic is None:
        return None

    # Buy signal
    if stochastic.is_oversold and stochastic.crossed_up:
        return "buy"

    # Sell signal
    if stochastic.is_overbought and stochastic.crossed_down:
        return "sell"

    return None
