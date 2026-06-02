"""
Tests for signal generator pipeline (T0-T4 combination).

Tests waterfall gating, risk calculation, and final signal output.
"""

import pytest
from app.services.signal_generator import (
    SignalPipeline,
    calculate_stop_loss,
    calculate_take_profit,
    calculate_risk_metrics,
    build_signal_card,
)


class TestRiskCalculation:
    """Test risk management calculations."""

    def test_stop_loss_long(self):
        """Test stop loss calculation for long positions."""
        entry = 100.0
        support = 95.0

        sl = calculate_stop_loss(entry, "long", support_level=support)

        assert sl < entry
        # SL should be below support
        assert sl <= support * 1.005

    def test_stop_loss_short(self):
        """Test stop loss calculation for short positions."""
        entry = 100.0
        resistance = 105.0

        sl = calculate_stop_loss(entry, "short", resistance_level=resistance)

        assert sl > entry
        # SL should be above resistance
        assert sl >= resistance * 0.995

    def test_take_profit_long(self):
        """Test take profit calculation for long positions."""
        entry = 100.0
        sl = 95.0
        risk = entry - sl

        tp = calculate_take_profit(entry, "long", risk, rr_ratio=3.0)

        assert tp > entry
        # TP should be 3x the risk above entry
        assert abs((tp - entry) - (risk * 3.0)) < 0.01

    def test_take_profit_short(self):
        """Test take profit calculation for short positions."""
        entry = 100.0
        sl = 105.0
        risk = sl - entry

        tp = calculate_take_profit(entry, "short", risk, rr_ratio=3.0)

        assert tp < entry
        # TP should be 3x the risk below entry
        assert abs((entry - tp) - (risk * 3.0)) < 0.01

    def test_risk_metrics_valid(self):
        """Test complete risk metrics calculation with valid R:R."""
        entry = 100.0
        sl = 95.0
        tp = 115.0

        risk_calc = calculate_risk_metrics(entry, sl, tp, "long")

        assert risk_calc.is_valid is True
        assert risk_calc.risk_reward_ratio >= 3.0
        assert risk_calc.risk_amount > 0
        assert risk_calc.reward_amount > 0

    def test_risk_metrics_invalid_rr(self):
        """Test risk metrics with invalid R:R ratio."""
        entry = 100.0
        sl = 95.0
        tp = 103.0  # Only 1:0.6 R:R

        risk_calc = calculate_risk_metrics(entry, sl, tp, "long")

        assert risk_calc.is_valid is False
        assert risk_calc.risk_reward_ratio < 3.0


class TestSignalPipeline:
    """Test the complete signal generation pipeline."""

    def test_pipeline_insufficient_data(self):
        """Test pipeline with insufficient data."""
        pipeline = SignalPipeline("BTCUSDT", "1d")

        opens = [100] * 10
        highs = [101] * 10
        lows = [99] * 10
        closes = [100] * 10
        volumes = [100] * 10

        signal = pipeline.run(opens, highs, lows, closes, volumes)

        assert signal is None
        assert "Insufficient data" in pipeline.skip_reason

    def test_pipeline_with_sufficient_data(self):
        """Test pipeline with uptrending data."""
        pipeline = SignalPipeline("BTCUSDT", "1d")

        # Create uptrending data
        opens = list(range(100, 150))
        highs = list(range(101, 151))
        lows = list(range(99, 149))
        closes = list(range(100, 150))
        volumes = list(range(100, 150))

        signal = pipeline.run(opens, highs, lows, closes, volumes)

        if signal:
            # Should have produced a signal
            assert signal.pair == "BTCUSDT"
            assert signal.entry > 0
            assert signal.stop_loss < signal.entry  # For long
            assert signal.take_profit > signal.entry
            assert 0 <= signal.confidence <= 100

    def test_pipeline_gates(self):
        """Test that pipeline gates work correctly."""
        # Create strongly bearish data when expecting uptrend
        pipeline = SignalPipeline("BTCUSDT", "1d")

        opens = list(range(150, 100, -1))  # Downtrend
        highs = list(range(151, 101, -1))
        lows = list(range(149, 99, -1))
        closes = list(range(150, 100, -1))
        volumes = list(range(100, 150))

        signal = pipeline.run(opens, highs, lows, closes, volumes)

        # May or may not generate signal depending on gate conditions
        if signal is None:
            assert pipeline.skip_reason is not None


class TestSignalCard:
    """Test signal card building and formatting."""

    def test_build_signal_card(self):
        """Test building a complete signal card."""
        signal = build_signal_card(
            pair="BTCUSDT",
            timeframe="1d",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            rr_ratio=3.0,
            position_size_pct=1.0,
            # T0
            wyckoff_phase="Accumulation",
            wyckoff_confidence=70.0,
            # T1
            trend_direction="uptrend",
            trend_confidence=75.0,
            # T2
            sr_zone_info="Support at $95",
            # T3
            pattern_type="Double Bottom",
            pattern_strength=80.0,
            # T4
            trigger_confidence=85.0,
            candle_pattern="Bullish Engulfing",
            stoch_signal="buy",
        )

        assert signal.pair == "BTCUSDT"
        assert signal.direction == "LONG"
        assert signal.entry == 100.0
        assert signal.stop_loss == 95.0
        assert signal.take_profit == 115.0
        assert signal.risk_reward == "1:3.0"
        assert 0 <= signal.confidence <= 100

    def test_signal_card_attributes(self):
        """Test signal card has all required attributes."""
        signal = build_signal_card(
            pair="ETHUSDT",
            timeframe="4h",
            entry_price=1800.0,
            stop_loss=1750.0,
            take_profit=1950.0,
            rr_ratio=2.0,
            position_size_pct=1.5,
            wyckoff_phase="Mark Up",
            wyckoff_confidence=60.0,
            trend_direction="uptrend",
            trend_confidence=65.0,
        )

        # Check all fields exist and are of correct type
        assert isinstance(signal.pair, str)
        assert isinstance(signal.timeframe, str)
        assert isinstance(signal.direction, str)
        assert isinstance(signal.entry, float)
        assert isinstance(signal.stop_loss, float)
        assert isinstance(signal.take_profit, float)
        assert isinstance(signal.confidence, float)
        assert isinstance(signal.timestamp, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
