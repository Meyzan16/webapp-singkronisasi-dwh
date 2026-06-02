"""
Tests for T0 (Wyckoff) phase analyzer.

Tests market cycle phase detection based on price structure and volume.
"""

import pytest
from app.services.ta_engine import detect_wyckoff_phase, WyckoffPhase


class TestWyckoffPhaseDetection:
    """Test Wyckoff phase detection."""

    def test_detect_accumulation_phase(self):
        """Test detection of accumulation phase."""
        # Create sideways price action with low volume (accumulation signature)
        highs = [100, 101, 100, 102, 101, 100, 102, 101, 100, 102] + [101] * 15
        lows = [98, 99, 98, 99, 98, 99, 98, 99, 98, 99] + [99] * 15
        closes = [99, 99.5, 99, 100, 99.5, 99, 100, 99.5, 99, 100] + [100] * 15
        volumes = [100] * 25  # Low volume in sideways

        wyckoff = detect_wyckoff_phase(highs, lows, closes, volumes, "sideways")

        assert wyckoff is not None
        assert wyckoff.phase in [WyckoffPhase.ACCUMULATION, WyckoffPhase.DISTRIBUTION]

    def test_detect_markup_phase(self):
        """Test detection of mark up phase."""
        # Create uptrending price action with HH and HL
        highs = list(range(100, 120))  # 100, 101, ..., 119
        lows = list(range(98, 118))
        closes = list(range(99, 119))
        volumes = [100 + i for i in range(20)]  # Increasing volume

        wyckoff = detect_wyckoff_phase(highs, lows, closes, volumes, "uptrend")

        assert wyckoff is not None
        assert wyckoff.phase == WyckoffPhase.MARK_UP
        assert wyckoff.strength > 50

    def test_detect_markdown_phase(self):
        """Test detection of mark down phase."""
        # Create downtrending price action
        highs = list(range(120, 100, -1))  # 120, 119, ..., 101
        lows = list(range(118, 98, -1))
        closes = list(range(119, 99, -1))
        volumes = [100] * 20

        wyckoff = detect_wyckoff_phase(highs, lows, closes, volumes, "downtrend")

        assert wyckoff is not None
        assert wyckoff.phase == WyckoffPhase.MARK_DOWN
        assert wyckoff.strength > 50

    def test_insufficient_data(self):
        """Test with insufficient data."""
        highs = [100, 102, 101]
        lows = [98, 100, 99]
        closes = [99, 101, 100]
        volumes = [100, 100, 100]

        wyckoff = detect_wyckoff_phase(highs, lows, closes, volumes, "uptrend")

        # Should return None or default phase
        if wyckoff is None:
            assert True
        else:
            # If it returns something, strength should be low
            assert wyckoff.strength < 50

    def test_support_resistance_levels(self):
        """Test that support and resistance levels are calculated."""
        highs = list(range(100, 150))
        lows = list(range(98, 148))
        closes = list(range(99, 149))
        volumes = [100] * 50

        wyckoff = detect_wyckoff_phase(highs, lows, closes, volumes, "uptrend")

        assert wyckoff is not None
        assert wyckoff.support_level > 0
        assert wyckoff.resistance_level > wyckoff.support_level
        # Resistance should be near max, support near min
        assert wyckoff.resistance_level >= max(highs[-20:])
        assert wyckoff.support_level <= min(lows[-20:])

    def test_volume_trend_detection(self):
        """Test volume trend analysis."""
        highs = list(range(100, 120))
        lows = list(range(98, 118))
        closes = list(range(99, 119))

        # Test with increasing volume
        volumes = [100 + i * 5 for i in range(20)]
        wyckoff = detect_wyckoff_phase(highs, lows, closes, volumes, "uptrend")
        assert wyckoff is not None
        assert wyckoff.volume_trend in ["increasing", "normal", "unknown"]

    def test_sideways_trend(self):
        """Test behavior with sideways trend."""
        highs = [100] * 20
        lows = [99] * 20
        closes = [99.5] * 20
        volumes = [100] * 20

        wyckoff = detect_wyckoff_phase(highs, lows, closes, volumes, "sideways")

        assert wyckoff is not None
        # Sideways should result in accumulation or distribution
        assert wyckoff.phase in [WyckoffPhase.ACCUMULATION, WyckoffPhase.DISTRIBUTION]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
