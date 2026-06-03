"""
Order Flow Analysis (T5 layer).

Analyzes buying/selling pressure using:
- Volume Delta (bullish vs bearish candle volume)
- CVD (Cumulative Volume Delta)
- Volume spike detection
- OBV (On-Balance Volume)
- Buy/Sell pressure ratio
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderFlowState:
    """Complete order flow analysis result."""
    signal: str                  # "strong_buy" | "buy" | "neutral" | "sell" | "strong_sell"
    direction: str               # "bullish" | "bearish" | "neutral"
    volume_delta: float          # last candle: buy_vol - sell_vol (approx)
    cvd_slope: str               # "rising" | "falling" | "flat" — trend of CVD
    volume_spike: bool           # last candle volume > 2x avg
    volume_ratio: float          # last / avg20 volume ratio
    buy_pressure: float          # 0–100, % of bullish volume in last 20 candles
    obv_trend: str               # "up" | "down" | "flat"
    large_candle: bool           # last candle body > 1.5x avg body
    description: str


def _approx_volume_delta(opens: list, closes: list, volumes: list) -> list[float]:
    """
    Approximate buy/sell volume delta per candle.
    Bullish candle (close > open) → mostly buying.
    Bearish candle → mostly selling.
    Uses candle body ratio for approximation.
    """
    deltas = []
    for o, c, v in zip(opens, closes, volumes):
        if c >= o:
            # Bullish: estimate buy vol proportional to close position in range
            delta = v * (c - o) / (c - o + 0.000001)
        else:
            delta = -v * (o - c) / (o - c + 0.000001)
        deltas.append(delta)
    return deltas


def _calc_obv(closes: list, volumes: list) -> list[float]:
    """On-Balance Volume."""
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def analyze_order_flow(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    lookback: int = 20,
) -> Optional[OrderFlowState]:
    """
    Analyze order flow for T5 layer.

    Returns OrderFlowState with signal, direction, and all metrics.
    """
    if len(closes) < lookback + 5:
        return None

    recent_o = opens[-lookback:]
    recent_c = closes[-lookback:]
    recent_v = volumes[-lookback:]
    recent_h = highs[-lookback:]
    recent_l = lows[-lookback:]

    # ── Volume metrics ─────────────────────────────────────────────────────────
    avg_vol = sum(recent_v[:-1]) / max(len(recent_v) - 1, 1)
    last_vol = recent_v[-1]
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0
    vol_spike = vol_ratio > 2.0

    # ── Volume delta ───────────────────────────────────────────────────────────
    deltas = _approx_volume_delta(recent_o, recent_c, recent_v)
    last_delta = deltas[-1]

    # CVD slope: compare sum of last 5 vs previous 5
    cvd = []
    running = 0.0
    for d in deltas:
        running += d
        cvd.append(running)

    cvd_recent = sum(deltas[-5:])
    cvd_prev = sum(deltas[-10:-5])
    if cvd_recent > cvd_prev * 1.1:
        cvd_slope = "rising"
    elif cvd_recent < cvd_prev * 0.9:
        cvd_slope = "falling"
    else:
        cvd_slope = "flat"

    # ── Buy pressure ───────────────────────────────────────────────────────────
    bull_vol = sum(v for o, c, v in zip(recent_o, recent_c, recent_v) if c >= o)
    total_vol = sum(recent_v) or 1
    buy_pressure = bull_vol / total_vol * 100

    # ── OBV trend ──────────────────────────────────────────────────────────────
    obv = _calc_obv(list(closes[-lookback:]), list(volumes[-lookback:]))
    if len(obv) >= 6:
        obv_slope = obv[-1] - obv[-6]
        obv_trend = "up" if obv_slope > 0 else ("down" if obv_slope < 0 else "flat")
    else:
        obv_trend = "flat"

    # ── Large candle ───────────────────────────────────────────────────────────
    bodies = [abs(c - o) for o, c in zip(recent_o, recent_c)]
    avg_body = sum(bodies[:-1]) / max(len(bodies) - 1, 1)
    last_body = bodies[-1]
    large_candle = last_body > avg_body * 1.5

    # ── Signal scoring ─────────────────────────────────────────────────────────
    score = 0

    # CVD
    if cvd_slope == "rising":
        score += 2
    elif cvd_slope == "falling":
        score -= 2

    # Buy pressure
    if buy_pressure > 65:
        score += 2
    elif buy_pressure > 55:
        score += 1
    elif buy_pressure < 35:
        score -= 2
    elif buy_pressure < 45:
        score -= 1

    # OBV
    if obv_trend == "up":
        score += 1
    elif obv_trend == "down":
        score -= 1

    # Volume spike with direction
    if vol_spike:
        last_is_bull = closes[-1] >= opens[-1]
        score += 2 if last_is_bull else -2

    # Last delta
    if last_delta > 0 and large_candle:
        score += 1
    elif last_delta < 0 and large_candle:
        score -= 1

    # ── Map score to signal ────────────────────────────────────────────────────
    if score >= 4:
        signal = "strong_buy"
        direction = "bullish"
    elif score >= 2:
        signal = "buy"
        direction = "bullish"
    elif score <= -4:
        signal = "strong_sell"
        direction = "bearish"
    elif score <= -2:
        signal = "sell"
        direction = "bearish"
    else:
        signal = "neutral"
        direction = "neutral"

    # ── Description ────────────────────────────────────────────────────────────
    parts = []
    parts.append(f"Vol {vol_ratio:.1f}x avg" + (" 🔥" if vol_spike else ""))
    parts.append(f"Buy pressure {buy_pressure:.0f}%")
    parts.append(f"CVD {cvd_slope}")
    parts.append(f"OBV {obv_trend}")
    if large_candle:
        parts.append("Large candle")

    return OrderFlowState(
        signal=signal,
        direction=direction,
        volume_delta=round(last_delta, 2),
        cvd_slope=cvd_slope,
        volume_spike=vol_spike,
        volume_ratio=round(vol_ratio, 2),
        buy_pressure=round(buy_pressure, 1),
        obv_trend=obv_trend,
        large_candle=large_candle,
        description=" | ".join(parts),
    )
