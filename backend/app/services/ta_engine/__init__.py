"""
Technical Analysis Engine module.

Provides T0-T4 analysis layers for trading signal generation.
"""

from .ema import calculate_ema, get_latest_ema, get_ema_pair
from .trendline import detect_swing_points, detect_trendline, SwingPoint, Trendline
from .trend_analyzer import analyze_trend, TrendState

__all__ = [
    # EMA
    "calculate_ema",
    "get_latest_ema",
    "get_ema_pair",
    # Trendline
    "detect_swing_points",
    "detect_trendline",
    "SwingPoint",
    "Trendline",
    # Trend analyzer
    "analyze_trend",
    "TrendState",
]
