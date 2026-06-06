"""
Agent 2 — T0-T4 Technical + On-chain Futures Scanner.

Philosophy:
  T0-T4 pipeline identifies the SETUP from price/volume structure.
  On-chain data (OI, Funding, Liquidation proxy) CONFIRMS or REJECTS it.
  A strong TA setup with on-chain disagreement = skip.
  A strong TA setup with on-chain alignment = high conviction.

Pipeline (0-100 pts):
  T0  Wyckoff Phase         0-20 pts  — smart money activity via price+volume
      └─ OI Confirmation    0-7  pts  — OI validates Wyckoff phase
  T1  Trend (EMA)           0-18 pts  — directional bias multi-TF
      └─ Funding Alignment  0-7  pts  — funding rate confirms trend bias
  T2  S/R Zone              0-14 pts  — entry near key levels
      └─ Volume Profile      0-4  pts  — volume cluster at zone = stronger S/R
  T3  Pattern Signals       0-14 pts  — BB Squeeze, Volume Accum, Candle
  T4  Trigger               0-16 pts  — RSI + Pressure shift + Liq proxy

Max possible: 20+7+18+7+14+4+14+16 = 100 pts

LONG  → Wyckoff Accumulation + Uptrend + Near Support + Bullish Trigger
          + Funding low/negative + OI rising + Long liq pressure spike
SHORT → Wyckoff Distribution + Downtrend + Near Resistance + Bearish Trigger
          + Funding high/positive + OI rising at top + Short liq pressure spike

Min score: 55  |  Min R:R: 1:3  |  Leverage: dynamic (ATR-based)
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

def _wyckoff_phase(closes: list[float], volumes: list[float]) -> tuple[str, float]:
    """
    Wyckoff phase + volume expansion ratio.
    Returns (phase, vol_expansion):
      phase: 'accumulation' | 'markup' | 'distribution' | 'markdown' | 'neutral'
      vol_expansion: recent avg vol / prior avg vol
    """
    if len(closes) < 30 or len(volumes) < 30:
        return "neutral", 1.0

    mid = len(closes) // 2
    recent_closes = closes[mid:]
    prior_closes  = closes[:mid]
    recent_vols   = volumes[mid:]
    prior_vols    = volumes[:mid]

    price_change   = (recent_closes[-1] - prior_closes[0]) / max(prior_closes[0], 1e-10)
    avg_vol_recent = sum(recent_vols) / len(recent_vols)
    avg_vol_prior  = sum(prior_vols)  / len(prior_vols)
    vol_expansion  = avg_vol_recent / avg_vol_prior if avg_vol_prior > 0 else 1.0

    recent_range = (max(recent_closes) - min(recent_closes)) / max(recent_closes[0], 1e-10)
    prior_range  = (max(prior_closes)  - min(prior_closes))  / max(prior_closes[0], 1e-10)
    is_compressed = recent_range < prior_range * 0.6

    if is_compressed and vol_expansion > 1.2 and abs(price_change) < 0.02:
        # Vol expanding while price flat → smart money positioning
        phase = "accumulation" if price_change >= 0 else "accumulation"
        return "accumulation", vol_expansion
    elif price_change > 0.03 and vol_expansion > 1.0:
        return "markup", vol_expansion
    elif is_compressed and vol_expansion > 1.1 and price_change > -0.01:
        return "distribution", vol_expansion
    elif price_change < -0.03 and vol_expansion > 1.0:
        return "markdown", vol_expansion
    return "neutral", vol_expansion


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


# ── T3: Pattern Helpers ────────────────────────────────────────────────────────

def _bb_squeeze(closes: list[float], period: int = 20) -> tuple[bool, float]:
    """Returns (is_squeeze, bb_width_pct)."""
    if len(closes) < period:
        return False, 1.0
    tail = closes[-period:]
    mean = sum(tail) / period
    std  = math.sqrt(sum((v - mean) ** 2 for v in tail) / period)
    bw   = (std * 4) / mean if mean > 0 else 1.0
    return bw < 0.04, round(bw * 100, 2)


def _vol_accumulation(closes: list[float], volumes: list[float]) -> tuple[bool, float]:
    """
    Volume rising while price is flat/sideways = accumulation signal.
    Returns (is_accum, vol_ratio).
    """
    if len(closes) < 21 or len(volumes) < 21:
        return False, 1.0
    avg_vol   = sum(volumes[-21:-1]) / 20
    cur_vol   = volumes[-1]
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0
    # Vol surge while price barely moved = accumulation
    price_move = abs((closes[-1] - closes[-5]) / (closes[-5] or 1)) if len(closes) >= 5 else 1
    is_accum   = vol_ratio > 1.8 and price_move < 0.03
    return is_accum, round(vol_ratio, 2)


def _candle_compression(opens: list[float], closes: list[float], n: int = 7) -> bool:
    """Shrinking candle bodies = energy coiling before breakout."""
    if len(closes) < n + 1:
        return False
    bodies = [abs(closes[i] - opens[i]) for i in range(-n, 0)]
    return bodies[-1] < bodies[0] * 0.5


# ── T4: Trigger Helpers ────────────────────────────────────────────────────────

def _pressure_shift(opens: list[float], closes: list[float], volumes: list[float], n: int = 5) -> float:
    """Buying pressure shift: positive = buyers taking over."""
    if len(opens) < n * 2:
        return 0.0

    def bull_ratio(o: list, c: list, v: list) -> float:
        total = sum(v) or 1
        return sum(v[i] for i in range(len(v)) if c[i] >= o[i]) / total

    now  = bull_ratio(opens[-n:],     closes[-n:],     volumes[-n:])
    prev = bull_ratio(opens[-n*2:-n], closes[-n*2:-n], volumes[-n*2:-n])
    return now - prev


# ── Main scorer ────────────────────────────────────────────────────────────────

def _score_direction(
    direction:  str,
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """Score a direction using T0-T4 pipeline + on-chain confirmation."""
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref  = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── T0: Wyckoff Phase (0-20 pts) ─────────────────────────────────────────
    phase, vol_exp = _wyckoff_phase(ref.closes, ref.volumes)

    if direction == "LONG":
        if phase == "accumulation":
            score += 20
            signals.append(f"📦 Wyckoff Accumulation — vol {vol_exp:.1f}× saat harga flat")
        elif phase == "markup":
            score += 12
            signals.append("📈 Wyckoff Markup — trend naik terkonfirmasi volume")
        elif phase in ("distribution", "markdown"):
            score -= 8   # wrong phase for LONG
    else:  # SHORT
        if phase == "distribution":
            score += 20
            signals.append(f"📤 Wyckoff Distribution — vol {vol_exp:.1f}× di zona puncak")
        elif phase == "markdown":
            score += 12
            signals.append("📉 Wyckoff Markdown — trend turun terkonfirmasi volume")
        elif phase in ("accumulation", "markup"):
            score -= 8

    # ── T0 on-chain: OI Confirmation (0-7 pts) ───────────────────────────────
    # OI rising during accumulation/distribution = institutions positioning
    # OI rising during markup with price up = trend continuation
    oi_chg = ref.oi_change_pct

    if direction == "LONG":
        if phase == "accumulation" and oi_chg > 1.5:
            score += 7
            signals.append(f"📊 OI +{oi_chg:.1f}% selama akumulasi — institusi masuk")
        elif phase == "markup" and oi_chg > 1.0 and change_24h > 0:
            score += 4
            signals.append(f"OI +{oi_chg:.1f}% konfirmasi markup LONG")
        elif oi_chg > 2.0 and change_24h < -1.5:
            # OI rising + price falling = short trap = LONG setup
            score += 6
            signals.append(f"📊 OI +{oi_chg:.1f}% saat harga turun — short trap terdeteksi")
        elif oi_chg < -2.0:
            score -= 4   # OI falling = long liquidation risk
    else:  # SHORT
        if phase == "distribution" and oi_chg > 1.5:
            score += 7
            signals.append(f"📊 OI +{oi_chg:.1f}% selama distribusi — institusi keluar")
        elif phase == "markdown" and oi_chg > 1.0 and change_24h < 0:
            score += 4
            signals.append(f"OI +{oi_chg:.1f}% konfirmasi markdown SHORT")
        elif oi_chg > 2.0 and change_24h > 1.5:
            # OI rising + price rising = long trap = SHORT setup
            score += 6
            signals.append(f"📊 OI +{oi_chg:.1f}% saat harga naik — long trap terdeteksi")
        elif oi_chg < -2.0:
            score -= 4

    # ── T1: Trend Analysis (0-18 pts) ────────────────────────────────────────
    trend_ok = False
    for tf_key in ["4h", "1h", "15m"]:
        d = tf_map.get(tf_key)
        if not d or len(d.closes) < 50:
            continue
        t = _trend(d.closes)
        if direction == "LONG" and t == "up":
            score += 18 if tf_key == "4h" else 12
            signals.append(f"⚡ Uptrend {tf_key} — EMA9>EMA21>EMA50 terkonfirmasi")
            trend_ok = True
            break
        elif direction == "SHORT" and t == "down":
            score += 18 if tf_key == "4h" else 12
            signals.append(f"⚡ Downtrend {tf_key} — EMA9<EMA21<EMA50 terkonfirmasi")
            trend_ok = True
            break

    if not trend_ok:
        score -= 8  # no trend = lower conviction

    # ── T1 on-chain: Funding Rate Alignment (0-7 pts) ────────────────────────
    # Funding contradicts longs/shorts → squeeze potential → confirms direction
    fr = ref.funding_rate

    if direction == "LONG":
        if fr < -0.02 / 100:
            # Negative funding = shorts paying = squeeze risk → LONG confirmed
            score += 7
            signals.append(f"💰 Funding {fr*100:.3f}% negatif — short squeeze, bias LONG")
        elif fr < 0:
            score += 3
        elif fr > 0.08 / 100:
            # High positive funding = longs overpaying → headwind for LONG
            score -= 5
            signals.append(f"⚠️ Funding +{fr*100:.3f}% tinggi — longs overpaying")
    else:  # SHORT
        if fr > 0.08 / 100:
            # High positive funding = longs overpaying → correction risk → SHORT confirmed
            score += 7
            signals.append(f"💰 Funding +{fr*100:.3f}% tinggi — long squeeze, bias SHORT")
        elif fr > 0.04 / 100:
            score += 3
        elif fr < -0.02 / 100:
            # Negative funding = shorts paying → headwind for SHORT
            score -= 5

    # ── T2: S/R Zone Analysis (0-14 pts) ─────────────────────────────────────
    sr_found = False
    for tf_key in ["4h", "1h", "15m"]:
        d = tf_map.get(tf_key)
        if not d or not d.lows or not d.highs:
            continue
        s_lows  = _swing_lows(d.lows,  lookback=5)
        s_highs = _swing_highs(d.highs, lookback=5)

        if direction == "LONG":
            near_sup = [s for s in s_lows  if 0 < (price - s) / price < 0.025]
            if near_sup:
                score    += 14
                signals.append(f"🎯 Near support {tf_key} — zona beli kuat ({len(near_sup)} level)")
                sr_found = True
                break
        else:
            near_res = [r for r in s_highs if 0 < (r - price) / price < 0.025]
            if near_res:
                score    += 14
                signals.append(f"🎯 Near resistance {tf_key} — zona jual kuat ({len(near_res)} level)")
                sr_found = True
                break

    # ── T2 on-chain: Volume Profile at Zone (0-4 pts) ────────────────────────
    # If we're near S/R AND volume is above average → zone is actively traded
    if sr_found and ref.volumes:
        avg_vol = sum(ref.volumes[-21:-1]) / 20 if len(ref.volumes) >= 21 else 0
        cur_vol = ref.volumes[-1]
        if avg_vol > 0 and cur_vol > avg_vol * 1.5:
            score   += 4
            signals.append(f"Vol {cur_vol/avg_vol:.1f}× di zona S/R — level valid")

    # ── T3: Pattern Signals (0-14 pts) ───────────────────────────────────────
    primary_tf = d1h or d4h or d15
    if primary_tf and primary_tf.closes:
        squeeze, bb_w   = _bb_squeeze(primary_tf.closes)
        accum,   vol_r  = _vol_accumulation(primary_tf.closes, primary_tf.volumes)
        candle_c        = _candle_compression(primary_tf.opens, primary_tf.closes)

        if squeeze:
            score += 8
            signals.append(f"🔵 BB Squeeze ({bb_w:.1f}% width) — energi terkompresi, breakout mendekat")
        elif bb_w < 6.0:
            score += 4   # moderate compression

        if accum:
            score += 4
            signals.append(f"📦 Volume Accumulation {vol_r:.1f}× — smart money positioning")

        if candle_c:
            score += 2
            # candle coil = weak signal alone, but confirms BB squeeze

    # ── T4: Trigger (0-16 pts) ───────────────────────────────────────────────
    trigger_tf = d1h or d15 or d4h
    if trigger_tf and trigger_tf.closes:
        rsi      = _rsi(trigger_tf.closes, 14)
        pressure = _pressure_shift(trigger_tf.opens, trigger_tf.closes, trigger_tf.volumes)

        if direction == "LONG":
            if rsi < 35:
                score += 8
                signals.append(f"RSI {rsi:.0f} — oversold, trigger reversal naik")
            elif rsi < 50:
                score += 4
            elif rsi > 72:
                score -= 5   # overbought = bad for new LONG
            if pressure > 0.20:
                score += 8
                signals.append(f"🟢 Buy pressure +{pressure*100:.0f}% — buyer mengambil alih")
            elif pressure > 0.10:
                score += 4
        else:  # SHORT
            if rsi > 70:
                score += 8
                signals.append(f"RSI {rsi:.0f} — overbought, trigger koreksi")
            elif rsi > 55:
                score += 4
            elif rsi < 30:
                score -= 5   # oversold = bad for new SHORT
            if pressure < -0.20:
                score += 8
                signals.append(f"🔴 Sell pressure {pressure*100:.0f}% — seller mengambil alih")
            elif pressure < -0.10:
                score += 4

    # ── T4 on-chain: Liquidation Proxy — L/S Ratio Shift (0-8 pts) ──────────
    # Synthetic proxy from globalLongShortAccountRatio:
    # liq_long_usdt  > 0 → long liq pressure (ratio dropping) → capitulation
    # liq_short_usdt > 0 → short liq pressure (ratio rising)  → squeeze
    liq_long  = ref.liq_long_usdt
    liq_short = ref.liq_short_usdt

    if direction == "LONG" and liq_long > 30_000:
        # Long liquidation spike = capitulation bottom → reversal LONG
        score += 8
        signals.append("💥 Tekanan likuidasi LONG — capitulation, potensi reversal naik")
    elif direction == "LONG" and liq_short > 30_000:
        # Short liq pressure = shorts being squeezed = bullish
        score += 4
        signals.append("Short squeeze pressure — momentum bullish")
    elif direction == "SHORT" and liq_short > 30_000:
        # Short liquidation spike → reversal SHORT potential after exhaustion
        score += 8
        signals.append("💥 Tekanan likuidasi SHORT — capitulation, potensi reversal turun")
    elif direction == "SHORT" and liq_long > 30_000:
        # Long liq pressure = longs being crushed = bearish
        score += 4
        signals.append("Long squeeze pressure — momentum bearish")

    # ── Penalty: extreme 24h move (trade likely exhausted) ───────────────────
    if abs(change_24h) > 20:
        score -= 15
    elif abs(change_24h) > 12:
        score -= 8

    clean = [s for s in signals if not s.startswith("⚠️")]
    return score, clean[:5]


# ── Trade levels (shared with Agent 1 logic) ──────────────────────────────────

def _calc_levels(direction: str, tf_map: dict[str, FuturesData], price: float) -> Optional[dict]:
    from .agent1 import _calc_levels as a1_levels
    return a1_levels(direction, tf_map, price)


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_symbol(
    symbol:     str,
    tf_map:     dict[str, FuturesData],
    change_24h: float,
) -> Optional[dict]:
    """
    Evaluate symbol for Agent 2 (T0-T4 + On-chain).
    Returns best direction signal dict, or None if below threshold.
    """
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
        "symbol":       symbol,
        "direction":    direction,
        "price":        round(price, 8),
        "score":        round(min(score, 99), 1),
        "signals":      signals,
        "leverage":     leverage,
        "change_24h":   round(change_24h, 2),
        "funding_rate": round(ref.funding_rate * 100, 4),
        "oi_change":    round(ref.oi_change_pct, 2),
        "liq_long":     round(ref.liq_long_usdt / 1e6, 3),
        "liq_short":    round(ref.liq_short_usdt / 1e6, 3),
        "agent":        AGENT_NAME,
        **levels,
    }
