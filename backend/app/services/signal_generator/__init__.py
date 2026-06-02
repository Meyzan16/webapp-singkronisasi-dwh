"""
Signal generator module.

Combines T0-T4 analysis layers into unified trading signals.
"""

from .pipeline import SignalPipeline
from .risk_calculator import RiskCalculation, calculate_stop_loss, calculate_take_profit, calculate_risk_metrics
from .signal_card import SignalCard, build_signal_card, format_signal_to_json

__all__ = [
    "SignalPipeline",
    "RiskCalculation",
    "calculate_stop_loss",
    "calculate_take_profit",
    "calculate_risk_metrics",
    "SignalCard",
    "build_signal_card",
    "format_signal_to_json",
]
