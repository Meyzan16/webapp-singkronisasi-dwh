"""
Agent 2 — T0-T4 Experience Futures Scanner.

Based on the proven T0-T4 analysis pipeline:
  T0 Wyckoff  → Accumulation (LONG) vs Distribution (SHORT)
  T1 Trend    → EMA alignment confirms direction
  T2 S/R      → Entry at key zones
  T3 Pattern  → BB Squeeze, Vol, Candle shrink
  T4 Trigger  → RSI + Pressure shift + final confirmation

LONG  → Wyckoff accumulation + uptrend + near support + bullish trigger
SHORT → Wyckoff distribution + downtrend + near resistance + bearish trigger

Min score: 55  |  Min R:R: 1:3  |  Leverage: dynamic
"""

import math
from typing import Optional

import structlog

from .data import FuturesData
from .agent1 import (
    _ema, _rsi, _atr, _swing_lows, _swing_highs,
    _round_price, calc_leverage,
)

logger = structlog.get_logger(__name__)

MIN_SCORE  = 55
MIN_RR     = 3.0
AGENT_NAME = "futures_agent2"


# ── T0: Wyckoff Phase Detection ────────────────────────────────────────────────

def _wyckoff_phase(closes: list[float], volumes: list[float], lows: list[float]) -> str:
    """
    Simplified Wyckoff phase detection.
    Returns: 'accumulation' | 'markup' | 'distribution' | 'markdown' | 'neutral'
    """
    if len(closes) < 30 or len(volumes) < 30:
        return "neutral"

    # Recent 15 vs prior 15 candles
    mid = len(closes) // 2
    recent_closes  = closes[mid:]
    prior_closes   = closes[:mid]
    recent_vols    = volumes[mid:]
    prior_vols     = volumes[:mid]

    price_change   = (recent_closes[-1] - prior_closes[0]) / prior_closes[0]
    avg_vol_recent = sum(recent_vols) / len(recent_vols)
    avg_vol_prior  = sum(prior_vols)  / len(prior_vols)
    vol_expansion  = avg_vol_recent / avg_vol_prior if avg_vol_prior > 0 else 1.0

    # Price range compression (accumulation/distribution zone)
    recent_range = (max(recent_closes) - min(recent_closes)) / recent_closes[0]
    prior_range  = (max(prior_closes)  - min(prior_closes))  / prior_closes[0]
    is_compressed = recent_range < prior_range * 0.6

    if is_compressed and vol_expansion > 1.2 and price_change < 0.02:
        return "accumulation"      # vol expanding while price flat → smart money buying
    elif price_change > 0.03 and vol_expansion > 1.0:
        return "markup"            # price rising with volume confirmation
    elif is_compressed and vol_expansion > 1.1 and price_change > -0.02:
        return "distribution"      # vol expanding while price flat at highs
    elif price_change < -0.03 and vol_expansion > 1.0:
        return "markdown"          # price falling with volume
    return "neutral"


# ── T1: Trend Detection ────────────────────────────────────────────────────────

def _trend(closes: list[float]) -> str:
    """EMA-based trend: 'up' | 'down' | 'sideways'."""
    if len(closes) < 50:
        return "sideways"
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)

    if ema9 > ema21 > ema50:
        return "up"
    if ema9 < ema21 < ema50:
        return "down"
    return "sideways"


# ── T3: Pattern Signals ────────────────────────────────────────────────────────

def _bb_width(closes: list[float], period: int = 20) -> float:
    if len(closes) < period:
        return 1.0
    tail = closes[-period:]
    mean = sum(tail) / period
    std  = math.sqrt(sum((v - mean) ** 2 for v in tail) / period)
    return (std * 4) / mean if mean > 0 else 1.0


def _vol_ratio(volumes: list[float]) -> float:
    if len(volumes) < 21:
        return 1.0
    avg = sum(volumes[-21:-1]) / 20
    return volumes[-1] / avg if avg > 0 else 1.0


def _candle_compression(opens: list[float], closes: list[float], n: int = 7) -> bool:
    """True if candle bodies are shrinking (indecision / coil before move)."""
    if len(closes) < n + 1:
        return False
    bodies = [abs(closes[i] - opens[i]) for i in range(-n, 0)]
    return bodies[-1] < bodies[0] * 0.5


# ── T4: Trigger Signals ────────────────────────────────────────────────────────

def _pressure_shift(opens: list[float], closes: list[float], volumes: list[float], n: int = 5) -> float:
    """Bull ratio shift: positive = buying pressure increasing."""
    if len(opens) < n * 2:
        return 0.0
    def bull_ratio(o, c, v):
        total = sum(v) or 1
        return sum(v[i] for i in range(len(v)) if c[i] >= o[i]) / total

    now  = bull_ratio(opens[-n:],      closes[-n:],      volumes[-n:])
    prev = bull_ratio(opens[-n*2:-n],  closes[-n*2:-n],  volumes[-n*2:-n])
    return now - prev


# ── Score direction ────────────────────────────────────────────────────────────

def _score_direction(
    direction: str,
    tf_map: dict[str, FuturesData],
    price: float,
    change_24h: float,
) -> tuple[float, list[str]]:
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref  = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── T0: Wyckoff (0-25 pts) ────────────────────────────────────────────────
    phase = _wyckoff_phase(ref.closes, ref.volumes, ref.lows)

    if direction == "LONG":
        if phase == "accumulation":
            score += 25
            signals.append("📦 Wyckoff Accumulation — smart money buying diam-diam")
        elif phase == "markup":
            score += 15
            signals.append("📈 Wyckoff Markup — trend naik terkonfirmasi")
    else:  # SHORT
        if phase == "distribution":
            score += 25
            signals.append("📤 Wyckoff Distribution — smart money selling diam-diam")
        elif phase == "markdown":
            score += 15
            signals.append("📉 Wyckoff Markdown — trend turun terkonfirmasi")

    # ── T1: Trend (0-20 pts) ──────────────────────────────────────────────────
    trend_ok = False
    for tf_key in ["4h", "1h", "15m"]:
        d = tf_map.get(tf_key)
        if not d or len(d.closes) < 50:
            continue
        t = _trend(d.closes)
        if direction == "LONG" and t == "up":
            score += 20 if tf_key == "4h" else 12
            signals.append(f"⚡ Uptrend terkonfirmasi ({tf_key}) — EMA9>21>50")
            trend_ok = True
            break
        elif direction == "SHORT" and t == "down":
            score += 20 if tf_key == "4h" else 12
            signals.append(f"⚡ Downtrend terkonfirmasi ({tf_key}) — EMA9<21<50")
            trend_ok = True
            break

    if not trend_ok:
        score -= 5   # no trend confirmation → reduce confidence

    # ── T2: S/R Zones (0-15 pts) ─────────────────────────────────────────────
    for tf_key, d in tf_map.items():
        if not d.lows or not d.highs:
            continue
        s_lows  = _swing_lows(d.lows, lookback=5)
        s_highs = _swing_highs(d.highs, lookback=5)

        if direction == "LONG":
            near = [s for s in s_lows if 0 < (price - s) / price < 0.02]
            if near:
                score += 15
                signals.append(f"🎯 Near support {tf_key} ({len(near)} zona) — area beli ideal")
                break
        else:
            near = [r for r in s_highs if 0 < (r - price) / price < 0.02]
            if near:
                score += 15
                signals.append(f"🎯 Near resistance {tf_key} ({len(near)} zona) — area jual ideal")
                break

    # ── T3: Pattern Signals (0-20 pts) ───────────────────────────────────────
    for tf_key, d in tf_map.items():
        if not d.closes:
            continue
        bb_w    = _bb_width(d.closes)
        vol_r   = _vol_ratio(d.volumes)
        candle_c = _candle_compression(d.opens, d.closes)

        bb_squeeze = (bb_w < 0.04 and tf_key == "1h") or (bb_w < 0.03 and tf_key == "15m")

        if bb_squeeze:
            score += 10
            signals.append(f"🔵 BB Squeeze ({tf_key}) — energi terkompresi, breakout mendekat")
        if vol_r > 1.8 and abs(
            (d.closes[-1] - d.closes[-5]) / (d.closes[-5] or 1)
        ) < 0.03:
            score += 7
            signals.append(f"📦 Volume {vol_r:.1f}x saat harga konsolidasi — akumulasi")
        if candle_c:
            score += 3
        break  # only use primary TF (1h preferred)

    # ── T4: Trigger (0-20 pts) ───────────────────────────────────────────────
    for tf_key, d in tf_map.items():
        if not d.closes:
            continue
        rsi      = _rsi(d.closes, 14)
        pressure = _pressure_shift(d.opens, d.closes, d.volumes)

        if direction == "LONG":
            if rsi < 35:
                score += 10
                signals.append(f"RSI({tf_key}) {rsi:.0f} — oversold, trigger reversal")
            elif rsi < 50:
                score += 5
            if pressure > 0.20:
                score += 10
                signals.append(f"🟢 Buy pressure +{pressure*100:.0f}% — momentum membalik")
            elif pressure > 0.10:
                score += 5
        else:  # SHORT
            if rsi > 70:
                score += 10
                signals.append(f"RSI({tf_key}) {rsi:.0f} — overbought, trigger koreksi")
            elif rsi > 55:
                score += 5
            if pressure < -0.20:
                score += 10
                signals.append(f"🔴 Sell pressure {pressure*100:.0f}% — momentum membalik")
            elif pressure < -0.10:
                score += 5
        break  # primary TF only

    # Penalty: extreme 24h move (likely already played out)
    if abs(change_24h) > 20:
        score -= 15
        signals.append(f"⚠️ Sudah bergerak {change_24h:.1f}% — entry terlambat?")

    return score, [s for s in signals if not s.startswith("⚠️")][:5]


# ── Trade levels (reuse Agent 1 logic) ────────────────────────────────────────

def _calc_levels(direction: str, tf_map: dict[str, FuturesData], price: float) -> Optional[dict]:
    from .agent1 import _calc_levels as a1_levels
    return a1_levels(direction, tf_map, price)


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_symbol(
    symbol: str,
    tf_map: dict[str, FuturesData],
    change_24h: float,
) -> Optional[dict]:
    """Evaluate symbol for Agent 2 (T0-T4). Returns best direction or None."""
    if not tf_map:
        return None

    ref   = tf_map.get("1h") or tf_map.get("4h") or next(iter(tf_map.values()))
    price = ref.closes[-1] if ref.closes else 0.0
    if price <= 0:
        return None

    long_score,  long_sigs  = _score_direction("LONG",  tf_map, price, change_24h)
    short_score, short_sigs = _score_direction("SHORT", tf_map, price, change_24h)

    if long_score >= short_score and long_score >= MIN_SCORE:
        direction, score, signals = "LONG",  long_score,  long_sigs
    elif short_score > long_score and short_score >= MIN_SCORE:
        direction, score, signals = "SHORT", short_score, short_sigs
    else:
        return None

    levels = _calc_levels(direction, tf_map, price)
    if not levels:
        return None

    atr_pct  = levels.pop("atr_pct")
    leverage = calc_leverage(atr_pct, score)

    return {
        "symbol":     symbol,
        "direction":  direction,
        "price":      round(price, 8),
        "score":      round(min(score, 99), 1),
        "signals":    signals,
        "leverage":   leverage,
        "change_24h": round(change_24h, 2),
        "funding_rate": round(ref.funding_rate * 100, 4),
        "oi_change":  round(ref.oi_change_pct, 2),
        "liq_long":   round(ref.liq_long_usdt / 1e6, 2),
        "liq_short":  round(ref.liq_short_usdt / 1e6, 2),
        "agent":      AGENT_NAME,
        **levels,
    }
