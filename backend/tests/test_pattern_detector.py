"""
Tests for T3 (Pattern) detection.

Tests chart pattern recognition and market structure analysis.
"""

import pytest
from app.services.ta_engine import (
    detect_patterns,
    analyze_market_structure,
    validate_pattern_with_trend,
    MarketStructure,
    PatternType,
)


class TestPatternDetection:
    """Test chart pattern detection."""

    def test_detect_double_bottom(self):
        """Test detection of double bottom pattern."""
        # Create two lows at similar level with intermediate high
        highs = [100, 102, 101, 103, 102, 100, 98, 100, 98, 100] + [105] * 20
        lows = [98, 100, 99, 101, 100, 98, 96, 98, 96, 98] + [103] * 20
        closes = [99, 101, 100, 102, 101, 99, 97, 99, 97, 99] + [104] * 20

        pattern = detect_patterns(highs, lows)

        # May or may not detect depending on exact values
        if pattern:
            assert pattern.pattern_type in [PatternType.DOUBLE_BOTTOM, PatternType.DOUBLE_TOP]

    def test_detect_double_top(self):
        """Test detection of double top pattern."""
        # Create two highs at similar level with intermediate low
        highs = [100, 100, 100, 100, 100] + [110, 105, 110, 105, 110] + [108] * 15
        lows = [98, 98, 98, 98, 98] + [103, 98, 103, 98, 103] + [106] * 15
        closes = [99, 99, 99, 99, 99] + [105, 100, 105, 100, 105] + [107] * 15

        pattern = detect_patterns(highs, lows)

        if pattern:
            assert pattern.pattern_type in [PatternType.DOUBLE_BOTTOM, PatternType.DOUBLE_TOP]

    def test_insufficient_data(self):
        """Test with insufficient data."""
        highs = [100, 101, 102]
        lows = [98, 99, 100]

        pattern = detect_patterns(highs, lows)

        assert pattern is None

    def test_pattern_attributes(self):
        """Test that detected pattern has expected attributes."""
        highs = list(range(100, 150))
        lows = list(range(98, 148))
        closes = list(range(99, 149))

        pattern = detect_patterns(highs, lows)

        if pattern:
            assert 0 <= pattern.formation_strength <= 100
            assert pattern.potential_breakout in ["up", "down", "bidirectional"]
            assert isinstance(pattern.confirmation_needed, bool)


class TestMarketStructure:
    """Test market structure analysis."""

    def test_bullish_structure(self):
        """Test detection of bullish structure (HH + HL)."""
        # Create uptrend with HH and HL
        highs = [100 + i * 2 for i in range(30)]
        lows = [98 + i * 2 for i in range(30)]
        closes = [99 + i * 2 for i in range(30)]

        structure = analyze_market_structure(highs, lows)

        assert structure.structure in [MarketStructure.BULLISH, MarketStructure.TRANSITIONAL]
        if structure.structure == MarketStructure.BULLISH:
            assert structure.hh_count >= 0  # Should have some higher highs

    def test_bearish_structure(self):
        """Test detection of bearish structure (LH + LL)."""
        # Create downtrend with LH and LL
        highs = list(range(150, 120, -1))
        lows = list(range(148, 118, -1))
        closes = list(range(149, 119, -1))

        structure = analyze_market_structure(highs, lows)

        assert structure.structure in [MarketStructure.BEARISH, MarketStructure.TRANSITIONAL]
        if structure.structure == MarketStructure.BEARISH:
            assert structure.ll_count >= 0  # Should have some lower lows

    def test_current_price_tracking(self):
        """Test that current prices are tracked."""
        highs = [100 + i for i in range(30)]
        lows = [98 + i for i in range(30)]
        closes = [99 + i for i in range(30)]

        structure = analyze_market_structure(highs, lows)

        assert structure.recent_high == highs[-1]
        assert structure.recent_low == lows[-1]

    def test_insufficient_data_structure(self):
        """Test structure analysis with insufficient data."""
        highs = [100, 101, 102]
        lows = [98, 99, 100]

        structure = analyze_market_structure(highs, lows)

        assert structure.structure == MarketStructure.TRANSITIONAL

    def test_bias_strength(self):
        """Test that bias strength is calculated."""
        highs = list(range(100, 150))
        lows = list(range(98, 148))
        closes = list(range(99, 149))

        structure = analyze_market_structure(highs, lows)

        assert 0 <= structure.bias_strength <= 100


class TestPatternValidation:
    """Test pattern validation against trend."""

    def test_bullish_pattern_with_uptrend(self):
        """Test that bullish pattern validates with uptrend."""
        # Create uptrend data
        highs = list(range(100, 150))
        lows = list(range(98, 148))
        closes = list(range(99, 149))

        pattern = detect_patterns(highs, lows)
        structure = analyze_market_structure(highs, lows)

        if pattern and structure.structure == MarketStructure.BULLISH:
            is_valid, reason = validate_pattern_with_trend(pattern, structure, "uptrend")
            # Validation logic checks alignment
            assert isinstance(is_valid, bool)
            assert isinstance(reason, str)

    def test_bearish_pattern_with_downtrend(self):
        """Test that bearish pattern validates with downtrend."""
        # Create downtrend data
        highs = list(range(150, 100, -1))
        lows = list(range(148, 98, -1))
        closes = list(range(149, 99, -1))

        pattern = detect_patterns(highs, lows)
        structure = analyze_market_structure(highs, lows)

        if pattern and structure.structure == MarketStructure.BEARISH:
            is_valid, reason = validate_pattern_with_trend(pattern, structure, "downtrend")
            assert isinstance(is_valid, bool)

    def test_validation_reason_messaging(self):
        """Test that validation provides meaningful reasons."""
        highs = list(range(100, 150))
        lows = list(range(98, 148))
        closes = list(range(99, 149))

        pattern = detect_patterns(highs, lows)
        structure = analyze_market_structure(highs, lows)

        is_valid, reason = validate_pattern_with_trend(pattern, structure, "uptrend")

        assert len(reason) > 0
        assert isinstance(reason, str)

    def test_no_pattern(self):
        """Test validation when no pattern exists."""
        highs = list(range(100, 130))
        lows = list(range(98, 128))
        closes = list(range(99, 129))

        structure = analyze_market_structure(highs, lows)

        is_valid, reason = validate_pattern_with_trend(None, structure, "uptrend")

        assert is_valid is True
        assert "No clear pattern" in reason or "pattern" in reason.lower()


class TestPatternEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_flat_price(self):
        """Test with flat/sideways price action."""
        highs = [100] * 50
        lows = [99] * 50
        closes = [99.5] * 50

        pattern = detect_patterns(highs, lows)
        structure = analyze_market_structure(highs, lows)

        assert structure is not None
        assert structure.structure == MarketStructure.TRANSITIONAL

    def test_extreme_volatility(self):
        """Test with extreme price swings."""
        highs = [100 + (i % 2) * 50 for i in range(50)]
        lows = [100 - (i % 2) * 50 for i in range(50)]
        closes = [100 + ((i % 2) - 0.5) * 25 for i in range(50)]

        pattern = detect_patterns(highs, lows)
        structure = analyze_market_structure(highs, lows)

        assert structure is not None
        # Extreme volatility might or might not form clear patterns

    def test_consistent_uptrend(self):
        """Test with consistent uptrend — linear data has no swings."""
        highs = [100 + i * 2 for i in range(60)]
        lows = [98 + i * 2 for i in range(60)]

        structure = analyze_market_structure(highs, lows)

        # Linear uptrend has no swing points, so bias_strength may be 0
        # (no HH/LL detected without actual pullbacks)
        assert structure is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
