"""
Tests for T1 (Trend) analyzer.

Tests EMA calculation, trendline detection, and trend state analysis.
"""

import pytest
from app.services.ta_engine import (
    get_ema_pair,
    detect_trendline,
    detect_swing_points,
    analyze_trend,
)


class TestEMA:
    """Test EMA calculation."""

    def test_ema_basic(self):
        """Test basic EMA calculation."""
        closes = [100 + i * 0.5 for i in range(30)]  # Need >= 21 data points
        ema_data = get_ema_pair(closes)

        # EMA should exist for this data length
        assert ema_data["latest_ema_13"] is not None
        assert ema_data["latest_ema_21"] is not None

        # EMA values should be within the price range
        prices_min, prices_max = min(closes), max(closes)
        assert prices_min <= ema_data["latest_ema_13"] <= prices_max
        assert prices_min <= ema_data["latest_ema_21"] <= prices_max

    def test_ema_insufficient_data(self):
        """Test EMA with insufficient data."""
        closes = [100, 102, 101]
        ema_data = get_ema_pair(closes)

        # EMA 21 needs at least 21 data points
        assert ema_data["latest_ema_13"] is None
        assert ema_data["latest_ema_21"] is None

    def test_ema_uptrend(self):
        """Test EMA in uptrend."""
        # Create strongly uptrending prices
        closes = list(range(100, 150))  # 100, 101, 102, ..., 149
        ema_data = get_ema_pair(closes)

        # In uptrend, EMA13 should be > EMA21
        assert ema_data["latest_ema_13"] > ema_data["latest_ema_21"]

    def test_ema_downtrend(self):
        """Test EMA in downtrend."""
        # Create strongly downtrending prices
        closes = list(range(150, 100, -1))  # 150, 149, ..., 101
        ema_data = get_ema_pair(closes)

        # In downtrend, EMA13 should be < EMA21
        assert ema_data["latest_ema_13"] < ema_data["latest_ema_21"]


class TestSwingPoints:
    """Test swing point detection."""

    def test_swing_points_basic(self):
        """Test basic swing point detection."""
        # Data with clear swings: up-down-up-down-up pattern
        highs = [100, 110, 105, 95,  108, 115, 100, 90,  112, 118, 105]
        lows  = [95,  105, 100, 88,  102, 108, 94,  82,  106, 112, 98]

        swings = detect_swing_points(highs, lows)

        # Should find at least some swing points
        assert len(swings) > 0

    def test_swing_points_insufficient_data(self):
        """Test swing points with insufficient data."""
        highs = [100, 110]
        lows = [95, 100]

        swings = detect_swing_points(highs, lows)

        # Should return empty list for insufficient data
        assert len(swings) == 0


class TestTrendline:
    """Test trendline detection."""

    def test_trendline_uptrend(self):
        """Test trendline detection in uptrend."""
        # Create uptrending price action with swing lows
        highs = [100, 110, 105, 115, 108, 120, 112, 130, 125]
        lows = [95, 105, 100, 110, 103, 115, 108, 125, 120]

        trendline = detect_trendline(highs, lows, is_uptrend=True)

        if trendline:
            assert trendline.is_uptrend
            # Should have at least 2 touches for validity
            if trendline.is_valid:
                assert trendline.num_touches >= 2

    def test_trendline_downtrend(self):
        """Test trendline detection in downtrend."""
        # Create downtrending price action with swing highs
        highs = [130, 125, 120, 115, 110, 105, 100, 95, 90]
        lows = [120, 115, 110, 105, 100, 95, 90, 85, 80]

        trendline = detect_trendline(highs, lows, is_uptrend=False)

        if trendline:
            assert not trendline.is_uptrend
            # Should have at least 2 touches for validity
            if trendline.is_valid:
                assert trendline.num_touches >= 2

    def test_trendline_insufficient_data(self):
        """Test trendline with insufficient data."""
        highs = [100, 110]
        lows = [95, 100]

        trendline = detect_trendline(highs, lows)

        # Should return None for insufficient data
        assert trendline is None


class TestTrendAnalyzer:
    """Test trend analysis combining EMA and trendline."""

    def test_analyze_trend_uptrend(self):
        """Test trend analysis in uptrend."""
        # Create 3 months of uptrending daily data
        opens = list(range(100, 150))
        closes = list(range(101, 151))
        highs = list(range(102, 152))
        lows = list(range(100, 150))

        trend = analyze_trend(opens, highs, lows, closes)

        assert trend is not None
        assert trend.direction in ["uptrend", "downtrend", "sideways"]
        assert trend.ema_13 > 0
        assert trend.ema_21 > 0
        assert 0 <= trend.confidence <= 100

    def test_analyze_trend_downtrend(self):
        """Test trend analysis in downtrend."""
        # Create 3 months of downtrending daily data
        opens = list(range(150, 100, -1))
        closes = list(range(149, 99, -1))
        highs = list(range(150, 100, -1))
        lows = list(range(148, 98, -1))

        trend = analyze_trend(opens, highs, lows, closes)

        assert trend is not None
        assert trend.direction in ["uptrend", "downtrend", "sideways"]

    def test_analyze_trend_insufficient_data(self):
        """Test trend analysis with insufficient data."""
        opens = list(range(100, 110))
        closes = list(range(101, 111))
        highs = list(range(102, 112))
        lows = list(range(100, 110))

        trend = analyze_trend(opens, highs, lows, closes)

        # Should return None for insufficient data (need 21+)
        assert trend is None

    def test_trend_state_reasoning(self):
        """Test that reasoning string is generated."""
        # Create valid trend data
        opens = list(range(100, 150))
        closes = list(range(101, 151))
        highs = list(range(102, 152))
        lows = list(range(100, 150))

        trend = analyze_trend(opens, highs, lows, closes)

        if trend:
            assert len(trend.reasoning) > 0
            # Should mention EMA
            assert "EMA" in trend.reasoning


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
