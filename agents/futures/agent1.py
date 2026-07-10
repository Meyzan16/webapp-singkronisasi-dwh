"""
Agent 1 — Pre-Gainer / Pre-Dump Scout.

Goal: Find setups BEFORE coins make big moves — both LONG and SHORT.
      Hunt "quiet coins" while they're still coiling — before the explosion or implosion.

Pre-PUMP fingerprint (LONG):
  1. BB Squeeze at base/support           — energy coiling at bottom, about to explode up
  2. Volume accumulating, price flat      — smart money buying quietly
  3. Funding neutral / negative           — market not yet crowded LONG (fuel available)
  4. OI rising steadily                  — new money entering long
  5. Price near resistance < 3%          — catalyst within reach, breakout imminent
  6. RSI 40-55 sweet spot                — momentum turning up, not yet overbought

Pre-DUMP fingerprint (SHORT):
  1. BB Squeeze at top/resistance         — energy coiling at top, about to collapse
  2. Volume distributing, price flat      — smart money selling quietly at top
  3. Funding HIGH (> 0.05%)              — longs overcrowded = fuel for dump
  4. OI rising at resistance             — long trap forming, forced unwind coming
  5. Price near resistance < 2%          — rejection zone
  6. RSI 55-70 fading zone               — momentum stalling, overbought approaching

Min score: 52  |  Min R:R: 1:3  |  Leverage: dynamic (ATR-based)
"""

import math
import time
from typing import Optional

import structlog

from .data import FuturesData
from .utils import (
    _ema, _atr,                # F112: shared TA helpers (agent2 re-imports from here)
    cap_leverage_by_lane,      # PLAN_v2 P1.2/P1.3 — single source for sizing caps
)

logger = structlog.get_logger(__name__)

MIN_RR     = 2.0   # PLAN_v6 P2b: was 3.0 — measured to TP2 which is now CAPPED at
                   # 2.5×risk (P2b) so 3.0 was unreachable-by-construction. 2.0 keeps a
                   # real asymmetry filter (reject if nearest target < 2×risk away).
                   # Shared by agent2 (delegates _calc_levels) and agent3 (imports MIN_RR).
AGENT_NAME = "futures_agent1"

# BUG-L3/L5: minimum SL distance (%) — stops tighter than this get hit by market noise
# (was an implicit 0.3% floor → 0.34% SL @ 12x = instant noise stop-out, win rate 0%).
MIN_SL_PCT = 1.5
# PLAN_v2 P1.3: per-lane cap now lives in utils.MAX_SL_MARGIN_PCT_BY_LANE.
# The single 25% legacy constant was applied uniformly to momentum + pre-move +
# accumulation — accumulation holds for days, so its cap is now 15% (utils).


# ── Math helpers ──────────────────────────────────────────────────────────────

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


def _round_price(price: float, ref: float) -> float:
    if ref >= 1000:  return round(price, 2)
    if ref >= 10:    return round(price, 4)
    if ref >= 0.1:   return round(price, 5)
    if ref >= 0.001: return round(price, 7)
    return round(price, 8)


# ── Signal detectors ──────────────────────────────────────────────────────────

def _bb_squeeze(closes: list[float], period: int = 20, atr_pct: float = 0.0) -> tuple[bool, float, str]:
    """
    Detect Bollinger Band Squeeze (volatility compression).
    D3.1 (PLAN_v3): adaptive threshold = 0.6× ATR for strong, 1.0× ATR for moderate.
    Falls back to fixed 4%/7% when atr_pct is not provided.
    """
    if len(closes) < period:
        return False, 100.0, "none"
    tail = closes[-period:]
    mean = sum(tail) / period
    std  = math.sqrt(sum((v - mean) ** 2 for v in tail) / period)
    bw   = (std * 4) / mean * 100 if mean > 0 else 100.0
    strong_thresh   = max(2.0, atr_pct * 0.6) if atr_pct > 0 else 4.0
    moderate_thresh = max(4.0, atr_pct * 1.0) if atr_pct > 0 else 7.0
    if bw < strong_thresh:
        return True, round(bw, 2), "strong"
    if bw < moderate_thresh:
        return True, round(bw, 2), "moderate"
    return False, round(bw, 2), "none"


def _bb_squeeze_persistence(closes: list[float], period: int = 20, atr_pct: float = 0.0) -> int:
    """
    D3.5 (PLAN_v3): count trailing consecutive candles where BB is in squeeze.
    Returns streak count (0 if current candle is not a squeeze).
    """
    if len(closes) < period + 1:
        return 0
    streak = 0
    for offset in range(len(closes) - period + 1):
        slice_end = len(closes) - offset
        _, _, label = _bb_squeeze(closes[slice_end - period: slice_end], period, atr_pct)
        if label in ("strong", "moderate"):
            streak += 1
        else:
            break
    return streak


def _volume_accumulation(closes: list[float], volumes: list[float]) -> tuple[bool, float, str]:
    """
    Volume rising while price is flat = smart money accumulation.
    Returns (is_accum, vol_ratio, label).
    Key insight: institutions buy quietly — volume up, price barely moves.
    """
    if len(closes) < 21 or len(volumes) < 21:
        return False, 1.0, "none"

    avg_vol    = sum(volumes[-21:-1]) / 20
    cur_vol    = volumes[-1]
    vol_ratio  = cur_vol / avg_vol if avg_vol > 0 else 1.0

    # Price movement over last 5 candles (flat = accumulation, not distribution)
    price_move = abs((closes[-1] - closes[-5]) / closes[-5]) if closes[-5] > 0 else 1.0

    if vol_ratio >= 2.5 and price_move < 0.03:
        return True, round(vol_ratio, 2), "strong"
    if vol_ratio >= 1.8 and price_move < 0.04:
        return True, round(vol_ratio, 2), "moderate"
    return False, round(vol_ratio, 2), "none"


def _volume_zscore(volumes: list[float]) -> float:
    """
    P1.1: Z-score of current candle volume vs historical baseline.
    Uses up to 200 prior candles as baseline; requires 1h TF fetched with limit=200.
    Returns standard deviations above mean (negative = below avg).
    """
    if len(volumes) < 10:
        return 0.0
    baseline_len = min(200, len(volumes) - 1)
    baseline = volumes[-baseline_len - 1:-1]
    if not baseline:
        return 0.0
    cur  = volumes[-1]
    mean = sum(baseline) / len(baseline)
    variance = sum((v - mean) ** 2 for v in baseline) / len(baseline)
    std = variance ** 0.5
    return (cur - mean) / std if std > 0 else 0.0


def _candle_coil(opens: list[float], closes: list[float], n: int = 8) -> bool:
    """
    Shrinking candle bodies over last N candles = energy coiling.
    Confirms BB Squeeze signal.
    """
    if len(closes) < n + 1 or len(opens) < n + 1:
        return False
    bodies = [abs(closes[i] - opens[i]) for i in range(-n, 0)]
    # Bodies shrinking trend (last is at least 40% smaller than first)
    return bodies[-1] < bodies[0] * 0.6 and bodies[-1] < bodies[int(n / 2)] * 0.8


def _rsi_sweet_spot(closes: list[float]) -> tuple[float, str]:
    """
    RSI in 40-55 zone = momentum waking up, not yet overbought.
    This is the ideal entry zone before a big move.
    Returns (rsi, zone_label).
    """
    rsi = _rsi(closes, 14)
    if 43 <= rsi <= 55:
        return rsi, "sweet"      # momentum turning up perfectly
    if 35 <= rsi < 43:
        return rsi, "recovering" # oversold recovery, still good
    if 55 < rsi <= 63:
        return rsi, "building"   # momentum building, watch out for extension
    return rsi, "outside"


# ── Leverage ──────────────────────────────────────────────────────────────────

def calc_leverage(
    atr_pct:    float,
    score:      float,
    risk_pct:   float = 0.0,
    lane:       str   = "pre_gainer",
    change_24h: float = 0.0,
) -> int:
    """Dynamic leverage from volatility (ATR%) + confidence (score), reconciled with SL.

    PLAN_v2 P1.2/P1.3 (replaces BUG-L6/L7):
      - lane-aware SL-margin cap (accumulation 15% / pre_move 18% / momentum 25%)
      - liquidation-safety cap so a wick to SL never lands at the liq line
    PLAN_v6 P1a/P1b: hard per-lane ceiling + extended-entry (|change_24h|) halving —
      all applied inside utils.cap_leverage_by_lane (shared by every agent).
    """
    if atr_pct > 5.0:   base = 2
    elif atr_pct > 3.0: base = 3
    elif atr_pct > 2.0: base = 5
    elif atr_pct > 1.0: base = 7
    else:               base = 10

    if score >= 80:    base = min(base + 3, 15)
    elif score >= 70:  base = min(base + 2, 12)
    elif score >= 60:  base = min(base + 1, 10)

    return cap_leverage_by_lane(base, risk_pct, lane, change_24h=change_24h)


# ── Main scorer ───────────────────────────────────────────────────────────────

def _score_pregainer(
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """
    Score a symbol for pre-gainer LONG setup.
    Returns (score, signals_list).
    """
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref  = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── 1. BB Squeeze multi-TF (0-30 pts) ─────────────────────────────────────
    # Primary signal — compression across multiple timeframes = explosion imminent
    squeeze_pts = 0
    squeeze_signals: list[str] = []

    # D3.1 (PLAN_v3): compute ATR for adaptive BB thresholds
    _atr_ref = d1h or d4h or d15
    _atr_pct_sq = 0.0
    if _atr_ref and len(_atr_ref.closes) >= 14 and _atr_ref.highs and _atr_ref.lows:
        _atr_v = _atr(_atr_ref.highs, _atr_ref.lows, _atr_ref.closes, 14)
        _atr_pct_sq = _atr_v / _atr_ref.closes[-1] * 100 if _atr_ref.closes[-1] > 0 else 0.0

    for tf_key, d in [("4h", d4h), ("1h", d1h), ("15m", d15)]:
        if not d or len(d.closes) < 20:
            continue
        is_sq, bw, label = _bb_squeeze(d.closes, atr_pct=_atr_pct_sq)
        if label == "strong":
            pts = 14 if tf_key == "4h" else (12 if tf_key == "1h" else 8)
            squeeze_pts += pts
            squeeze_signals.append(f"🔵 BB Squeeze {tf_key} ({bw:.1f}% width) — energi terkompresi")
        elif label == "moderate":
            pts = 8 if tf_key == "4h" else (6 if tf_key == "1h" else 4)
            squeeze_pts += pts
            squeeze_signals.append(f"BB Squeeze {tf_key} ({bw:.1f}%) — kompresi sedang")

        # Candle coil confirms the squeeze
        if is_sq and d.opens and _candle_coil(d.opens, d.closes):
            squeeze_pts += 2

    squeeze_pts = min(squeeze_pts, 30)
    score += squeeze_pts
    if squeeze_signals:
        signals.extend(squeeze_signals[:2])

    # F35: flat coin bonus — genuinely coiling = ideal pre-gainer setup
    if -2.0 <= change_24h <= 2.0 and squeeze_pts > 0:
        score += 5
        signals.append(f"🟢 Flat {change_24h:+.1f}% + BB Squeeze — pre-gainer coiling ideal")

    # ── 2. Volume Accumulation (0-25 pts) ─────────────────────────────────────
    # Smart money buying quietly — volume up, price flat
    best_accum = 0
    for tf_key, d in [("1h", d1h), ("4h", d4h), ("15m", d15)]:
        if not d or len(d.closes) < 21:
            continue
        is_accum, vol_r, label = _volume_accumulation(d.closes, d.volumes)
        if label == "strong":
            pts = 25 if tf_key == "1h" else (20 if tf_key == "4h" else 15)
            if pts > best_accum:
                best_accum = pts
                signals.append(f"📦 Volume Akumulasi {tf_key} {vol_r:.1f}× — smart money masuk diam-diam")
        elif label == "moderate":
            pts = 15 if tf_key == "1h" else (12 if tf_key == "4h" else 8)
            if pts > best_accum:
                best_accum = pts
                signals.append(f"Volume naik {vol_r:.1f}× {tf_key} — akumulasi terbentuk")

    score += best_accum

    # P1.1: Volume Z-Score bonus — current vol vs 200-candle 1h baseline
    if d1h and len(d1h.volumes) >= 10:
        vol_z = _volume_zscore(d1h.volumes)
        if vol_z >= 2.5:
            score += 10
            signals.append(f"🚀 Volume spike +{vol_z:.1f}σ vs baseline 200 candle — surge institusional")
        elif vol_z >= 1.5:
            score += 5
            signals.append(f"Volume +{vol_z:.1f}σ di atas baseline 1h — akumulasi di atas normal")

    # ── 3. Funding Rate neutral/negative (0-15 pts) ───────────────────────────
    # Fuel = market not yet crowded LONG → room to run when breakout hits
    fr = ref.funding_rate   # raw (e.g. 0.0001 = 0.01%)
    if fr < -0.04 / 100:
        score += 15
        signals.append(f"🔴 Funding {fr*100:.3f}% negatif ekstrem — short squeeze fuel siap")
    elif fr < -0.01 / 100:
        score += 10
        signals.append(f"Funding {fr*100:.3f}% negatif — shorts bayar, fuel untuk pump")
    elif fr <= 0.01 / 100:
        score += 6   # near-zero = neutral, still ok
    elif fr > 0.05 / 100:
        # Crowded longs already → headwind
        score -= 8
    elif fr > 0.03 / 100:
        score -= 4

    # ── 4. OI Building (0-12 pts) + Acceleration (0-6 pts) ───────────────────
    # Open Interest rising = new money entering = conviction accumulating
    oi_chg      = ref.oi_change_pct
    oi_chg_prev = ref.oi_change_pct_prev
    if oi_chg >= 3.0:
        score += 12
        signals.append(f"📊 OI +{oi_chg:.1f}% — posisi baru masuk, konviksi meningkat")
    elif oi_chg >= 1.5:
        score += 8
        signals.append(f"OI +{oi_chg:.1f}% — akumulasi open interest")
    elif oi_chg >= 0.5:
        score += 4
    elif oi_chg < -2.0:
        score -= 5   # OI falling = liquidation / exit risk

    # P1.2: OI acceleration (delta-of-delta) — consecutive growth = institutional momentum
    if oi_chg > oi_chg_prev > 0:
        score += 6
        signals.append(f"📈 OI acceleration {oi_chg_prev:.1f}% → {oi_chg:.1f}% — momentum institusional membangun")

    # ── 5. Near Resistance < 3% (0-10 pts) ───────────────────────────────────
    # Catalyst within reach → breakout needs only small push
    near_resistance = False
    for tf_key, d in [("1h", d1h), ("4h", d4h)]:
        if not d or not d.highs:
            continue
        s_highs = _swing_highs(d.highs, lookback=5)
        close_res = [r for r in s_highs if 0 < (r - price) / price < 0.03]
        if close_res:
            dist_pct = (close_res[0] - price) / price * 100
            score += 10
            signals.append(f"🎯 Dekat resistance {tf_key} — {dist_pct:.1f}% lagi ke breakout")
            near_resistance = True
            break
    if not near_resistance:
        # F6: breakout bonus only if coin is genuinely flat — not already pumped
        for tf_key, d in [("1h", d1h)]:
            if not d or not d.highs:
                continue
            recent_high = max(d.highs[-30:]) if len(d.highs) >= 30 else max(d.highs)
            if price > recent_high * 0.99 and 0 < change_24h < 2:
                score += 5  # fresh breakout on flat coin = true pre-gainer

    # ── 6. RSI Sweet Spot 40-55 (0-8 pts) ────────────────────────────────────
    # Momentum turning up, not yet overbought — ideal pre-pump entry zone
    primary = d1h or d15 or d4h
    rsi_val = 50.0   # F106: compute once, reuse in penalties below
    if primary and primary.closes:
        rsi_val, zone = _rsi_sweet_spot(primary.closes)
        if zone == "sweet":
            score += 8
            signals.append(f"RSI {rsi_val:.0f} sweet spot — momentum naik, belum overbought")
        elif zone == "recovering":
            score += 5
            signals.append(f"RSI {rsi_val:.0f} recovering — reversal bias naik")
        elif zone == "building":
            score += 3

    # ── Penalties ─────────────────────────────────────────────────────────────

    # D2.2 (PLAN_v3): gradual 24h penalty conditioned on 1h pullback
    # If coin is up big 24h BUT pulled back 1h, it may be coiling for continuation
    _d1h = tf_map.get("1h")
    _change_1h = 0.0
    if _d1h and len(_d1h.closes) >= 2:
        _change_1h = (_d1h.closes[-1] - _d1h.closes[-2]) / _d1h.closes[-2] * 100 if _d1h.closes[-2] > 0 else 0.0

    # PLAN_v6 P4b: health-scaled with healthy_frac=0.5 — pre-gainer KEEPS its
    # flat-coin identity (a moved coin is genuinely less "pre"-anything), but a
    # move backed by rising OI + live volume no longer gets the full blind −25.
    from agents.futures.utils import momentum_health, health_scaled_penalty
    _mh1 = momentum_health(tf_map, "LONG")
    if change_24h > 15:
        if _change_1h < -2.0:   # pulled back 1h after big 24h move = potential continuation
            score -= 5
            signals.append(f"⚠ Up {change_24h:.1f}% but 1h pullback {_change_1h:.1f}% — possible re-entry zone")
        else:
            score -= health_scaled_penalty(25, _mh1, healthy_frac=0.5)   # −12.5 healthy/neutral, −25 exhausted
    elif change_24h > 8:
        if _change_1h < -1.0:   # mild pullback
            score -= 6
        else:
            score -= health_scaled_penalty(12, _mh1, healthy_frac=0.5)

    # Dumping coin = wrong direction for LONG
    if change_24h < -15:
        score -= 10

    # Overbought = late entry risk (F106: reuse rsi_val, no second _rsi() call)
    if rsi_val > 72:
        score -= 10
    elif rsi_val > 65:
        score -= 5

    # High positive funding = longs already crowded
    if fr > 0.05 / 100:
        pass   # already penalized above

    # BUG-L14: liquidation feed is a directional PROXY (L/S-ratio shift), NOT real USDT.
    # Keep only a small directional nudge; no fake $ magnitude in score or labels.
    if ref.liq_short_usdt > 100_000:
        score += 2
        signals.append("Short squeeze terdeteksi (proxy arah) — bias bullish")
    elif ref.liq_long_usdt > 500_000:
        score += 1

    # D2.1 (PLAN_v3): differentiate ATH cases — breaking ATH with volume = fresh leg up,
    # not late entry. Near ATH but coiling = still cautious.
    if d4h and len(d4h.highs) >= 42:
        ath_7d = max(d4h.highs[-42:])
        if ath_7d > 0:
            pct_from_ath = (price - ath_7d) / ath_7d
            # Volume confirmation for breakout
            _vol_ratio_1h = 1.0
            if _d1h and len(_d1h.volumes) >= 5:
                _vol_avg_1h = sum(_d1h.volumes[-5:]) / 5
                _vol_ratio_1h = _d1h.volumes[-1] / _vol_avg_1h if _vol_avg_1h > 0 else 1.0
            if pct_from_ath >= 0.005 and _vol_ratio_1h >= 1.5:
                # Breaking ATH with volume = continuation thesis (fresh leg up)
                score += 8
                signals.append(f"🚀 Break 7d ATH +{pct_from_ath:.1%} vol {_vol_ratio_1h:.1f}× — fresh leg up")
            elif -0.02 <= pct_from_ath < 0.005:
                # Near ATH but not breaking → cautious (milder than before)
                score -= 10
                signals.append(f"⚠️ Near 7d ATH ({pct_from_ath:+.1%}) — late entry risk")
            elif pct_from_ath >= -0.05:
                score -= 5
                signals.append(f"Dekat 7d ATH ({pct_from_ath:+.1%}) — cautious")

    return score, signals[:5]


# ── Pre-Dump scorer (SHORT) ───────────────────────────────────────────────────

def _score_predump(
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """
    Score a symbol for pre-dump SHORT setup.
    Mirror of _score_pregainer but for downside moves.

    Pre-dump fingerprint:
      BB Squeeze at resistance    → compression at top = dump imminent
      Volume distributing, flat   → smart money selling quietly at top
      Funding HIGH                → longs overcrowded = forced unwind fuel
      OI rising at resistance     → long trap, forced unwind when support breaks
      Near resistance < 2%        → rejection zone
      RSI 55-70 fading zone       → momentum stalling, reversal approaching
    """
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref  = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── 1. BB Squeeze at resistance (0-30 pts) ────────────────────────────────
    # Compression at top = energy loading for a drop, not a pump
    squeeze_pts = 0
    squeeze_signals: list[str] = []

    # D3.1 (PLAN_v3): compute ATR for adaptive BB thresholds
    _atr_ref_d = d1h or d4h or d15
    _atr_pct_sq_d = 0.0
    if _atr_ref_d and len(_atr_ref_d.closes) >= 14 and _atr_ref_d.highs and _atr_ref_d.lows:
        _atr_v_d = _atr(_atr_ref_d.highs, _atr_ref_d.lows, _atr_ref_d.closes, 14)
        _atr_pct_sq_d = _atr_v_d / _atr_ref_d.closes[-1] * 100 if _atr_ref_d.closes[-1] > 0 else 0.0

    for tf_key, d in [("4h", d4h), ("1h", d1h), ("15m", d15)]:
        if not d or len(d.closes) < 20:
            continue
        is_sq, bw, label = _bb_squeeze(d.closes, atr_pct=_atr_pct_sq_d)
        if label == "strong":
            pts = 14 if tf_key == "4h" else (12 if tf_key == "1h" else 8)
            squeeze_pts += pts
            squeeze_signals.append(f"🔴 BB Squeeze {tf_key} ({bw:.1f}%) di puncak — energi dump terkompres")
        elif label == "moderate":
            pts = 8 if tf_key == "4h" else (6 if tf_key == "1h" else 4)
            squeeze_pts += pts
            squeeze_signals.append(f"BB Squeeze {tf_key} ({bw:.1f}%) — kompresi di area resistance")

        if is_sq and d.opens and _candle_coil(d.opens, d.closes):
            squeeze_pts += 2

    squeeze_pts = min(squeeze_pts, 30)
    score += squeeze_pts
    if squeeze_signals:
        signals.extend(squeeze_signals[:2])

    # ── 2. Volume distribution at top (0-25 pts) ─────────────────────────────
    # Vol rising while price flat at a HIGH level = distribution, not accumulation
    best_dist = 0
    for tf_key, d in [("1h", d1h), ("4h", d4h), ("15m", d15)]:
        if not d or len(d.closes) < 21:
            continue
        avg_vol    = sum(d.volumes[-21:-1]) / 20 if len(d.volumes) >= 21 else 0
        cur_vol    = d.volumes[-1] if d.volumes else 0
        vol_ratio  = cur_vol / avg_vol if avg_vol > 0 else 1.0
        # Price flat at top = distribution (same pattern as accumulation but at HIGH)
        price_move = abs((d.closes[-1] - d.closes[-5]) / d.closes[-5]) if len(d.closes) >= 5 and d.closes[-5] > 0 else 1.0

        if vol_ratio >= 2.5 and price_move < 0.03:   # F37: distribution doesn't require price near exact 30-candle high
            pts = 25 if tf_key == "1h" else (20 if tf_key == "4h" else 15)
            if pts > best_dist:
                best_dist = pts
                signals.append(f"📤 Volume distribusi {tf_key} {vol_ratio:.1f}× — smart money exit diam-diam")
        elif vol_ratio >= 1.8 and price_move < 0.04:
            pts = 12 if tf_key == "1h" else 8
            if pts > best_dist:
                best_dist = pts
                signals.append(f"Volume naik {vol_ratio:.1f}× {tf_key} di area tinggi — potensi distribusi")

    score += best_dist

    # ── 3. Funding rate HIGH (0-15 pts) ──────────────────────────────────────
    # Longs overcrowded → forced unwind when price starts dropping
    fr = ref.funding_rate
    if fr > 0.08 / 100:
        score += 15
        signals.append(f"🔴 Funding +{fr*100:.3f}% ekstrem — longs overcrowded, long squeeze fuel")
    elif fr > 0.05 / 100:
        score += 10
        signals.append(f"Funding +{fr*100:.3f}% tinggi — longs bayar mahal, potensi exit massal")
    elif fr > 0.02 / 100:
        score += 5
    elif fr < 0:
        # Negative funding = shorts paying = headwind for SHORT
        score -= 8

    # ── 4. OI rising at resistance (0-12 pts) + Acceleration (0-5 pts) ────────
    # New longs entering at resistance = long trap (will be forced to close on drop)
    oi_chg      = ref.oi_change_pct
    oi_chg_prev = ref.oi_change_pct_prev
    if oi_chg >= 3.0 and change_24h > 2:
        score += 12
        signals.append(f"📊 OI +{oi_chg:.1f}% saat harga naik — long trap forming, forced unwind imminent")
    elif oi_chg >= 1.5 and change_24h > 0:
        score += 7
        signals.append(f"OI +{oi_chg:.1f}% — posisi long baru di area resistance")
    elif oi_chg >= 0.5:
        score += 3
    elif oi_chg < -2.0:
        score -= 4  # OI falling = longs already exiting

    # P1.2: OI acceleration at resistance = long trap deepening each hour
    if oi_chg > oi_chg_prev > 0 and change_24h > 1:
        score += 5
        signals.append(f"📈 OI acceleration {oi_chg_prev:.1f}% → {oi_chg:.1f}% di resistance — long trap deepening")

    # ── 5. Near resistance < 2% (0-10 pts) ───────────────────────────────────
    # Price hugging resistance = rejection zone, short entry ideal
    near_resistance = False
    for tf_key, d in [("1h", d1h), ("4h", d4h)]:
        if not d or not d.highs:
            continue
        s_highs = _swing_highs(d.highs, lookback=5)
        at_res = [r for r in s_highs if abs(price - r) / price < 0.02 and r >= price * 0.99]
        if at_res:
            dist_pct = abs(at_res[0] - price) / price * 100
            score += 10
            signals.append(f"🎯 Di zona resistance {tf_key} — {dist_pct:.1f}% dari rejection level")
            near_resistance = True
            break

    if not near_resistance:
        # Already broke resistance cleanly = don't short (missed the rejection)
        for tf_key, d in [("1h", d1h)]:
            if d and d.highs:
                recent_high = max(d.highs[-20:]) if len(d.highs) >= 20 else max(d.highs)
                if price > recent_high * 1.02:
                    score -= 5   # already broke out, shorting now is dangerous

    # ── 6. RSI fading zone 55-70 (0-8 pts) ───────────────────────────────────
    # Momentum stalling in this zone = about to reject, ideal SHORT entry
    primary = d1h or d15 or d4h
    rsi_val = 50.0   # compute once, reuse in penalties
    if primary and primary.closes:
        rsi_val = _rsi(primary.closes, 14)
        if 58 <= rsi_val <= 70:
            score += 8
            signals.append(f"RSI {rsi_val:.0f} fading zone — momentum stalling, reversal approaching")
        elif 70 < rsi_val <= 80:
            score += 5   # overbought, could still go higher but risk elevated
            signals.append(f"RSI {rsi_val:.0f} overbought — extended, rawan koreksi tajam")
        elif rsi_val < 40:
            score -= 8   # oversold = dangerous to short

    # ── Penalties ─────────────────────────────────────────────────────────────

    # Already dumped big = missed the move down
    if change_24h < -12:
        score -= 20
    elif change_24h < -6:
        score -= 10

    # Already pumping hard = momentum too strong for SHORT
    if change_24h > 15:
        score -= 12

    # BUG-L14: liquidation feed is a directional PROXY, not real USDT — small nudge only.
    if ref.liq_long_usdt > 100_000:
        score += 2
        signals.append("💥 Long liquidation terdeteksi (proxy arah) — bias bearish")
    elif ref.liq_short_usdt > 500_000:
        # Shorts getting squeezed = headwind for a new SHORT
        score -= 2

    # Oversold RSI = avoid short (reuse rsi_val, no second _rsi() call)
    if rsi_val < 30:
        score -= 10

    return score, signals[:5]


# ── Trade levels ──────────────────────────────────────────────────────────────

def _calc_levels(
    direction: str,
    tf_map:    dict[str, FuturesData],
    price:     float,
) -> Optional[dict]:
    """
    Trade levels for LONG or SHORT.
    LONG:  SL below swing low, TP at resistance.
    SHORT: SL above swing high, TP at support.
    """
    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    if not d1h or len(d1h.closes) < 20:
        return None

    atr     = _atr(d1h.highs, d1h.lows, d1h.closes, 14)
    atr_pct = atr / price * 100 if price > 0 else 0
    rp      = _round_price

    if direction == "LONG":
        s_lows   = _swing_lows(d1h.lows, lookback=5)
        below    = [s for s in s_lows if s < price * 0.999]
        swing_sl = max(below) if below else min(d1h.lows[-20:])
        sl       = swing_sl - atr * 0.3
        risk     = price - sl
        risk_pct = risk / price * 100

        # BUG-L3/L5: SL floor — too-tight stops get hit by noise; too-wide → ATR fallback.
        min_sl_pct = max(MIN_SL_PCT, atr_pct * 1.0)   # PLAN_v11 B1: lebih lebar — leverage bikin SL ketat kena noise
        if risk_pct > 8.0:
            sl       = price - atr * 1.5
            risk     = price - sl
            risk_pct = risk / price * 100
        if risk_pct < min_sl_pct:
            risk     = price * (min_sl_pct / 100)
            sl       = price - risk
            risk_pct = min_sl_pct

        s_highs   = _swing_highs(d1h.highs, lookback=5)
        if d4h:
            s_highs += _swing_highs(d4h.highs, lookback=3)
        # PLAN_v6 P2a/P2b: TP1 near (1×risk, was 1.5×) so it's actually reachable;
        # TP2 CAPPED at 2.5×risk so it can't float to a far resistance (the 16%-away
        # TP2 that never hit while SL at 5% did). Take the NEARER of {resistance, cap}.
        tp2_cap   = price + risk * 2.5
        valid_res = sorted([h for h in s_highs if h > price * 1.005])
        tp2 = min(valid_res[0], tp2_cap) if valid_res else tp2_cap
        tp1 = rp(price + risk * 1.0, price)
        tp3 = rp(price + risk * 5.0, price)
        tp1_pct = (tp1 - price) / price * 100
        tp2_pct = (tp2 - price) / price * 100
        tp3_pct = (tp3 - price) / price * 100

    else:  # SHORT
        s_highs  = _swing_highs(d1h.highs, lookback=5)
        above    = [h for h in s_highs if h > price * 1.001]
        swing_sl = min(above) if above else max(d1h.highs[-20:])
        sl       = swing_sl + atr * 0.3
        risk     = sl - price
        risk_pct = risk / price * 100

        # BUG-L3/L5: SL floor — too-tight stops get hit by noise; too-wide → ATR fallback.
        min_sl_pct = max(MIN_SL_PCT, atr_pct * 1.0)   # PLAN_v11 B1: lebih lebar — leverage bikin SL ketat kena noise
        if risk_pct > 8.0:
            sl       = price + atr * 1.5
            risk     = sl - price
            risk_pct = risk / price * 100
        if risk_pct < min_sl_pct:
            risk     = price * (min_sl_pct / 100)
            sl       = price + risk
            risk_pct = min_sl_pct

        s_lows   = _swing_lows(d1h.lows, lookback=5)
        if d4h:
            s_lows += _swing_lows(d4h.lows, lookback=3)
        # PLAN_v6 P2a/P2b: TP1 near (1×risk), TP2 capped at 2.5×risk (nearer of
        # {support, cap} — for SHORT the nearer target is the HIGHER price = max).
        tp2_cap   = price - risk * 2.5
        valid_sup = sorted([l for l in s_lows if l < price * 0.995], reverse=True)
        tp2 = max(valid_sup[0], tp2_cap) if valid_sup else tp2_cap
        tp1 = rp(price - risk * 1.0, price)
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
    Evaluate a symbol for Agent 1 (Pre-Gainer / Pre-Dump Scout).
    F34: Returns ALL valid directions (LONG and/or SHORT) where score ≥ MIN_SCORE.
    Both directions are returned independently if both qualify.
    F68/F69/F72: applies weight cache, adaptive threshold, and regime modifier.
    """
    if not tf_map:
        return []

    ref   = tf_map.get("1h") or tf_map.get("4h") or next(iter(tf_map.values()))
    price = ref.closes[-1] if ref.closes else 0.0
    if price <= 0:
        return []

    # F68/F69/F72: load in-memory caches (synchronous — no await needed)
    from agents.futures import weight_updater
    from agents.futures.regime import detect_coin_regime
    from agents.shared.cross_agent_learning import get_cross_weight, blend_weights
    thresholds    = weight_updater.get_adaptive_thresholds(AGENT_NAME)
    effective_min = thresholds["min_score"]
    # BUG-L13: per-coin regime from the coin's own 1h OHLCV (was BTC-only for all alts)
    regime        = detect_coin_regime(tf_map.get("1h") or ref)
    # P3.5: regime-conditional weight cache (falls back to "all" for missing keys)
    weight_cache  = weight_updater.get_weight_cache(AGENT_NAME, regime=regime)

    long_score,  long_sigs  = _score_pregainer(tf_map, price, change_24h)
    short_score, short_sigs = _score_predump(tf_map, price, change_24h)

    results = []
    for direction, score, signals in [
        ("LONG",  long_score,  long_sigs),
        ("SHORT", short_score, short_sigs),
    ]:
        # F68 + SP3: apply signal weight (own-agent blended with cross-agent evidence).
        # P3.7: multiplier ×7 (was ×5) — wider impact so adaptive learning has real bite.
        for sig in signals:
            key   = weight_updater.normalize_signal_key(sig)
            own_w = weight_cache.get(key, 1.0)
            w     = blend_weights(own_w, get_cross_weight(key))
            score += (w - 1.0) * 7.0

        # F72: regime modifier — reward alignment, penalize counter-trend
        if regime == "volatile":
            score *= 0.85
        elif regime == "trending_up" and direction == "LONG":
            score += 5
        elif regime == "trending_down" and direction == "SHORT":
            score += 5
        elif regime == "trending_up" and direction == "SHORT":
            score -= 5
        elif regime == "trending_down" and direction == "LONG":
            score -= 5

        # F92: per-coin win rate bonus/penalty (±5 pts, needs ≥3 historical trades)
        score += weight_updater.get_coin_bonus(symbol, direction)  # P4.8: directional

        if score < effective_min:   # F69: adaptive threshold
            # P7.1: log rejection so UI can explain "why not opened"
            _weak = sorted(
                ((weight_updater.normalize_signal_key(s),
                  weight_cache.get(weight_updater.normalize_signal_key(s), 1.0))
                 for s in signals),
                key=lambda x: x[1]
            )[:3]
            weight_updater.log_rejection(symbol, AGENT_NAME, direction, score, effective_min,
                                         regime=regime, weak_signals=[f"{k}:{w}" for k, w in _weak])
            continue
        # PLAN_v6 P3: candle-level timing gate — reject entries into an exhaustion
        # wick or a mature move that hasn't pulled back yet (score is a snapshot;
        # this validates the entry candle itself). No OI-confirm for pre-gainer:
        # its universe is flat coins where OI is legitimately quiet.
        from agents.futures.utils import entry_timing_ok
        _t_ok, _t_why = entry_timing_ok(tf_map, direction, change_24h)
        if not _t_ok:
            logger.debug("entry_timing_reject", symbol=symbol, agent=AGENT_NAME,
                         direction=direction, reason=_t_why, score=round(score, 1))
            continue
        levels = _calc_levels(direction, tf_map, price)
        if not levels:
            continue
        atr_pct  = levels.pop("atr_pct")
        leverage = calc_leverage(atr_pct, score, levels["risk_pct"], lane="pre_gainer", change_24h=change_24h)
        results.append({
            "symbol":       symbol,
            "direction":    direction,
            "price":        round(price, 8),
            "score":        round(min(score, 100), 1),   # F7: cap at 100, not 99
            "signals":      signals,
            "leverage":     leverage,
            "change_24h":   round(change_24h, 2),
            "funding_rate": round(ref.funding_rate * 100, 4),
            "oi_change":    round(ref.oi_change_pct, 2),
            "liq_long":     round(ref.liq_long_usdt / 1e6, 3),
            "liq_short":    round(ref.liq_short_usdt / 1e6, 3),
            "agent":        AGENT_NAME,
            "setup_type":   "pre_gainer",   # PLAN_v2 — lane disambiguated from accumulation
            "regime":       regime,         # BUG-L13: per-coin regime (for trade.regime/learning)
            "atr_pct":      atr_pct,        # PLAN_v15: monitor needs it (G4 rugpull + P9 fail-fast)
            **levels,
        })
    return results
