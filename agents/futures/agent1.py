"""
Agent 1 — AI Knowledge Futures Scanner.

Strategy:
  LONG  → buy at support + funding bearish bias + OI confirms + RSI < 50
  SHORT → sell at resistance + funding bullish bias + OI confirms + RSI > 55

Signals (scored 0-100):
  Funding Rate:        0-25 pts  (strongest Futures signal — market sentiment)
  OI Divergence:       0-20 pts  (smart money vs price divergence)
  Liquidation data:    0-15 pts  (cascade = capitulation reversal)
  S/R Confluence:      0-20 pts  (multi-TF zone alignment)
  Technical TA:        0-20 pts  (RSI + EMA + volume)

Min score: 55  |  Min R:R: 1:3  |  Leverage: dynamic (ATR-based)
"""

import math
import time
from typing import Optional

import structlog

from .data import FuturesData

logger = structlog.get_logger(__name__)

MIN_SCORE  = 45   # lowered from 55: liquidation data (15pts) unavailable without API key
MIN_RR     = 3.0
AGENT_NAME = "futures_agent1"


# ── Math helpers ──────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    return 100 - (100 / (1 + ag / al)) if al > 0 else 100.0


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
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


def _swing_highs(highs: list[float], lookback: int = 5) -> list[float]:
    pivots = []
    for i in range(lookback, len(highs) - lookback):
        window = highs[i - lookback: i + lookback + 1]
        if highs[i] >= max(window):
            pivots.append(highs[i])
    return sorted(set(pivots))


def _swing_lows(lows: list[float], lookback: int = 5) -> list[float]:
    pivots = []
    for i in range(lookback, len(lows) - lookback):
        window = lows[i - lookback: i + lookback + 1]
        if lows[i] <= min(window):
            pivots.append(lows[i])
    return sorted(set(pivots))


def _rsi_divergence(closes: list[float], period: int = 14) -> str:
    """
    Detect RSI divergence over last 20 candles.
    Returns: 'bullish' | 'bearish' | 'none'
    Bullish: price makes lower low, RSI makes higher low.
    Bearish: price makes higher high, RSI makes lower high.
    """
    if len(closes) < 30:
        return "none"
    mid     = len(closes) // 2
    prev_p  = min(closes[:mid])
    curr_p  = min(closes[mid:])
    prev_rsi = _rsi(closes[:mid + period], period)
    curr_rsi = _rsi(closes[mid:], period)

    if curr_p < prev_p and curr_rsi > prev_rsi:
        return "bullish"   # price lower, RSI higher → hidden strength

    prev_high = max(closes[:mid])
    curr_high = max(closes[mid:])
    if curr_high > prev_high and curr_rsi < prev_rsi:
        return "bearish"   # price higher, RSI lower → hidden weakness

    return "none"


def _round_price(price: float, ref: float) -> float:
    if ref >= 1000:  return round(price, 2)
    if ref >= 10:    return round(price, 4)
    if ref >= 0.1:   return round(price, 5)
    if ref >= 0.001: return round(price, 7)
    return round(price, 8)


# ── Leverage calculator ───────────────────────────────────────────────────────

def calc_leverage(atr_pct: float, score: float) -> int:
    """
    Dynamic leverage based on volatility (ATR%) and signal confidence (score).
    Higher volatility = lower leverage (protect capital).
    Higher score = slightly more leverage (more confident).
    """
    if atr_pct > 5.0:   base = 2
    elif atr_pct > 3.0: base = 3
    elif atr_pct > 2.0: base = 5
    elif atr_pct > 1.0: base = 7
    else:               base = 10

    # Confidence boost (max +3x)
    if score >= 80:   base = min(base + 3, 15)
    elif score >= 70: base = min(base + 2, 12)
    elif score >= 60: base = min(base + 1, 10)

    return base


# ── Signal scoring ────────────────────────────────────────────────────────────

def _score_direction(
    direction: str,     # "LONG" or "SHORT"
    tf_map: dict[str, FuturesData],
    price: float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """Score a specific direction for this symbol. Returns (score, signals)."""
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref  = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── 1. Funding Rate (0-25 pts) ──────────────────────────────────────────
    fr = ref.funding_rate
    fr_avg = ref.funding_rate_avg

    if direction == "LONG":
        if fr < -0.03 / 100:          # shorts paying heavily → squeeze coming
            score += 25
            signals.append(f"🔴 Funding {fr*100:.3f}% — short squeeze likely")
        elif fr < 0:
            score += 12
            signals.append(f"Funding {fr*100:.3f}% negatif — bias bullish")
        elif fr > 0.10 / 100:         # longs overpaying → bad for long
            score -= 10
    else:  # SHORT
        if fr > 0.10 / 100:           # longs overpaying → correction coming
            score += 25
            signals.append(f"🟢 Funding +{fr*100:.3f}% — long squeeze likely")
        elif fr > 0.05 / 100:
            score += 12
            signals.append(f"Funding +{fr*100:.3f}% tinggi — bias bearish")
        elif fr < 0:                  # shorts paying → bad for short
            score -= 8

    # ── 2. OI Divergence (0-20 pts) ──────────────────────────────────────────
    oi_chg = ref.oi_change_pct

    if direction == "LONG":
        if oi_chg > 2 and change_24h < -1.5:   # OI rising + price falling = short trap
            score += 20
            signals.append(f"📊 OI +{oi_chg:.1f}% saat harga turun — short trap setup")
        elif oi_chg > 1 and change_24h < -1:    # moderate OI rise with price drop
            score += 12
            signals.append(f"OI +{oi_chg:.1f}% saat harga terkoreksi — potential reversal")
        elif oi_chg > 1 and change_24h > 0:     # OI rising + price rising = trend confirm
            score += 8
            signals.append(f"OI +{oi_chg:.1f}% konfirmasi momentum naik")
        elif oi_chg < -2:                        # OI falling = long capitulation
            score -= 8
    else:  # SHORT
        if oi_chg > 2 and change_24h > 1.5:    # OI rising + price rising = long trap
            score += 20
            signals.append(f"📊 OI +{oi_chg:.1f}% saat harga naik — long trap setup")
        elif oi_chg > 1 and change_24h > 1:     # moderate rise with price up
            score += 12
            signals.append(f"OI +{oi_chg:.1f}% saat harga naik — potential rejection")
        elif oi_chg > 1 and change_24h < 0:     # OI rising + price falling = trend confirm
            score += 8
            signals.append(f"OI +{oi_chg:.1f}% konfirmasi tekanan jual")
        elif oi_chg < -2:                        # OI falling = short capitulation
            score -= 8

    # ── 3. Liquidation Cascade (0-15 pts) ────────────────────────────────────
    liq_long  = ref.liq_long_usdt
    liq_short = ref.liq_short_usdt

    if direction == "LONG" and liq_long > 500_000:
        # Large long liquidation = capitulation → potential reversal up
        score += 15
        signals.append(f"💥 Likuidasi LONG ${liq_long/1e6:.1f}M — potensi reversal naik")
    elif direction == "SHORT" and liq_short > 500_000:
        # Large short liquidation = potential reversal down after exhaustion
        score += 15
        signals.append(f"💥 Likuidasi SHORT ${liq_short/1e6:.1f}M — potensi reversal turun")
    elif direction == "LONG" and liq_short > 200_000:
        score += 5   # shorts being squeezed = bullish pressure
    elif direction == "SHORT" and liq_long > 200_000:
        score += 5

    # ── 4. S/R Confluence (0-20 pts) ─────────────────────────────────────────
    support_score    = 0
    resistance_score = 0
    sr_signal        = ""

    for tf_key, d in tf_map.items():
        if not d.lows or not d.highs:
            continue
        s_lows  = _swing_lows(d.lows, lookback=5)
        s_highs = _swing_highs(d.highs, lookback=5)

        # Near support (within 1.5%)?
        near_sup = [s for s in s_lows if 0 < (price - s) / price < 0.015]
        # Near resistance (within 1.5%)?
        near_res = [r for r in s_highs if 0 < (r - price) / price < 0.015]

        if near_sup:
            support_score += 7
            sr_signal = f"📍 Near support {tf_key} — zona beli kuat"
        if near_res:
            resistance_score += 7
            sr_signal = f"📍 Near resistance {tf_key} — zona jual kuat"

    if direction == "LONG":
        score += min(support_score, 20)
        if support_score >= 7:
            signals.append(sr_signal or "Support zone teridentifikasi multi-TF")
    else:
        score += min(resistance_score, 20)
        if resistance_score >= 7:
            signals.append(sr_signal or "Resistance zone teridentifikasi multi-TF")

    # ── 5. Technical TA (0-20 pts) ───────────────────────────────────────────
    for tf_key, d in tf_map.items():
        if not d.closes:
            continue
        rsi  = _rsi(d.closes, 14)
        ema9 = _ema(d.closes, 9)
        ema21 = _ema(d.closes, 21)
        div  = _rsi_divergence(d.closes)

        if direction == "LONG":
            if rsi < 35:
                score += 8
                signals.append(f"RSI({tf_key}) {rsi:.0f} — oversold, potensi reversal")
                break
            elif rsi < 50:
                score += 5
                break
        else:  # SHORT
            if rsi > 70:
                score += 8
                signals.append(f"RSI({tf_key}) {rsi:.0f} — overbought, rawan koreksi")
                break
            elif rsi > 55:
                score += 5
                break

    # EMA alignment
    long_ema = all(
        _ema(d.closes, 9) > _ema(d.closes, 21)
        for d in tf_map.values() if len(d.closes) >= 21
    )
    short_ema = all(
        _ema(d.closes, 9) < _ema(d.closes, 21)
        for d in tf_map.values() if len(d.closes) >= 21
    )

    if direction == "LONG" and long_ema:
        score += 7
        signals.append("EMA9 > EMA21 semua TF — momentum bullish terkonfirmasi")
    elif direction == "SHORT" and short_ema:
        score += 7
        signals.append("EMA9 < EMA21 semua TF — momentum bearish terkonfirmasi")

    # RSI divergence bonus
    if direction == "LONG" and div == "bullish":
        score += 5
        signals.append("🔵 Bullish RSI divergence — hidden strength")
    elif direction == "SHORT" and div == "bearish":
        score += 5
        signals.append("🔴 Bearish RSI divergence — hidden weakness")

    return score, signals[:5]


# ── Trade levels ──────────────────────────────────────────────────────────────

def _calc_levels(
    direction: str,
    tf_map: dict[str, FuturesData],
    price: float,
) -> Optional[dict]:
    """
    Calculate Entry / SL / TP1 / TP2 / TP3 for Futures trade.

    LONG:
      Entry = current price
      SL    = below nearest swing low (1H) + ATR buffer
      TP1   = R:R 1:1.5, TP2 = nearest resistance, TP3 = R:R 1:5

    SHORT:
      Entry = current price
      SL    = above nearest swing high (1H) + ATR buffer
      TP1   = R:R 1:1.5, TP2 = nearest support, TP3 = R:R 1:5
    """
    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    if not d1h or len(d1h.closes) < 20:
        return None

    atr       = _atr(d1h.highs, d1h.lows, d1h.closes, 14)
    atr_pct   = atr / price * 100 if price > 0 else 0
    rp        = _round_price

    if direction == "LONG":
        s_lows    = _swing_lows(d1h.lows, lookback=5)
        below     = [s for s in s_lows if s < price * 0.999]
        swing_sl  = max(below) if below else min(d1h.lows[-20:])
        sl        = swing_sl - atr * 0.3
        risk      = price - sl
        risk_pct  = risk / price * 100

        if risk_pct > 8.0 or risk_pct < 0.3:
            sl        = price - atr * 1.5
            risk      = price - sl
            risk_pct  = risk / price * 100

        # TP2: nearest resistance above
        s_highs = _swing_highs(d1h.highs, lookback=5)
        if d4h:
            s_highs += _swing_highs(d4h.highs, lookback=3)
        valid_res = sorted([h for h in s_highs if h > price * 1.005])
        tp2       = valid_res[0] if valid_res else rp(price + risk * 3.0, price)
        tp1       = rp(price + risk * 1.5, price)
        tp3       = rp(price + risk * 5.0, price)

    else:  # SHORT
        s_highs   = _swing_highs(d1h.highs, lookback=5)
        above     = [h for h in s_highs if h > price * 1.001]
        swing_sl  = min(above) if above else max(d1h.highs[-20:])
        sl        = swing_sl + atr * 0.3
        risk      = sl - price
        risk_pct  = risk / price * 100

        if risk_pct > 8.0 or risk_pct < 0.3:
            sl        = price + atr * 1.5
            risk      = sl - price
            risk_pct  = risk / price * 100

        # TP2: nearest support below
        s_lows = _swing_lows(d1h.lows, lookback=5)
        if d4h:
            s_lows += _swing_lows(d4h.lows, lookback=3)
        valid_sup = sorted([l for l in s_lows if l < price * 0.995], reverse=True)
        tp2       = valid_sup[0] if valid_sup else rp(price - risk * 3.0, price)
        tp1       = rp(price - risk * 1.5, price)
        tp3       = rp(price - risk * 5.0, price)

    if risk <= 0:
        return None

    rr = abs(tp2 - price) / risk
    if rr < MIN_RR:
        return None

    if direction == "LONG":
        tp1_pct = (tp1 - price) / price * 100
        tp2_pct = (tp2 - price) / price * 100
        tp3_pct = (tp3 - price) / price * 100
    else:
        tp1_pct = (price - tp1) / price * 100
        tp2_pct = (price - tp2) / price * 100
        tp3_pct = (price - tp3) / price * 100

    return {
        "entry":     rp(price, price),
        "sl":        rp(sl, price),
        "tp1":       rp(tp1, price),
        "tp2":       rp(tp2, price),
        "tp3":       rp(tp3, price),
        "risk_pct":  round(risk_pct, 2),
        "tp1_pct":   round(tp1_pct, 2),
        "tp2_pct":   round(tp2_pct, 2),
        "tp3_pct":   round(tp3_pct, 2),
        "rr_ratio":  round(rr, 1),
        "atr_pct":   round(atr_pct, 2),
    }


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_symbol(
    symbol: str,
    tf_map: dict[str, FuturesData],
    change_24h: float,
) -> Optional[dict]:
    """
    Evaluate a symbol for Agent 1.
    Returns the best direction (LONG or SHORT) if score ≥ MIN_SCORE, else None.
    """
    if not tf_map:
        return None

    ref   = tf_map.get("1h") or tf_map.get("4h") or next(iter(tf_map.values()))
    price = ref.closes[-1] if ref.closes else 0.0
    if price <= 0:
        return None

    # Score both directions, pick the better one
    long_score,  long_sigs  = _score_direction("LONG",  tf_map, price, change_24h)
    short_score, short_sigs = _score_direction("SHORT", tf_map, price, change_24h)

    # Choose direction with higher score (must exceed MIN_SCORE)
    if long_score >= short_score and long_score >= MIN_SCORE:
        direction = "LONG"
        score     = long_score
        signals   = long_sigs
    elif short_score > long_score and short_score >= MIN_SCORE:
        direction = "SHORT"
        score     = short_score
        signals   = short_sigs
    else:
        return None

    levels = _calc_levels(direction, tf_map, price)
    if not levels:
        return None

    atr_pct  = levels.pop("atr_pct")
    leverage = calc_leverage(atr_pct, score)

    return {
        "symbol":      symbol,
        "direction":   direction,
        "price":       round(price, 8),
        "score":       round(min(score, 99), 1),
        "signals":     signals,
        "leverage":    leverage,
        "change_24h":  round(change_24h, 2),
        "funding_rate": round(ref.funding_rate * 100, 4),   # as %
        "oi_change":   round(ref.oi_change_pct, 2),
        "liq_long":    round(ref.liq_long_usdt / 1e6, 2),   # in $M
        "liq_short":   round(ref.liq_short_usdt / 1e6, 2),
        "agent":       AGENT_NAME,
        **levels,
    }
