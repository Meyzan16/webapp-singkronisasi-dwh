"""
Signal generation pipeline (T0 → T1 → T2 → T3 → T4).

Waterfall gating: each layer is a filter. Fail at any stage = skip token.
"""

from typing import List, Optional, Tuple
from app.services.ta_engine import (
    analyze_trend,
    detect_wyckoff_phase,
    detect_support_resistance,
    detect_patterns,
    analyze_market_structure,
    detect_trigger,
    validate_no_dry_volume,
)
from app.services.signal_generator.risk_calculator import (
    calculate_stop_loss,
    calculate_take_profit,
    calculate_risk_metrics,
    validate_risk_rules,
)
from app.services.signal_generator.signal_card import build_signal_card, format_signal_to_json, SignalCard


class SignalPipeline:
    """
    Runs the complete signal generation pipeline.

    Waterfall: T0 → T1 → T2 → T3 → T4 → Risk → Output

    Each layer can gate (skip) the signal if conditions aren't met.
    """

    def __init__(self, pair: str, timeframe: str):
        self.pair = pair
        self.timeframe = timeframe
        self.skip_reason = None

    def run(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
        taker_buy_volumes: Optional[List[float]] = None,
    ) -> Optional[SignalCard]:
        """
        Run the complete signal pipeline.

        Returns:
            SignalCard if all gates passed, None if skipped at any stage
        """
        if len(closes) < 30:
            self.skip_reason = "Insufficient data"
            return None

        # ==== T0: Wyckoff phase detection ====
        wyckoff_state = detect_wyckoff_phase(highs, lows, closes, volumes, "sideways")
        if wyckoff_state is None:
            self.skip_reason = "T0: Could not analyze Wyckoff phase"
            return None

        # ==== T1: Trend analysis ====
        trend_state = analyze_trend(opens, highs, lows, closes)
        if trend_state is None:
            self.skip_reason = "T1: Could not analyze trend"
            return None

        # Gate: Trend must align with Wyckoff phase
        trend_direction = trend_state.direction
        wyckoff_phase = wyckoff_state.phase.value

        if not self._validate_t0_t1_alignment(trend_direction, wyckoff_phase):
            self.skip_reason = f"Gate (T0→T1): {trend_direction} contradicts {wyckoff_phase}"
            return None

        # ==== T2: Support/Resistance zones ====
        sr_analysis = detect_support_resistance(highs, lows, closes, lookback_days=30)
        if sr_analysis is None:
            self.skip_reason = "T2: Could not analyze S/R zones"
            return None

        # Gate: Entry price must be valid for direction
        current_price = closes[-1]
        sr_valid, sr_reason = self._validate_entry_with_sr(current_price, sr_analysis, trend_direction)
        if not sr_valid:
            self.skip_reason = f"Gate (T2): {sr_reason}"
            return None

        # ==== T3: Pattern detection ====
        pattern = detect_patterns(highs, lows)
        market_structure = analyze_market_structure(highs, lows)

        # Gate: Pattern must confirm trend direction
        if pattern:
            pattern_valid, pattern_reason = self._validate_pattern_with_trend(pattern, market_structure, trend_direction)
            if not pattern_valid:
                self.skip_reason = f"Gate (T3): {pattern_reason}"
                return None

        # ==== T4: Trigger signal ====
        trigger = detect_trigger(opens, highs, lows, closes, volumes, taker_buy_volumes)
        if trigger is None:
            self.skip_reason = "T4: No trigger signal detected"
            return None

        # Gate: Volume must not be dry
        if not validate_no_dry_volume(volumes):
            self.skip_reason = "Gate (T4): Dry volume (< 30% of average)"
            return None

        # All gates passed! Now calculate risk metrics
        # ==== Risk management ====

        # Determine SL and TP
        support_level = sr_analysis.strongest_support.midpoint if sr_analysis.strongest_support else None
        resistance_level = sr_analysis.strongest_resistance.midpoint if sr_analysis.strongest_resistance else None
        sr_zone = (sr_analysis.strongest_support.price_low, sr_analysis.strongest_support.price_high) if sr_analysis.strongest_support else None

        entry_price = current_price
        direction = trigger.direction.lower()

        # Calculate SL
        stop_loss = calculate_stop_loss(
            entry_price=entry_price,
            direction=direction,
            support_level=support_level if direction == "long" else resistance_level,
            resistance_level=resistance_level if direction == "short" else support_level,
            sr_zone=sr_zone,
        )

        # Calculate risk amount
        risk_amount = abs(entry_price - stop_loss)

        # Calculate TP (target 1:3 R:R)
        take_profit = calculate_take_profit(
            entry_price=entry_price,
            direction=direction,
            risk_amount=risk_amount,
            rr_ratio=3.0,
        )

        # Calculate complete risk metrics
        risk_calc = calculate_risk_metrics(
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            direction=direction,
        )

        # Gate: R:R must be >= 1:3
        if not risk_calc.is_valid:
            self.skip_reason = f"Gate (Risk): {risk_calc.reasoning}"
            return None

        # Validate all risk rules
        risk_valid, risk_reason = validate_risk_rules(risk_calc)
        if not risk_valid:
            self.skip_reason = f"Gate (Risk Rules): {risk_reason}"
            return None

        # ==== Build signal card ====
        signal = build_signal_card(
            pair=self.pair,
            timeframe=self.timeframe,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rr_ratio=risk_calc.risk_reward_ratio,
            position_size_pct=risk_calc.position_size_pct,
            # T0
            wyckoff_phase=wyckoff_phase,
            wyckoff_confidence=wyckoff_state.strength,
            # T1
            trend_direction=trend_direction,
            trend_confidence=trend_state.confidence,
            # T2
            sr_zone_info=self._format_sr_info(sr_analysis, current_price),
            # T3
            pattern_type=pattern.pattern_type.value if pattern else None,
            pattern_strength=pattern.formation_strength if pattern else 0,
            # T4
            trigger_confidence=trigger.confidence,
            candle_pattern=trigger.candlestick_pattern,
            stoch_signal=trigger.stochastic_signal,
        )

        return signal

    def _validate_t0_t1_alignment(self, trend_direction: str, wyckoff_phase: str) -> bool:
        """Gate: Trend must align with Wyckoff phase."""
        # Accumulation allows uptrend
        if wyckoff_phase == "Accumulation" and trend_direction == "uptrend":
            return True
        # Mark up requires uptrend
        if wyckoff_phase == "Mark Up" and trend_direction == "uptrend":
            return True
        # Mark down requires downtrend
        if wyckoff_phase == "Mark Down" and trend_direction == "downtrend":
            return True
        # Distribution allows downtrend
        if wyckoff_phase == "Distribution" and trend_direction == "downtrend":
            return True
        # Sideways can be anything
        if trend_direction == "sideways":
            return True

        return False

    def _validate_entry_with_sr(self, current_price: float, sr_analysis, direction: str) -> Tuple[bool, str]:
        """Gate: Entry price must be valid for direction."""
        # Long entries should be at support, not resistance
        if direction == "uptrend":
            if sr_analysis.strongest_support:
                zone_range = sr_analysis.strongest_support.price_high - sr_analysis.strongest_support.price_low
                tolerance = max(zone_range, sr_analysis.strongest_support.midpoint * 0.02)
                if abs(current_price - sr_analysis.strongest_support.midpoint) <= tolerance:
                    return True, "Price at support"
            return True, "Price valid for long"

        # Short entries should be at resistance, not support
        elif direction == "downtrend":
            if sr_analysis.strongest_resistance:
                zone_range = sr_analysis.strongest_resistance.price_high - sr_analysis.strongest_resistance.price_low
                tolerance = max(zone_range, sr_analysis.strongest_resistance.midpoint * 0.02)
                if abs(current_price - sr_analysis.strongest_resistance.midpoint) <= tolerance:
                    return True, "Price at resistance"
            return True, "Price valid for short"

        return True, "Price valid"

    def _validate_pattern_with_trend(self, pattern, structure, trend_direction: str) -> Tuple[bool, str]:
        """Gate: Pattern must confirm trend direction."""
        pattern_breakout = pattern.potential_breakout

        if trend_direction == "uptrend":
            if pattern_breakout in ["up", "bidirectional"]:
                return True, f"{pattern.pattern_type.value} confirms uptrend"
            return False, f"{pattern.pattern_type.value} contradicts uptrend"

        elif trend_direction == "downtrend":
            if pattern_breakout in ["down", "bidirectional"]:
                return True, f"{pattern.pattern_type.value} confirms downtrend"
            return False, f"{pattern.pattern_type.value} contradicts downtrend"

        return True, "Pattern valid for sideways"

    def _format_sr_info(self, sr_analysis, current_price: float) -> str:
        """Format S/R information for signal reasoning."""
        info = []

        if sr_analysis.strongest_support:
            info.append(f"Support: ${sr_analysis.strongest_support.midpoint:.2f} ({sr_analysis.strongest_support.num_bounces} bounces)")

        if sr_analysis.strongest_resistance:
            info.append(f"Resistance: ${sr_analysis.strongest_resistance.midpoint:.2f} ({sr_analysis.strongest_resistance.num_bounces} bounces)")

        if not info:
            return "No strong S/R zones"

        return " | ".join(info)
