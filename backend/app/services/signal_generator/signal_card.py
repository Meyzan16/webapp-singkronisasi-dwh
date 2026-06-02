"""
Signal card output formatting.

Combines all T0-T4 analysis into a unified signal card output.
"""

from typing import Optional
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class SignalCard:
    """Complete trading signal with full reasoning chain."""

    pair: str
    timeframe: str
    direction: str  # "LONG" or "SHORT"
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: str  # "1:3.0" format
    confidence: float  # 0-100, weighted average
    phase: str  # Wyckoff phase
    t0_reasoning: str  # Wyckoff phase reasoning
    t1_reasoning: str  # Trend reasoning
    t2_reasoning: str  # S/R reasoning
    t3_reasoning: str  # Pattern reasoning
    t4_reasoning: str  # Trigger reasoning
    position_size_pct: float
    timestamp: str


def build_signal_card(
    pair: str,
    timeframe: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    rr_ratio: float,
    position_size_pct: float,
    # T0 - Wyckoff
    wyckoff_phase: str,
    wyckoff_confidence: float,
    # T1 - Trend
    trend_direction: str,
    trend_confidence: float,
    # T2 - S/R
    sr_zone_info: Optional[str] = None,
    # T3 - Pattern
    pattern_type: Optional[str] = None,
    pattern_strength: float = 0.0,
    # T4 - Trigger
    trigger_confidence: float = 0.0,
    candle_pattern: Optional[str] = None,
    stoch_signal: Optional[str] = None,
) -> SignalCard:
    """
    Build a complete signal card from all T0-T4 inputs.

    Returns a structured signal ready for JSON serialization.
    """
    # Determine direction (majority vote from phases)
    if entry_price > 0:  # Just use the direction from the highest confidence source
        direction = "LONG" if trend_direction == "uptrend" else "SHORT"
    else:
        direction = "LONG"

    # Build reasoning for each layer
    t0_reasoning = f"{wyckoff_phase}"
    if wyckoff_confidence > 0:
        t0_reasoning += f" (confidence: {wyckoff_confidence:.0f}%)"

    t1_reasoning = f"Trend: {trend_direction}"
    if trend_confidence > 0:
        t1_reasoning += f" (confidence: {trend_confidence:.0f}%)"

    t2_reasoning = sr_zone_info or "No strong S/R zones detected"

    t3_reasoning = pattern_type or "No clear pattern detected"
    if pattern_strength > 0:
        t3_reasoning += f" (strength: {pattern_strength:.0f}%)"

    t4_reasoning = "Trigger: "
    if candle_pattern:
        t4_reasoning += f"{candle_pattern}"
    if stoch_signal:
        t4_reasoning += f" + Stochastic {stoch_signal.upper()}"
    if trigger_confidence > 0:
        t4_reasoning += f" (confidence: {trigger_confidence:.0f}%)"

    # Calculate weighted confidence
    weights = {
        "T0": (wyckoff_confidence, 0.2),
        "T1": (trend_confidence, 0.2),
        "T2": (50, 0.15),  # S/R presence adds ~50% confidence
        "T3": (pattern_strength, 0.15),
        "T4": (trigger_confidence, 0.3),  # Trigger is most important
    }

    total_confidence = sum(score * weight for score, (_, weight) in weights.items() if weight)
    confidence = min(100.0, total_confidence)

    # Format R:R ratio
    rr_str = f"1:{rr_ratio:.1f}"

    # Create signal card
    signal = SignalCard(
        pair=pair,
        timeframe=timeframe,
        direction=direction,
        entry=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=rr_str,
        confidence=confidence,
        phase=wyckoff_phase,
        t0_reasoning=t0_reasoning,
        t1_reasoning=t1_reasoning,
        t2_reasoning=t2_reasoning,
        t3_reasoning=t3_reasoning,
        t4_reasoning=t4_reasoning,
        position_size_pct=position_size_pct,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )

    return signal


def format_signal_to_json(signal: SignalCard) -> dict:
    """Convert signal card to JSON-serializable dictionary."""
    return {
        "pair": signal.pair,
        "timeframe": signal.timeframe,
        "direction": signal.direction,
        "entry": round(signal.entry, 2),
        "stop_loss": round(signal.stop_loss, 2),
        "take_profit": round(signal.take_profit, 2),
        "risk_reward": signal.risk_reward,
        "confidence": round(signal.confidence, 0),
        "position_size_pct": round(signal.position_size_pct, 2),
        "reasoning": {
            "phase": signal.phase,
            "T0_wyckoff": signal.t0_reasoning,
            "T1_trend": signal.t1_reasoning,
            "T2_support_resistance": signal.t2_reasoning,
            "T3_pattern": signal.t3_reasoning,
            "T4_trigger": signal.t4_reasoning,
        },
        "timestamp": signal.timestamp,
    }
