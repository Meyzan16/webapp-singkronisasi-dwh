"""
Technical Analysis Engine module.

Provides T0-T4 analysis layers for trading signal generation.
"""

from .ema import calculate_ema, get_latest_ema, get_ema_pair
from .trendline import detect_swing_points, detect_trendline, SwingPoint, Trendline
from .trend_analyzer import analyze_trend, TrendState
from .wyckoff import detect_wyckoff_phase, WyckoffPhase, WyckoffState
from .support_resistance import detect_support_resistance, validate_entry_with_sr, SRZone, SRAnalysis, ZoneType
from .pattern_detector import (
    detect_patterns,
    analyze_market_structure,
    validate_pattern_with_trend,
    PatternDetection,
    PatternType,
    MarketStructureAnalysis,
    MarketStructure,
)

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
    # Wyckoff
    "detect_wyckoff_phase",
    "WyckoffPhase",
    "WyckoffState",
    # Support/Resistance
    "detect_support_resistance",
    "validate_entry_with_sr",
    "SRZone",
    "SRAnalysis",
    "ZoneType",
    # Pattern detection
    "detect_patterns",
    "analyze_market_structure",
    "validate_pattern_with_trend",
    "PatternDetection",
    "PatternType",
    "MarketStructureAnalysis",
    "MarketStructure",
]
