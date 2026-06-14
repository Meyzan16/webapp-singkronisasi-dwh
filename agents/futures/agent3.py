"""
Agent 3 — Momentum Capture.

Goal: Enter AFTER the move has begun — ride the confirmed momentum wave.
      Find coins already breaking out with volume + OI + RSI confirmation.

OPPOSITE of Agents 1 & 2:
  Agent 1 PENALIZES change_24h > 8%   (−12 pts)  ← pre-gainer, wants flat coin
  Agent 2 PENALIZES change_24h > 7%   (−10 pts)  ← accumulation, wants flat coin
  Agent 3 REWARDS   change_24h 5-20%  (+up to 20) ← momentum, coin already moving

Momentum LONG fingerprint:
  1. Price up 5-20% in 24h      — move established, not yet exhausted
  2. Volume 2x+ confirming      — real buyers, not ghost volume
  3. OI rising WITH price       — new long positions = conviction (not short squeeze)
  4. Funding healthy < 0.08%   — still room to run, not overcrowded
  5. RSI 55-72                  — momentum established, not overbought
  6. Breakout above recent high — trend confirmation, clear air above

Momentum SHORT fingerprint (mirror):
  1. Price down 5-20% in 24h
  2. Volume surge on drop
  3. OI rising WHILE price falls — new shorts = bearish conviction
  4. Funding neutral/negative
  5. RSI 28-45 falling
  6. Break below recent low

Min score: 55  |  Min R:R: 1:3  |  Leverage: dynamic ATR-based (cap 10x)
"""

import math
from typing import Optional

import structlog

from .data import FuturesData
from .agent1 import (
    _rsi, _swing_lows, _swing_highs, _round_price,
    _ema, _atr,
    MIN_RR, MIN_SL_PCT, MAX_SL_MARGIN_PCT,
)

logger = structlog.get_logger(__name__)

MIN_SCORE  = 55
AGENT_NAME = "futures_agent3"

# Momentum leverage: capped lower than pre-gainer (already-moved = higher vol risk)
_MAX_LEV = 10


def calc_leverage_momentum(atr_pct: float, score: float, risk_pct: float = 0.0) -> int:
    """Dynamic leverage — more conservative than pre-gainer agents (max 10x).

    BUG-L6/L7: reconciled with SL distance so a full SL never loses more than
    MAX_SL_MARGIN_PCT of margin (was ATR-only → tight SL + high leverage wipe).
    """
    if atr_pct > 5.0:   base = 2
    elif atr_pct > 3.0: base = 3
    elif atr_pct > 2.0: base = 4
    elif atr_pct > 1.0: base = 6
    else:               base = 8

    if score >= 80:    base = min(base + 2, _MAX_LEV)
    elif score >= 70:  base = min(base + 1, _MAX_LEV)

    # BUG-L6/L7: cap leverage by SL distance (margin loss ≈ risk_pct × leverage)
    if risk_pct and risk_pct > 0:
        base = min(base, max(1, int(MAX_SL_MARGIN_PCT / risk_pct)))

    return max(1, min(base, _MAX_LEV))


# ── Signal helpers ────────────────────────────────────────────────────────────

def _volume_momentum(
    closes: list[float],
    volumes: list[float],
    direction: str,
) -> tuple[float, str]:
    """
    Volume surge ALIGNED with price direction.
    Unlike agent1's _volume_accumulation (vol up + price FLAT),
    here we want vol up + price moving in the signal direction.
    """
    if len(closes) < 22 or len(volumes) < 22:
        return 1.0, "none"

    avg_vol   = sum(volumes[-21:-1]) / 20
    cur_vol   = volumes[-1]
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

    # Price move over last 4 candles to confirm direction
    price_move = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] > 0 else 0.0

    if direction == "LONG":
        if vol_ratio >= 2.5 and price_move >= 1.5:
            return round(vol_ratio, 2), "strong"
        if vol_ratio >= 2.0 and price_move >= 0.5:
            return round(vol_ratio, 2), "moderate"
        if vol_ratio >= 1.5 and price_move >= 0.3:
            return round(vol_ratio, 2), "weak"
    else:  # SHORT
        if vol_ratio >= 2.5 and price_move <= -1.5:
            return round(vol_ratio, 2), "strong"
        if vol_ratio >= 2.0 and price_move <= -0.5:
            return round(vol_ratio, 2), "moderate"
        if vol_ratio >= 1.5 and price_move <= -0.3:
            return round(vol_ratio, 2), "weak"

    return round(vol_ratio, 2), "none"


def _is_breakout(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    direction: str,
) -> tuple[bool, float]:
    """
    Price breaking above/below recent 30-candle extreme (not including current candle).
    Returns (is_breakout, breakout_pct).
    """
    price = closes[-1]
    if direction == "LONG":
        if len(highs) < 32:
            return False, 0.0
        recent_high = max(highs[-31:-1])   # prior 30 candles, not current
        if price > recent_high:
            return True, round((price - recent_high) / recent_high * 100, 2)
    else:  # SHORT
        if len(lows) < 32:
            return False, 0.0
        recent_low = min(lows[-31:-1])
        if price < recent_low:
            return True, round((recent_low - price) / recent_low * 100, 2)
    return False, 0.0


# ── Momentum LONG scorer ──────────────────────────────────────────────────────

def _score_momentum_long(
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """Score a symbol for momentum LONG (coin already pumping, ride the wave)."""
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── 1. 24h move in sweet spot (0-20 pts) ─────────────────────────────────
    if 8 <= change_24h <= 12:
        score += 20
        signals.append(f"🚀 Momentum +{change_24h:.1f}% — sweet spot entry: terbangun tapi belum exhausted")
    elif 5 <= change_24h < 8:
        score += 12
        signals.append(f"Momentum early +{change_24h:.1f}% — awal terbentuk, masih ada room")
    elif 12 < change_24h <= 18:
        score += 15
        signals.append(f"⚡ Momentum kuat +{change_24h:.1f}% — wave sudah jelas, SL sadar-leverage")
    elif 18 < change_24h <= 25:
        score += 8
        signals.append(f"Momentum tinggi +{change_24h:.1f}% — waspadai exhaustion candle")

    # ── 2. Volume surge confirming direction (0-25 pts) ───────────────────────
    best_vol = 0
    for tf_key, d in [("1h", d1h), ("4h", d4h), ("15m", d15)]:
        if not d or len(d.closes) < 22:
            continue
        vol_r, label = _volume_momentum(d.closes, d.volumes, "LONG")
        if label == "strong":
            pts = 25 if tf_key == "1h" else (20 if tf_key == "4h" else 15)
            if pts > best_vol:
                best_vol = pts
                signals.append(f"💥 Volume {vol_r:.1f}× {tf_key} saat naik — buyer aggression dikonfirmasi")
        elif label == "moderate":
            pts = 16 if tf_key == "1h" else (12 if tf_key == "4h" else 9)
            if pts > best_vol:
                best_vol = pts
                signals.append(f"Volume {vol_r:.1f}× {tf_key} — momentum terkonfirmasi pembeli")
        elif label == "weak" and best_vol == 0:
            best_vol = 6
    score += best_vol

    # ── 3. OI rising WITH price (0-15 pts) ───────────────────────────────────
    # Key: OI up while price up = real new longs (not short squeeze)
    oi_chg = ref.oi_change_pct
    if oi_chg >= 5.0:
        score += 15
        signals.append(f"📊 OI +{oi_chg:.1f}% — massive new LONG positioning masuk")
    elif oi_chg >= 3.0:
        score += 10
        signals.append(f"OI +{oi_chg:.1f}% — new money masuk LONG, bukan squeeze biasa")
    elif oi_chg >= 1.0:
        score += 5
    elif oi_chg < -2.0:
        score -= 10  # OI falling while price up = pure short squeeze, risky
        signals.append(f"⚠️ OI turun {oi_chg:.1f}% saat naik — kemungkinan short squeeze saja")

    # ── 4. Funding rate healthy (0-12 pts) ───────────────────────────────────
    fr = ref.funding_rate
    if fr < 0:
        score += 9   # shorts paying = extra squeeze fuel for LONG
    elif fr <= 0.03 / 100:
        score += 12  # neutral = perfect, not yet crowded
    elif fr <= 0.06 / 100:
        score += 6
    elif fr <= 0.10 / 100:
        score += 2
    else:
        score -= 8   # funding too high = crowded longs = reversal risk
        signals.append(f"⚠️ Funding {fr*100:.3f}% terlalu tinggi — longs sudah crowded")

    # ── 5. RSI momentum zone 55-72 (0-15 pts) ────────────────────────────────
    primary = d1h or d15 or d4h
    rsi_val = 50.0
    if primary and primary.closes:
        rsi_val = _rsi(primary.closes, 14)
        if 58 <= rsi_val <= 70:
            score += 15
            signals.append(f"RSI {rsi_val:.0f} momentum zone — trending kuat belum overbought")
        elif 53 <= rsi_val < 58:
            score += 10
            signals.append(f"RSI {rsi_val:.0f} — momentum building, waktu entry bagus")
        elif 70 < rsi_val <= 78:
            score += 6
            signals.append(f"RSI {rsi_val:.0f} extended — momentum kuat, SL di swing terakhir")
        elif rsi_val < 45:
            score -= 6  # coin actually stalling/reversing

    # ── 6. Breakout above 30-candle high (0-13 pts) ──────────────────────────
    for tf_key, d in [("4h", d4h), ("1h", d1h)]:
        if not d or len(d.highs) < 32:
            continue
        is_bo, bo_pct = _is_breakout(d.highs, d.lows, d.closes, "LONG")
        if is_bo:
            if bo_pct >= 2.0:
                score += 13
                signals.append(f"🔓 Breakout {tf_key} +{bo_pct:.1f}% di atas {30}-candle high — udara bersih di atas")
            elif bo_pct >= 0.5:
                score += 8
                signals.append(f"Breakout baru {tf_key} — baru menembus resistance {30}-candle")
            break

    # ── Penalties ─────────────────────────────────────────────────────────────
    if change_24h < 5.0:
        score -= 15   # not enough momentum — pre-gainers better handles this
    if change_24h > 25.0:
        score -= 15   # overextended
    if change_24h > 35.0:
        score -= 25   # parabolic = extreme reversal risk
    if rsi_val > 80:
        score -= 15   # overbought
    elif rsi_val > 75:
        score -= 8

    # BUG-L14: liquidation feed is a directional PROXY, not real USDT — small nudge only.
    if ref.liq_short_usdt > 2_000_000:
        score += 3
        signals.append("Short squeeze terdeteksi (proxy arah) — forced buying = momentum fuel")
    elif ref.liq_short_usdt > 500_000:
        score += 2

    return score, signals[:5]


# ── Momentum SHORT scorer ─────────────────────────────────────────────────────

def _score_momentum_short(
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """Score a symbol for momentum SHORT (coin already dumping, ride the wave down)."""
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── 1. 24h drop in sweet spot (0-20 pts) ─────────────────────────────────
    drop = -change_24h  # positive value = how much it dropped
    if 8 <= drop <= 12:
        score += 20
        signals.append(f"📉 Dump {change_24h:.1f}% — sweet spot short entry: momen tapi belum oversold")
    elif 5 <= drop < 8:
        score += 12
        signals.append(f"Dump early {change_24h:.1f}% — awal turun, momentum SHORT terbentuk")
    elif 12 < drop <= 18:
        score += 15
        signals.append(f"⚡ Dump kuat {change_24h:.1f}% — wave turun jelas, short SL sadar-leverage")
    elif 18 < drop <= 25:
        score += 8
        signals.append(f"Dump besar {change_24h:.1f}% — waspadai bouncing oversold")

    # ── 2. Volume surge on the drop (0-25 pts) ────────────────────────────────
    best_vol = 0
    for tf_key, d in [("1h", d1h), ("4h", d4h), ("15m", d15)]:
        if not d or len(d.closes) < 22:
            continue
        vol_r, label = _volume_momentum(d.closes, d.volumes, "SHORT")
        if label == "strong":
            pts = 25 if tf_key == "1h" else (20 if tf_key == "4h" else 15)
            if pts > best_vol:
                best_vol = pts
                signals.append(f"💥 Volume {vol_r:.1f}× {tf_key} saat turun — seller aggression dikonfirmasi")
        elif label == "moderate":
            pts = 16 if tf_key == "1h" else (12 if tf_key == "4h" else 9)
            if pts > best_vol:
                best_vol = pts
                signals.append(f"Volume {vol_r:.1f}× {tf_key} — momentum SHORT terkonfirmasi")
        elif label == "weak" and best_vol == 0:
            best_vol = 6
    score += best_vol

    # ── 3. OI rising WHILE price falls (0-15 pts) ────────────────────────────
    # Key: OI up + price down = real new shorts entering (not just long liquidation)
    oi_chg = ref.oi_change_pct
    if oi_chg >= 5.0:
        score += 15
        signals.append(f"📊 OI +{oi_chg:.1f}% saat harga turun — new SHORT positioning masuk kuat")
    elif oi_chg >= 3.0:
        score += 10
        signals.append(f"OI +{oi_chg:.1f}% saat dump — short conviction nyata, bukan sekedar liq")
    elif oi_chg >= 1.0:
        score += 5
    elif oi_chg < -3.0:
        score -= 8   # OI falling while price down = long capitulation not short entry

    # ── 4. Funding neutral/negative (0-12 pts) ────────────────────────────────
    fr = ref.funding_rate
    if fr < -0.04 / 100:
        score += 12  # strongly negative = shorts dominating
        signals.append(f"Funding {fr*100:.3f}% negatif kuat — market SHORT mode aktif")
    elif fr < -0.01 / 100:
        score += 9   # mildly negative = shifting to bears
    elif fr <= 0.02 / 100:
        score += 5   # near-zero = neutral, still ok
    elif fr <= 0.05 / 100:
        score += 2   # positive but low — longs still crowded (good for short)
    else:
        score -= 5   # high positive = market too bullish for short momentum

    # ── 5. RSI falling zone 28-45 (0-15 pts) ─────────────────────────────────
    primary = d1h or d15 or d4h
    rsi_val = 50.0
    if primary and primary.closes:
        rsi_val = _rsi(primary.closes, 14)
        if 30 <= rsi_val <= 42:
            score += 15
            signals.append(f"RSI {rsi_val:.0f} falling zone — downward momentum, belum oversold")
        elif 42 < rsi_val <= 50:
            score += 8
            signals.append(f"RSI {rsi_val:.0f} breaking down — momentum bearish terbentuk")
        elif 22 < rsi_val < 30:
            score += 6
            signals.append(f"RSI {rsi_val:.0f} — nearly oversold, tight SL required")
        elif rsi_val > 60:
            score -= 6  # too strong upside momentum for short

    # ── 6. Breakdown below 30-candle low (0-13 pts) ──────────────────────────
    for tf_key, d in [("4h", d4h), ("1h", d1h)]:
        if not d or len(d.lows) < 32:
            continue
        is_bd, bd_pct = _is_breakout(d.highs, d.lows, d.closes, "SHORT")
        if is_bd:
            if bd_pct >= 2.0:
                score += 13
                signals.append(f"📉 Breakdown {tf_key} -{bd_pct:.1f}% di bawah {30}-candle low — support dijebol")
            elif bd_pct >= 0.5:
                score += 8
                signals.append(f"Breakdown baru {tf_key} — baru menembus support {30}-candle")
            break

    # ── Penalties ─────────────────────────────────────────────────────────────
    if drop < 5.0:
        score -= 15   # not enough downward momentum
    if drop > 25.0:
        score -= 15   # oversold — bounce risk very high
    if drop > 35.0:
        score -= 25   # capitulation = dangerous to short here
    if rsi_val < 22:
        score -= 15   # extreme oversold = reversal imminent
    elif rsi_val < 28:
        score -= 8

    # BUG-L14: liquidation feed is a directional PROXY, not real USDT — small nudge only.
    if ref.liq_long_usdt > 2_000_000:
        score += 3
        signals.append("Long liq terdeteksi (proxy arah) — forced selling = bearish fuel")
    elif ref.liq_long_usdt > 500_000:
        score += 2

    return score, signals[:5]


# ── Trade levels ──────────────────────────────────────────────────────────────

def _calc_levels(
    direction: str,
    tf_map:    dict[str, FuturesData],
    price:     float,
) -> Optional[dict]:
    """
    Trade levels for momentum entry.
    LONG: SL below recent swing low (breakout-confirmation), TP at next resistance.
    SHORT: SL above recent swing high, TP at next support.
    Same structure as agent1._calc_levels but using 15m or shorter lookback for momentum.
    """
    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref = d1h or d15 or d4h
    if not ref or len(ref.closes) < 20:
        return None

    atr     = _atr(ref.highs, ref.lows, ref.closes, 14)
    atr_pct = atr / price * 100 if price > 0 else 0
    rp      = _round_price

    if direction == "LONG":
        # SL: just below the most recent swing low (or 1.2× ATR below entry if no swing)
        s_lows  = _swing_lows(ref.lows, lookback=4)
        below   = [s for s in s_lows if s < price * 0.999]
        swing_sl = max(below) if below else min(ref.lows[-15:])
        sl       = swing_sl - atr * 0.25   # tighter buffer for momentum
        risk     = price - sl
        risk_pct = risk / price * 100

        # BUG-L3/L5: SL floor — too-tight stops get hit by noise; too-wide → ATR fallback.
        min_sl_pct = max(MIN_SL_PCT, atr_pct * 0.8)
        if risk_pct > 7.0:
            sl       = price - atr * 1.2
            risk     = price - sl
            risk_pct = risk / price * 100
        if risk_pct < min_sl_pct:
            risk     = price * (min_sl_pct / 100)
            sl       = price - risk
            risk_pct = min_sl_pct

        s_highs   = _swing_highs(ref.highs, lookback=4)
        if d4h:
            s_highs += _swing_highs(d4h.highs, lookback=3)
        valid_res = sorted([h for h in s_highs if h > price * 1.005])
        tp2 = valid_res[0] if valid_res else rp(price + risk * 3.0, price)
        tp1 = rp(price + risk * 1.5, price)
        tp3 = rp(price + risk * 5.0, price)
        tp1_pct = (tp1 - price) / price * 100
        tp2_pct = (tp2 - price) / price * 100
        tp3_pct = (tp3 - price) / price * 100

    else:  # SHORT
        s_highs  = _swing_highs(ref.highs, lookback=4)
        above    = [h for h in s_highs if h > price * 1.001]
        swing_sl = min(above) if above else max(ref.highs[-15:])
        sl       = swing_sl + atr * 0.25
        risk     = sl - price
        risk_pct = risk / price * 100

        # BUG-L3/L5: SL floor — too-tight stops get hit by noise; too-wide → ATR fallback.
        min_sl_pct = max(MIN_SL_PCT, atr_pct * 0.8)
        if risk_pct > 7.0:
            sl       = price + atr * 1.2
            risk     = sl - price
            risk_pct = risk / price * 100
        if risk_pct < min_sl_pct:
            risk     = price * (min_sl_pct / 100)
            sl       = price + risk
            risk_pct = min_sl_pct

        s_lows   = _swing_lows(ref.lows, lookback=4)
        if d4h:
            s_lows += _swing_lows(d4h.lows, lookback=3)
        valid_sup = sorted([l for l in s_lows if l < price * 0.995], reverse=True)
        tp2 = valid_sup[0] if valid_sup else rp(price - risk * 3.0, price)
        tp1 = rp(price - risk * 1.5, price)
        tp3 = rp(price - risk * 5.0, price)
        tp1_pct = (price - tp1) / price * 100
        tp2_pct = (price - tp2) / price * 100
        tp3_pct = (price - tp3) / price * 100

    if risk <= 0:
        return None

    rr = abs(tp2 - price) / risk
    if rr < MIN_RR:
        return None

    return {
        "entry":    rp(price, price),
        "sl":       rp(sl, price),
        "tp1":      tp1,
        "tp2":      rp(tp2, price),
        "tp3":      tp3,
        "risk_pct": round(risk_pct, 2),
        "tp1_pct":  round(tp1_pct, 2),
        "tp2_pct":  round(tp2_pct, 2),
        "tp3_pct":  round(tp3_pct, 2),
        "rr_ratio": round(rr, 1),
        "atr_pct":  round(atr_pct, 2),
    }


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_symbol(
    symbol:     str,
    tf_map:     dict[str, FuturesData],
    change_24h: float,
) -> list[dict]:
    """
    Evaluate a symbol for Agent 3 (Momentum Capture).
    Returns valid LONG and/or SHORT momentum setups where score >= MIN_SCORE.
    Applies same weight cache + regime modifier pattern as Agents 1 & 2.
    """
    if not tf_map:
        return []

    ref   = tf_map.get("1h") or tf_map.get("4h") or next(iter(tf_map.values()))
    price = ref.closes[-1] if ref.closes else 0.0
    if price <= 0:
        return []

    from agents.futures import weight_updater
    from agents.futures.regime import detect_coin_regime
    weight_cache  = weight_updater.get_weight_cache(AGENT_NAME)
    thresholds    = weight_updater.get_adaptive_thresholds(AGENT_NAME)
    effective_min = thresholds["min_score"]
    # BUG-L13: per-coin regime from the coin's own 1h OHLCV (was BTC-only for all alts)
    regime        = detect_coin_regime(tf_map.get("1h") or ref)

    long_score,  long_sigs  = _score_momentum_long(tf_map, price, change_24h)
    short_score, short_sigs = _score_momentum_short(tf_map, price, change_24h)

    results = []
    for direction, score, signals in [
        ("LONG",  long_score,  long_sigs),
        ("SHORT", short_score, short_sigs),
    ]:
        # Signal weight adjustments from historical win rates
        for sig in signals:
            key = weight_updater.normalize_signal_key(sig)
            w   = weight_cache.get(key, 1.0)
            score += (w - 1.0) * 5.0

        # Regime modifier: momentum loves trending regimes
        if regime == "volatile":
            score *= 0.80   # volatile = whipsaw risk on momentum entries
        elif regime == "trending_up" and direction == "LONG":
            score += 8      # with-trend momentum: strong bonus
        elif regime == "trending_down" and direction == "SHORT":
            score += 8      # with-trend momentum: strong bonus
        elif regime == "trending_up" and direction == "SHORT":
            score -= 8      # counter-trend momentum: risky
        elif regime == "trending_down" and direction == "LONG":
            score -= 8      # counter-trend momentum: risky

        if score < effective_min:
            continue
        levels = _calc_levels(direction, tf_map, price)
        if not levels:
            continue
        atr_pct  = levels.pop("atr_pct")
        leverage = calc_leverage_momentum(atr_pct, score, levels["risk_pct"])
        results.append({
            "symbol":       symbol,
            "direction":    direction,
            "price":        round(price, 8),
            "score":        round(min(score, 100), 1),
            "signals":      signals,
            "leverage":     leverage,
            "change_24h":   round(change_24h, 2),
            "funding_rate": round(ref.funding_rate * 100, 4),
            "oi_change":    round(ref.oi_change_pct, 2),
            "liq_long":     round(ref.liq_long_usdt / 1e6, 3),
            "liq_short":    round(ref.liq_short_usdt / 1e6, 3),
            "agent":        AGENT_NAME,
            "setup_type":   "momentum",   # P2: lane tag for unified scanner
            "regime":       regime,       # BUG-L13: per-coin regime (for trade.regime/learning)
            **levels,
        })
    return results
