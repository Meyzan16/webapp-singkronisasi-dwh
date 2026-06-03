"""
Risk management and position sizing calculator.

Calculates stop loss, take profit, and validates R:R ratio.
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class RiskCalculation:
    """Complete risk calculation for a trade."""

    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float  # Distance from entry to SL
    reward_amount: float  # Distance from entry to TP
    risk_reward_ratio: float  # reward / risk (e.g. 3.0 = 1:3)
    is_valid: bool  # True if R:R >= 1:3
    position_size_pct: float  # Position size as % of capital (0-2%)
    reasoning: str  # Explanation of SL/TP placement


MIN_SL_PCT = {
    "long":  0.015,   # minimum 1.5% from entry for any long SL
    "short": 0.015,   # minimum 1.5% from entry for any short SL
}


def _enforce_min_sl(entry: float, sl: float, direction: str, min_pct: float = 0.015) -> float:
    """Ensure SL is at least min_pct away from entry to avoid stop-hunt zone."""
    dist = abs(entry - sl) / entry
    if dist < min_pct:
        if direction == "long":
            return entry * (1 - min_pct)
        else:
            return entry * (1 + min_pct)
    return sl


def calculate_stop_loss(
    entry_price: float,
    direction: str,  # "long" or "short"
    support_level: Optional[float] = None,
    resistance_level: Optional[float] = None,
    sr_zone: Optional[tuple[float, float]] = None,
    fib_level: Optional[float] = None,
    min_sl_pct: float = 0.015,   # minimum SL distance from entry
) -> float:
    """
    Calculate stop loss using priority order with minimum distance enforcement.

    Priority:
    1. Below strongest support area (most bounces) for long
    2. Below liquidity cluster (S/R zone)
    3. Below Fibonacci 0.618 level
    4. Default: 2% below entry for long, 2% above for short

    Always enforces minimum SL distance (default 1.5%) to prevent
    stop-hunt zone placement.
    """
    if direction == "long":
        candidates = []

        if support_level and support_level < entry_price:
            candidates.append(("support", support_level * 0.995))

        if sr_zone:
            candidates.append(("sr_zone", sr_zone[0] * 0.995))

        if fib_level and fib_level < entry_price:
            candidates.append(("fibonacci", fib_level * 0.995))

        if candidates:
            sl = max(candidates, key=lambda x: x[1])[1]
        else:
            sl = entry_price * 0.98

        return _enforce_min_sl(entry_price, sl, "long", min_sl_pct)

    else:  # short
        candidates = []

        if resistance_level and resistance_level > entry_price:
            candidates.append(("resistance", resistance_level * 1.005))

        if sr_zone:
            candidates.append(("sr_zone", sr_zone[1] * 1.005))

        if fib_level and fib_level > entry_price:
            candidates.append(("fibonacci", fib_level * 1.005))

        if candidates:
            sl = min(candidates, key=lambda x: x[1])[1]
        else:
            sl = entry_price * 1.02

        return _enforce_min_sl(entry_price, sl, "short", min_sl_pct)


def calculate_take_profit(
    entry_price: float,
    direction: str,  # "long" or "short"
    risk_amount: float,
    rr_ratio: float = 3.0,  # Target 1:3 risk:reward
) -> float:
    """
    Calculate take profit based on risk:reward ratio.

    Default target: 1:3 (3x the risk as reward).

    Args:
        entry_price: Entry price
        direction: "long" or "short"
        risk_amount: Distance from entry to stop loss
        rr_ratio: Desired risk:reward ratio

    Returns:
        Take profit price
    """
    reward_distance = risk_amount * rr_ratio

    if direction == "long":
        return entry_price + reward_distance
    else:  # short
        return entry_price - reward_distance


def calculate_risk_metrics(
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    direction: str,  # "long" or "short"
) -> RiskCalculation:
    """
    Calculate complete risk metrics and validate R:R ratio.

    Rules:
    - Minimum R:R = 1:3 (reward >= risk * 3)
    - Max daily loss = 3% of capital
    - Risk per trade = 1-2% of capital

    Returns:
        RiskCalculation with all metrics
    """
    # Calculate distances
    if direction == "long":
        risk_amount = entry_price - stop_loss
        reward_amount = take_profit - entry_price
    else:  # short
        risk_amount = stop_loss - entry_price
        reward_amount = entry_price - take_profit

    # Validate risk is positive
    if risk_amount <= 0:
        return RiskCalculation(
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=0,
            reward_amount=0,
            risk_reward_ratio=0,
            is_valid=False,
            position_size_pct=0,
            reasoning="Invalid SL: risk amount <= 0",
        )

    # Calculate R:R ratio
    rr_ratio = reward_amount / risk_amount if risk_amount > 0 else 0

    # Validate R:R >= 1:3
    is_valid = rr_ratio >= 3.0

    # Position sizing (risk 1% of capital per trade)
    position_size_pct = 1.0  # 1% risk per trade

    reasoning = f"Entry: {entry_price:.2f} | SL: {stop_loss:.2f} | TP: {take_profit:.2f} | R:R: 1:{rr_ratio:.1f}"
    if not is_valid:
        reasoning += f" (fails 1:3 minimum)"

    return RiskCalculation(
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_amount=risk_amount,
        reward_amount=reward_amount,
        risk_reward_ratio=rr_ratio,
        is_valid=is_valid,
        position_size_pct=position_size_pct,
        reasoning=reasoning,
    )


def validate_risk_rules(
    risk_calc: RiskCalculation,
    daily_loss_pct: float = 0.0,  # Current daily loss %
    max_daily_loss_pct: float = 3.0,  # Max allowed
) -> tuple[bool, str]:
    """
    Validate trade against all risk rules.

    Rules:
    1. R:R must be >= 1:3
    2. Risk per trade must be 1-2%
    3. Total daily loss must not exceed 3%

    Returns:
        (is_valid, reason)
    """
    # Rule 1: R:R ratio
    if risk_calc.risk_reward_ratio < 3.0:
        return False, f"R:R {risk_calc.risk_reward_ratio:.1f} < 1:3 minimum"

    # Rule 2: Position size
    if risk_calc.position_size_pct < 0.5 or risk_calc.position_size_pct > 2.0:
        return False, f"Position size {risk_calc.position_size_pct:.1f}% outside 0.5-2% range"

    # Rule 3: Daily loss limit
    if daily_loss_pct + risk_calc.position_size_pct > max_daily_loss_pct:
        return (
            False,
            f"Daily loss ({daily_loss_pct + risk_calc.position_size_pct:.1f}%) would exceed {max_daily_loss_pct}% limit",
        )

    return True, "All risk rules passed"
