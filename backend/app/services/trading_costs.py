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
