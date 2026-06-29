"""
Shared TA math helpers for the futures agents.

F112: `_ema` and `_atr` were duplicated identically in agent1.py and regime.py.
Both now import from here so a formula change happens in one place only.

PLAN_v2 P1.2/P1.3: leverage sizing safety constants — single source of truth so
agent + monitor + risk_gate all reason about the same caps.
"""


# ── PLAN_v2 P1.3 — per-lane max margin loss at SL hit ─────────────────────────
# Tighter caps for lanes that hold longer (more black-swan window).
MAX_SL_MARGIN_PCT_BY_LANE: dict[str, float] = {
    "accumulation":  15.0,
    "pre_gainer":    18.0,
    "pre_move":      18.0,    # legacy alias
    "momentum":      25.0,
    "bigmover":      20.0,
}
DEFAULT_LANE_CAP = 25.0


# ── PLAN_v2 P1.2 — liquidation-safe sizing multiplier ─────────────────────────
# liq_dist_pct ≈ 95 / leverage (1% MMR). Require liq_dist ≥ SL_dist × SAFETY_MULT
# so a wick to SL never lands the trade inside liquidation territory.
LIQ_SAFETY_MULT = 2.0


def cap_leverage_by_lane(base_lev: int, risk_pct: float, lane: str = "momentum") -> int:
    """
    Apply two caps to a base leverage choice:
      1. Lane SL-margin cap   → L ≤ MAX_SL_MARGIN_PCT_LANE / risk_pct
      2. Liquidation safety   → L ≤ (95 / SAFETY_MULT) / risk_pct  = 47.5 / risk_pct
    Returns the smaller of the two (or `base_lev` when risk_pct is unknown).
    """
    if not risk_pct or risk_pct <= 0:
        return max(1, int(base_lev))

    lane_cap = MAX_SL_MARGIN_PCT_BY_LANE.get(lane, DEFAULT_LANE_CAP)
    sl_cap   = max(1, int(lane_cap / risk_pct))
    liq_cap  = max(1, int(95.0 / LIQ_SAFETY_MULT / risk_pct))   # = int(47.5 / risk_pct)
    return max(1, min(int(base_lev), sl_cap, liq_cap))


# ── PLAN_v2 P1.1 / P1.5 — per-lane max margin loss (live-monitor gate) ────────
# Stricter than the entry sizing caps because slippage past SL or regime-widened
# SL can blow through the static sizing assumption.
MAX_LOSS_PCT_OF_MARGIN_BY_LANE: dict[str, float] = {
    "accumulation":  35.0,
    "pre_gainer":    30.0,
    "pre_move":      30.0,    # legacy alias
    "momentum":      50.0,
    "bigmover":      40.0,
}
DEFAULT_MAX_LOSS_PCT = 50.0


# ── PLAN_v2 — agent style → lane mapping (used by monitor) ────────────────────
STYLE_TO_LANE: dict[str, str] = {
    "futures_agent1":          "pre_gainer",
    "futures_agent2":          "accumulation",
    "futures_agent3":          "momentum",
    "futures_agent_bigmover":  "bigmover",
}


def lane_for_style(style: str) -> str:
    return STYLE_TO_LANE.get(style, "momentum")


def _ema(values: list[float], period: int) -> float:
    """Exponential moving average of the last `period` values."""
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Average True Range over the last `period` candles."""
    if len(closes) < 2:
        return 0.0
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    tail = trs[-period:] if len(trs) >= period else trs
    return sum(tail) / len(tail) if tail else 0.0
