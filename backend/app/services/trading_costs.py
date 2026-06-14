"""
Trading cost model — single source of truth for execution costs (§15.1).

Real round-trip cost on Binance spot is more than the taker fee:
  taker fee   : 0.10% per side  → 0.20% round-trip
  spread      : ~0.06% (taker buys at ask, sells at bid)
  slippage    : ~0.05% on market entries/stops for mid-cap alts

EXECUTION_COST_PCT is used UNIFORMLY in: scanner net-TP math, monitor P&L
netting, EV ranking, and breakeven placement. When going live, calibrate this
single number from real fills.
"""

# Spot (opportunity_spot)
SPOT_TAKER_FEE_PCT   = 0.10   # % per side (no BNB discount — conservative)
SPOT_SPREAD_PCT      = 0.06   # full-spread cost across round trip
SPOT_SLIPPAGE_PCT    = 0.05   # market-order slippage estimate

EXECUTION_COST_PCT   = round(SPOT_TAKER_FEE_PCT * 2 + SPOT_SPREAD_PCT + SPOT_SLIPPAGE_PCT, 2)  # 0.31 → use as-is

# Extra adverse slippage applied to STOP-LOSS fills only (market stop in a
# falling book fills worse than the trigger price). TP limit orders fill at
# their level — no slippage there.
SL_SLIPPAGE_PCT      = 0.10

# Futures paper trading — single source of truth (B8)
# Referenced by: futures_learning.py, monitor.py, balance.py
FUTURES_STARTING_BALANCE = 1_000.0   # paper wallet starting equity ($)
FUTURES_RISK_PCT         = 0.01      # 1% risk per trade (fixed-fractional)

# F15/F33: statuses that count toward WIN-RATE only.
# "expired" (stagnant/max-age closes) is EXCLUDED — not a real win/loss outcome.
FUTURES_CLOSED_STATUSES = ("tp", "sl")

# BUG-L19: statuses that count toward realized BALANCE / equity / drawdown.
# Expired trades DID move real money (esp. after a TP1 partial sell), so the wallet must
# include them — even though they're excluded from win-rate above.
FUTURES_BALANCE_STATUSES = ("tp", "sl", "expired")


def futures_notional(risk_pct: float | None) -> float:
    """F33: position notional ($) for a futures paper trade — single source of truth.
    Falls back to 2.0% risk when risk_pct is missing/invalid (matches legacy default)."""
    rp = risk_pct if (risk_pct and risk_pct > 0) else 2.0
    return FUTURES_STARTING_BALANCE * FUTURES_RISK_PCT / (rp / 100)


def futures_pnl_dollar(pnl_pct: float | None, risk_pct: float | None) -> float:
    """F33: realized $ P&L for a closed futures trade — single source of truth.
    Used identically by monitor (balance rebuild), learning stats, and risk dashboard."""
    return (pnl_pct or 0.0) / 100 * futures_notional(risk_pct)
