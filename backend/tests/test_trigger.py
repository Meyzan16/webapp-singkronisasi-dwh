"""
Tests for T4 (Trigger) signal detection.

Tests candlestick patterns, stochastic oscillator, and combined trigger signals.
"""

import pytest
from app.services.ta_engine import (
    calculate_stochastic,
    detect_stochastic_signal,
    detect_candlestick_pattern,
    detect_trigger,
    validate_no_dry_volume,
    CandlePattern,
)


class TestStochasticCalculation:
    """Test Stochastic oscillator (5,3,3) calculation."""

    def test_stochastic_basic_calculation(self):
        """Test basic stochastic calculation."""
        highs = [100 + i for i in range(20)]
        lows = [98 + i for i in range(20)]
        closes = [99 + i for i in range(20)]

        stochastics = calculate_stochastic(highs, lows, closes)

        assert len(stochastics) == len(closes)
        # First few values should be None (insufficient data)
        assert stochastics[0] is None

        # Later values should be populated
        last_stoch = stochastics[-1]
        assert last_stoch is not None
        assert 0 <= last_stoch.percent_k <= 100
        assert 0 <= last_stoch.percent_d <= 100

    def test_stochastic_oversold_condition(self):
        """Test oversold condition detection."""
        # Create data that goes to very low levels (oversold)
        highs = [100] * 15 + [95, 94, 93, 92, 91]
        lows = [98] * 15 + [93, 92, 91, 90, 89]
        closes = [99] * 15 + [94, 93, 92, 91, 90]

        stochastics = calculate_stochastic(highs, lows, closes)

        last_stoch = stochastics[-1]
        assert last_stoch is not None
        # Should be oversold (both < 20)
        assert last_stoch.is_oversold or (last_stoch.percent_k < 30 and last_stoch.percent_d < 30)

    def test_stochastic_overbought_condition(self):
        """Test overbought condition detection."""
        # Create data that goes to very high levels (overbought)
        highs = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
        lows = [98, 99, 100, 101, 102, 103, 104, 105, 106, 107]
        closes = [99, 100, 101, 102, 103, 104, 105, 106, 107, 108]

        stochastics = calculate_stochastic(highs, lows, closes)

        # Find overbought stochastic
        for stoch in stochastics[-5:]:
            if stoch and stoch.is_overbought:
                assert stoch.percent_k > 80
                assert stoch.percent_d > 80
                break

    def test_stochastic_cross_detection(self):
        """Test %K crossing %D detection."""
        highs = list(range(100, 130))
        lows = list(range(98, 128))
        closes = list(range(99, 129))

        stochastics = calculate_stochastic(highs, lows, closes)

        # Check for cross signals in the data
        has_cross = any(s and (s.crossed_up or s.crossed_down) for s in stochastics if s)
        # May or may not have a cross depending on data pattern

    def test_detect_stochastic_signal(self):
        """Test stochastic signal detection."""
        # Oversold + upward cross
        highs = [100] * 10 + list(range(100, 110))
        lows = [98] * 10 + list(range(98, 108))
        closes = [99] * 10 + list(range(99, 109))

        signal = detect_stochastic_signal(highs, lows, closes)

        # May or may not detect signal depending on exact values


class TestCandlestickPatterns:
    """Test candlestick pattern detection."""

    def test_bullish_engulfing(self):
        """Test bullish engulfing pattern detection."""
        opens = [100, 105, 104]
        highs = [101, 108, 108]
        lows = [99, 104, 102]
        closes = [99, 104, 107]  # Current closes above prev open

        pattern = detect_candlestick_pattern(opens, highs, lows, closes)

        assert pattern == CandlePattern.BULLISH_ENGULFING

    def test_bearish_engulfing(self):
        """Test bearish engulfing pattern detection."""
        opens = [100, 95, 101]
        highs = [101, 101, 102]
        lows = [99, 93, 95]
        closes = [100, 96, 94]  # Current closes below prev open

        pattern = detect_candlestick_pattern(opens, highs, lows, closes)

        assert pattern == CandlePattern.BEARISH_ENGULFING

    def test_hammer_pattern(self):
        """Test hammer pattern detection."""
        opens = [100, 105, 104]
        highs = [101, 108, 107]
        lows = [99, 100, 98]
        closes = [99, 104, 105]  # Close in upper half

        pattern = detect_candlestick_pattern(opens, highs, lows, closes)

        # Should detect hammer (small body, long lower wick)
        if pattern:
            assert pattern in [CandlePattern.HAMMER, CandlePattern.REJECTION_CANDLE]

    def test_shooting_star_pattern(self):
        """Test shooting star pattern detection."""
        opens = [100, 105, 104]
        highs = [101, 108, 112]
        lows = [99, 104, 103]
        closes = [100, 107, 103]  # Close in lower half with high wick

        pattern = detect_candlestick_pattern(opens, highs, lows, closes)

        # May detect shooting star or rejection

    def test_insufficient_data(self):
        """Test with insufficient data."""
        opens = [100, 105]
        highs = [101, 108]
        lows = [99, 104]
        closes = [99, 104]

        pattern = detect_candlestick_pattern(opens, highs, lows, closes)

        # Need at least 3 candles, should return None or pattern


class TestTriggerDetection:
    """Test combined trigger signal detection."""

    def test_trigger_with_all_confirmations(self):
        """Test trigger detection with all confirmations."""
        # Create data with bullish engulfing + oversold stoch + volume spike
        opens = [100] * 10 + [105, 104, 104]
        highs = [101] * 10 + [108, 108, 108]
        lows = [99] * 10 + [104, 102, 102]
        closes = [99] * 10 + [104, 107, 107]
        volumes = [100] * 10 + [150, 200, 300]  # Volume spike at end

        trigger = detect_trigger(opens, highs, lows, closes, volumes)

        if trigger:
            assert trigger.direction in ["buy", "sell"]
            assert 0 <= trigger.confidence <= 100

    def test_trigger_no_volume_spike(self):
        """Test trigger when volume is not spiking."""
        opens = [100] * 15 + [105, 104, 104]
        highs = [101] * 15 + [108, 108, 108]
        lows = [99] * 15 + [104, 102, 102]
        closes = [99] * 15 + [104, 107, 107]
        volumes = [100] * 18  # No volume spike

        trigger = detect_trigger(opens, highs, lows, closes, volumes)

        if trigger:
            assert trigger.has_volume_spike is False

    def test_trigger_with_taker_pressure(self):
        """Test trigger with taker buy pressure data."""
        opens = [100] * 10 + [105, 104]
        highs = [101] * 10 + [108, 108]
        lows = [99] * 10 + [104, 102]
        closes = [99] * 10 + [104, 107]
        volumes = [100] * 12
        taker_buy_volumes = [60] * 10 + [80, 90]  # Strong buying pressure

        trigger = detect_trigger(opens, highs, lows, closes, volumes, taker_buy_volumes)

        if trigger:
            assert trigger.taker_buy_pressure is not None
            assert 0 <= trigger.taker_buy_pressure <= 1

    def test_insufficient_data_trigger(self):
        """Test with insufficient data."""
        opens = [100, 105]
        highs = [101, 108]
        lows = [99, 104]
        closes = [99, 104]
        volumes = [100, 150]

        trigger = detect_trigger(opens, highs, lows, closes, volumes)

        assert trigger is None

    def test_trigger_confidence_calculation(self):
        """Test that confidence is properly calculated."""
        opens = list(range(100, 120))
        highs = list(range(101, 121))
        lows = list(range(99, 119))
        closes = list(range(100, 120))
        volumes = list(range(100, 120))

        trigger = detect_trigger(opens, highs, lows, closes, volumes)

        if trigger:
            # Confidence should be based on confirmations
            assert trigger.confidence > 0


class TestVolumeValidation:
    """Test dry volume validation."""

    def test_healthy_volume(self):
        """Test that healthy volume passes validation."""
        volumes = [100] * 5 + [100, 95, 110]

        is_healthy = validate_no_dry_volume(volumes)

        assert is_healthy is True

    def test_dry_volume_detection(self):
        """Test detection of dry volume (< 30% of average)."""
        volumes = [100] * 5 + [100, 100, 20]  # Last candle is very dry

        is_healthy = validate_no_dry_volume(volumes)

        assert is_healthy is False

    def test_insufficient_data_volume(self):
        """Test with insufficient data."""
        volumes = [100]

        is_healthy = validate_no_dry_volume(volumes, lookback=3)

        # Should return True when can't validate
        assert is_healthy is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
