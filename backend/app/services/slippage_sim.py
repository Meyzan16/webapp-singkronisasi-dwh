"""
Volume-parameterized entry slippage simulator — B4.1 + G19.

Replaces the hardcoded 0.3-0.5% constant with a tier based on 24h quote volume
(liquidity proxy) and a time-of-day multiplier (G19).

Volume tiers (B4.1):
  >$100M  24h vol → 0.10%   (top-tier liquid; BTCUSDT / ETHUSDT range)
  $10-100M        → 0.20%
  $1-10M          → 0.40%
  <$1M            → 0.70%   (illiquid; wide spread, high impact)

G19 time-of-day multiplier (UTC):
  Asian (00:00-07:00) → 1.5×   (thin book, wide spread)
  EU    (07:00-15:00) → 1.0×   (reference session)
  US    (15:00-23:59) → 0.8×   (deepest global liquidity)

Usage:
    from app.services.slippage_sim import calculate_entry_slippage

    slip = calculate_entry_slippage(quote_vol_24h=ticker["quoteVolume"])
    eff_entry = price * (1 + slip/100)   # LONG — buy at worse fill
"""

import time
from typing import Optional

# Volume tier breakpoints → base slippage %
_VOL_TIERS: list[tuple[float, float]] = [
    (100_000_000, 0.10),   # >$100M
    (10_000_000,  0.20),   # $10M-$100M
    (1_000_000,   0.40),   # $1M-$10M
    (0.0,         0.70),   # <$1M
]

# UTC hour ranges → multiplier (G19)
_SESSION_MULT: list[tuple[int, int, float]] = [
    (0,   7,  1.5),   # Asian: 00:00-07:00 UTC
    (7,  15,  1.0),   # EU:    07:00-15:00 UTC
    (15, 24,  0.8),   # US:    15:00-23:59 UTC
]


def _session_multiplier(utc_hour: Optional[int] = None) -> float:
    h = utc_hour if utc_hour is not None else int(time.gmtime().tm_hour)
    for start, end, mult in _SESSION_MULT:
        if start <= h < end:
            return mult
    return 1.0


def calculate_entry_slippage(
    quote_vol_24h: float,
    utc_hour: Optional[int] = None,
) -> float:
    """
    Return estimated entry slippage % for a market order on this symbol.

    Args:
        quote_vol_24h: 24h USDT quote volume from Binance ticker (raw number).
                       Pass 0 to fall back to the $1-10M tier (0.40% base).
        utc_hour:      override UTC hour for testing; None = current system time.

    Returns:
        Slippage as a percentage, e.g. 0.20 means 0.20% adverse vs mid-price.
        Clamped to [0.05, 1.00].
    """
    base = 0.40   # default: mid-tier if vol unknown
    for threshold, pct in _VOL_TIERS:
        if quote_vol_24h >= threshold:
            base = pct
            break

    result = base * _session_multiplier(utc_hour)
    return round(max(0.05, min(1.0, result)), 4)


def get_session_label(utc_hour: Optional[int] = None) -> str:
    """Human-readable trading session name for logging."""
    h = utc_hour if utc_hour is not None else int(time.gmtime().tm_hour)
    if h < 7:
        return "Asian"
    if h < 15:
        return "EU"
    return "US"
