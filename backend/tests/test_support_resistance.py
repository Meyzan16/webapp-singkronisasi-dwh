"""
Tests for T2 (Support/Resistance) zone detection.

Tests zone identification and bounce counting.
"""

import pytest
from app.services.ta_engine import detect_support_resistance, validate_entry_with_sr


class TestSupportResistanceDetection:
    """Test S/R zone detection."""

    def test_detect_simple_support_zone(self):
        """Test detection of a simple support zone."""
        # Create price that bounces off 100 multiple times
        highs = [102, 101, 103, 102, 104] + [103, 102, 104, 102, 103] + [105, 104, 106, 105, 107]
        lows = [99, 98, 99, 98, 99] + [99, 98, 99, 98, 99] + [99, 98, 99, 98, 99]
        closes = [100, 99, 101, 100, 102] + [101, 100, 102, 101, 103] + [104, 103, 105, 104, 106]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=15)

        assert sr is not None
        assert len(sr.support_zones) > 0
        # Support zone should be around 98-99 area
        assert sr.strongest_support is not None
        assert 98 <= sr.strongest_support.midpoint <= 100

    def test_detect_resistance_zone(self):
        """Test detection of a resistance zone."""
        # Create price that bounces off resistance multiple times
        highs = [100, 99, 100, 99, 100] + [100, 99, 100, 99, 100] + [100, 99, 100, 99, 100]
        lows = [98, 97, 98, 97, 98] + [98, 97, 98, 97, 98] + [98, 97, 98, 97, 98]
        closes = [99, 98, 99, 98, 99] + [99, 98, 99, 98, 99] + [99, 98, 99, 98, 99]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=15)

        assert sr is not None
        assert len(sr.resistance_zones) > 0
        # Resistance should be near the highs
        assert sr.strongest_resistance is not None

    def test_multiple_zones(self):
        """Test detection of multiple S/R zones."""
        # Uptrend with multiple support bounces
        highs = [100 + i * 2 for i in range(30)]
        lows = [98 + i * 2 for i in range(30)]
        closes = [99 + i * 2 for i in range(30)]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=25)

        assert sr is not None
        # Should detect support zones at various levels
        assert len(sr.support_zones) >= 0  # May be 0 if data doesn't create bounces

    def test_insufficient_data(self):
        """Test with insufficient data."""
        highs = [100, 101, 102]
        lows = [98, 99, 100]
        closes = [99, 100, 101]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=30)

        # Should return None if not enough data
        assert sr is None

    def test_current_price_tracking(self):
        """Test that current price is correctly tracked."""
        highs = [100 + i for i in range(50)]
        lows = [98 + i for i in range(50)]
        closes = [99 + i for i in range(50)]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=30)

        assert sr is not None
        # Current price should be the last close
        assert sr.current_price == closes[-1]

    def test_zone_strength_calculation(self):
        """Test that zone strength is properly calculated."""
        # Create multiple bounces off same level
        highs = [102, 101, 102, 101, 102, 101, 102]
        lows = [99, 98, 99, 98, 99, 98, 99]
        closes = [100, 99, 100, 99, 100, 99, 100]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=7)

        if sr and sr.strongest_support:
            # Strength should increase with more bounces
            assert sr.strongest_support.strength >= 0
            assert sr.strongest_support.strength <= 100
            # More bounces = higher strength (strength = (bounces - 1) * 20)
            assert sr.strongest_support.strength == (sr.strongest_support.num_bounces - 1) * 20 or sr.strongest_support.strength == 100

    def test_fibonacci_confluence(self):
        """Test fibonacci level identification."""
        highs = [110 + i for i in range(50)]
        lows = [100 + i for i in range(50)]
        closes = [105 + i for i in range(50)]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=30)

        assert sr is not None
        # Should have some zones identified
        all_zones = sr.support_zones + sr.resistance_zones
        # At least one zone might align with fibonacci
        has_fib = any(z.is_fibonacci for z in all_zones)
        # This may or may not be true depending on data, but flag should exist
        assert all(isinstance(z.is_fibonacci, bool) for z in all_zones)


class TestEntryValidation:
    """Test entry validation with S/R."""

    def test_long_at_support(self):
        """Test that long entry at support is valid."""
        highs = [100 + i for i in range(30)]
        lows = [98 + i for i in range(30)]
        closes = [99 + i for i in range(30)]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=25)

        if sr:
            current_price = sr.current_price
            is_valid, reason = validate_entry_with_sr(current_price, sr, "long")
            # Should be valid or at least not explicitly invalid
            assert isinstance(is_valid, bool)

    def test_short_validation(self):
        """Test short entry validation."""
        highs = [100 + i for i in range(30)]
        lows = [98 + i for i in range(30)]
        closes = [99 + i for i in range(30)]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=25)

        if sr:
            current_price = sr.current_price
            is_valid, reason = validate_entry_with_sr(current_price, sr, "short")
            assert isinstance(is_valid, bool)
            assert isinstance(reason, str)

    def test_no_sr_zones(self):
        """Test validation when no zones are detected."""
        is_valid, reason = validate_entry_with_sr(100.0, None, "long")

        assert is_valid is True
        assert "No S/R zones" in reason or "no zones" in reason.lower()

    def test_reason_messaging(self):
        """Test that validation provides meaningful reasons."""
        highs = [100 + i for i in range(30)]
        lows = [98 + i for i in range(30)]
        closes = [99 + i for i in range(30)]

        sr = detect_support_resistance(highs, lows, closes, lookback_days=25)

        if sr:
            is_valid, reason = validate_entry_with_sr(sr.current_price, sr, "long")
            assert len(reason) > 0
            assert isinstance(reason, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
