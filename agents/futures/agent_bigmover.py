"""
Agent Big Mover — Phase 2 BM1.

Lane terpisah untuk extreme movers (±15% < change_24h < ±150%) yang TIDAK
bisa di-tangkap A1/A2/A3 karena math impossibility (lihat PLAN-BIG-MOVERS-DATA.md V2).

Paradigma berbeda dari A1-A3:
  - NO anti-momentum penalty (A1 hardstop change_24h>15 → −25 mati di sini)
  - Direction INFERRED dari change_24h sign — momentum ITSELF adalah arah
  - Threshold FIXED 60 (TIDAK adaptive — A2 death-spiral safe)
  - Cooldown 30 min + reset jika score naik +10 (B2.2)
  - Funding hard-gate: LONG ≤ +0.12%, SHORT ≥ −0.12%
  - SL ATR×1.5 (floor 2.5%, ceiling 8%, fallback fixed 4% kalau ATR<0.5%)
  - TP1 ATR×2 | TP2 ATR×4 | TP3 ATR×6 — R:R ≥ 1:2
  - Leverage FIXED 3x (anti-blowup pada coin volatil)
  - Risk pct 0.5% (separuh A1-A3)
  - Max concurrent terpisah dari main pool (2 slot)

Bug mitigations baked in:
  B2.1 — direction confirmed by `change_1h` searah `change_24h`
  G14  — noise filter (price gap 30+ min, spread, vol=0 candles)
  G18  — entry-trap: skip kalau change_30m > 15% pada arah yang sama (puncak literal)
"""

import time
from typing import Optional

import structlog

from .data import FuturesData
from .agent1 import (
    _rsi, _swing_lows, _swing_highs, _round_price,
    _atr,
    MIN_SL_PCT,
)
from .utils import cap_leverage_by_lane   # PLAN_v2 P1.2/P1.3
from app.services.slippage_sim import calculate_entry_slippage

logger = structlog.get_logger(__name__)

AGENT_NAME = "futures_agent_bigmover"

MIN_SCORE        = 60          # fixed, no death spiral
MIN_RR           = 2.0         # 1:2 — trade-off speed vs RR
MIN_CHANGE_24H   = 15.0        # ±15% minimum to qualify
# PLAN_v6 P4a: was 150 — that cap made the Big Mover agent reject the biggest movers
# (NFP/TAIKO/MZBT-type). 150–300% is now the "extreme" tier traded at HALF size
# instead of rejected; only >300% (true blow-off territory) is skipped.
MAX_CHANGE_24H     = 300.0
EXTREME_CHANGE_24H = 150.0     # ≥ this → extreme tier: size ½ (time-stop 90m already on)

# SL/TP bracket
SL_ATR_MULT      = 1.5
TP1_ATR_MULT     = 2.0
TP2_ATR_MULT     = 4.0
TP3_ATR_MULT     = 6.0
SL_FLOOR_PCT     = 2.5
SL_CEILING_PCT   = 8.0
SL_FALLBACK_PCT  = 4.0         # if ATR < 0.5% — coin too quiet, use fixed

# Fixed leverage — A1-A3 mature ATR-based, BM coins too volatile
FIXED_LEVERAGE   = 3
RISK_PCT_DEFAULT = 0.5         # 0.5% wallet — separuh main lanes

# Funding hard gate
MAX_LONG_FUNDING_PCT  = 0.12   # >0.12% LONG bayar mahal
MIN_SHORT_FUNDING_PCT = -0.12  # < -0.12% SHORT bayar mahal

# G18 — entry-trap threshold: 30-min move > 15% same direction = puncak
ENTRY_TRAP_30M_PCT = 15.0

# Cost guard — fees ≈ 0.10% round-trip + 0.3% slippage on extreme movers
MIN_TP1_NET_PCT  = 2.0         # TP1 wajib ≥ 2× cost (~1% all-in)
FUTURES_FEE_PCT  = 0.08        # 0.04% × 2 round-trip taker fee
MIN_NET_EV_PCT   = 1.5         # P2: projected net profit after fees+slippage must be ≥ 1.5%


# ── Helpers ────────────────────────────────────────────────────────────────────

def _change_pct(closes: list[float], lookback_candles: int) -> float:
    """Return % change over `lookback_candles` (closes[-lookback-1] to last)."""
    if len(closes) < lookback_candles + 1:
        return 0.0
    prev = closes[-(lookback_candles + 1)]
    if prev <= 0:
        return 0.0
    return (closes[-1] - prev) / prev * 100


def _has_data_gap(closes: list[float], volumes: list[float], lookback: int = 10) -> bool:
    """
    G14 noise filter — flag if recent N candles have >=3 zero-vol or zero-move
    candles. Often indicates wash trading or stale/feed-broken data.
    """
    if len(closes) < lookback or len(volumes) < lookback:
        return True
    zero_vol = sum(1 for v in volumes[-lookback:] if v == 0)
    if zero_vol >= 3:
        return True
    flat = sum(
        1 for i in range(1, lookback)
        if volumes[-i] == 0 and closes[-i] == closes[-i - 1]
    )
    return flat >= 3


# PLAN_v6 P4a: _looks_like_top REMOVED — "skip when price == recent 5-candle high"
# was self-defeating for THIS lane: a coin becoming a top gainer is, by definition,
# printing new highs. For a momentum lane that's a strength signal, not a veto.
# Exhaustion protection now comes from the P3 entry-timing gate (wick/chase checks)
# in the other lanes, plus reduced size + 90m time-stop here.


# ── Scoring ────────────────────────────────────────────────────────────────────

def _score_bigmover(
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
    direction:  str,
) -> tuple[float, list[str], dict]:
    """
    Anti-momentum-penalty-free scoring.
    Returns (score, signals, diagnostics).
    """
    score   = 0.0
    signals: list[str] = []
    diag: dict = {}

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref = d1h or d15 or d4h
    if not ref:
        return 0.0, [], diag

    # 1h / 30m change for confirmation + entry-trap
    change_1h = _change_pct(d1h.closes, 1) if d1h else 0.0  # 1 hourly candle = 1h move
    change_30m = _change_pct(d15.closes, 2) if d15 else 0.0  # 2 × 15m = 30 min
    diag["change_1h"]  = round(change_1h, 2)
    diag["change_30m"] = round(change_30m, 2)

    abs_chg = abs(change_24h)

    # ── 1. Magnitude bonus (0-30 pts) — bigger move = stronger thesis ─────────
    if 15 <= abs_chg < 25:
        score += 15
        signals.append(f"Δ24h {change_24h:+.1f}% — early-stage big-mover")
    elif 25 <= abs_chg < 40:
        score += 22
        signals.append(f"Δ24h {change_24h:+.1f}% — established momentum, banyak room")
    elif 40 <= abs_chg < 70:
        score += 28
        signals.append(f"💥 Δ24h {change_24h:+.1f}% — momentum kuat, wave matang")
    elif 70 <= abs_chg < 120:
        score += 30
        signals.append(f"🚀 Δ24h {change_24h:+.1f}% — parabolic, sangat agresif")
    elif 120 <= abs_chg < EXTREME_CHANGE_24H:
        score += 25
        signals.append(f"⚠ Δ24h {change_24h:+.1f}% — di ujung jangkauan, hati-hati reversal")
    else:  # PLAN_v6 P4a: 150-300 extreme tier — tradeable at half size, not rejected
        score += 20
        signals.append(f"🔥 Δ24h {change_24h:+.1f}% — EXTREME tier: size ½, time-stop ketat")

    # ── 2. B2.1 — direction confirm via change_1h ─────────────────────────────
    if direction == "LONG":
        if change_1h > 1.0:
            score += 18
            signals.append(f"1h +{change_1h:.1f}% confirm — masih searah momentum")
        elif change_1h > -1.0:
            score += 10
            signals.append(f"1h {change_1h:+.1f}% sideways pullback — re-entry zone")
        elif change_1h > -5.0:
            score += 4   # mild pullback — bisa entry tapi lemah
        else:
            score -= 20  # 1h reverse strong = LONG bahaya
            signals.append(f"⚠ 1h {change_1h:+.1f}% reverse — kontra arah")
    else:  # SHORT
        if change_1h < -1.0:
            score += 18
            signals.append(f"1h {change_1h:+.1f}% confirm — masih dump")
        elif change_1h < 1.0:
            score += 10
            signals.append(f"1h {change_1h:+.1f}% bounce — re-entry zone SHORT")
        elif change_1h < 5.0:
            score += 4
        else:
            score -= 20
            signals.append(f"⚠ 1h +{change_1h:.1f}% bounce kuat — kontra arah")

    # ── 3. Volume confirmation (0-20 pts) — buyer/seller pressure now ─────────
    best_vol = 0
    for tf_key, d in [("1h", d1h), ("15m", d15)]:
        if not d or len(d.volumes) < 22:
            continue
        avg_vol = sum(d.volumes[-21:-1]) / 20
        cur_vol = d.volumes[-1]
        ratio   = cur_vol / avg_vol if avg_vol > 0 else 1.0
        if ratio >= 3.0:
            best_vol = max(best_vol, 20 if tf_key == "1h" else 15)
            signals.append(f"Volume {ratio:.1f}× {tf_key} — pressure dikonfirmasi")
            break
        elif ratio >= 2.0:
            best_vol = max(best_vol, 14 if tf_key == "1h" else 10)
        elif ratio >= 1.3:
            best_vol = max(best_vol, 6)
    score += best_vol

    # ── 4. OI confirmation (0-15 pts) ─────────────────────────────────────────
    oi_chg = ref.oi_change_pct
    if direction == "LONG":
        if oi_chg >= 5:
            score += 15
            signals.append(f"OI +{oi_chg:.1f}% — new longs masuk")
        elif oi_chg >= 2:
            score += 8
        elif oi_chg < -3:
            score -= 8  # pure short squeeze, risky
            signals.append(f"⚠ OI {oi_chg:.1f}% turun — short squeeze, bukan real long")
    else:  # SHORT
        if oi_chg >= 5:
            score += 15
            signals.append(f"OI +{oi_chg:.1f}% saat turun — short conviction nyata")
        elif oi_chg >= 2:
            score += 8
        elif oi_chg < -3:
            score -= 5  # long capitulation, weak short setup

    # ── 5. Funding confirms thesis (0-10 pts) ─────────────────────────────────
    # NOTE: hard gate done OUTSIDE scoring (caller filters extreme funding).
    fr_pct = ref.funding_rate * 100
    diag["funding_pct"] = round(fr_pct, 4)
    if direction == "LONG":
        if fr_pct < 0:
            score += 10
            signals.append(f"Funding {fr_pct:.3f}% negatif — shorts bayar LONG, squeeze fuel")
        elif fr_pct < 0.05:
            score += 6
        elif fr_pct > 0.10:
            score -= 5  # mendekati cap
    else:
        if fr_pct > 0:
            score += 10
        elif fr_pct > -0.05:
            score += 6
        elif fr_pct < -0.10:
            score -= 5

    # ── 6. RSI position check — wajar (0-12 pts) ──────────────────────────────
    rsi_val = _rsi(ref.closes, 14) if ref.closes else 50.0
    diag["rsi"] = round(rsi_val, 1)
    if direction == "LONG":
        if 60 <= rsi_val <= 78:
            score += 12
        elif 78 < rsi_val <= 85:
            score += 5
            signals.append(f"RSI {rsi_val:.0f} overbought tapi big-mover lane masih ride")
        elif rsi_val > 85:
            score -= 5     # extreme — likely top
    else:  # SHORT
        if 22 <= rsi_val <= 40:
            score += 12
        elif 15 <= rsi_val < 22:
            score += 5
        elif rsi_val < 15:
            score -= 5     # extreme oversold — bounce risk

    return score, signals[:6], diag


# ── Trade levels ──────────────────────────────────────────────────────────────

def _calc_levels(
    direction: str,
    tf_map:    dict[str, FuturesData],
    price:     float,
) -> Optional[dict]:
    """SL ATR×1.5 (floor 2.5%, ceiling 8%, fallback 4% kalau ATR <0.5%).
    TP1 ATR×2 / TP2 ATR×4 / TP3 ATR×6.
    """
    ref = tf_map.get("1h") or tf_map.get("15m") or tf_map.get("4h")
    if not ref or len(ref.closes) < 20 or price <= 0:
        return None

    atr     = _atr(ref.highs, ref.lows, ref.closes, 14)
    atr_pct = atr / price * 100 if price > 0 else 0.0
    rp      = _round_price

    # SL fallback kalau ATR terlalu kecil
    if atr_pct < 0.5:
        sl_pct = SL_FALLBACK_PCT
    else:
        sl_pct = max(SL_FLOOR_PCT, min(SL_CEILING_PCT, atr_pct * SL_ATR_MULT))

    risk = price * (sl_pct / 100)
    if risk <= 0:
        return None

    if direction == "LONG":
        sl  = price - risk
        tp1 = price + atr * TP1_ATR_MULT if atr_pct >= 0.5 else price * (1 + sl_pct * TP1_ATR_MULT / 100 / SL_ATR_MULT)
        tp2 = price + atr * TP2_ATR_MULT if atr_pct >= 0.5 else price * (1 + sl_pct * TP2_ATR_MULT / 100 / SL_ATR_MULT)
        tp3 = price + atr * TP3_ATR_MULT if atr_pct >= 0.5 else price * (1 + sl_pct * TP3_ATR_MULT / 100 / SL_ATR_MULT)
        tp1_pct = (tp1 - price) / price * 100
        tp2_pct = (tp2 - price) / price * 100
        tp3_pct = (tp3 - price) / price * 100
    else:
        sl  = price + risk
        tp1 = price - atr * TP1_ATR_MULT if atr_pct >= 0.5 else price * (1 - sl_pct * TP1_ATR_MULT / 100 / SL_ATR_MULT)
        tp2 = price - atr * TP2_ATR_MULT if atr_pct >= 0.5 else price * (1 - sl_pct * TP2_ATR_MULT / 100 / SL_ATR_MULT)
        tp3 = price - atr * TP3_ATR_MULT if atr_pct >= 0.5 else price * (1 - sl_pct * TP3_ATR_MULT / 100 / SL_ATR_MULT)
        tp1_pct = (price - tp1) / price * 100
        tp2_pct = (price - tp2) / price * 100
        tp3_pct = (price - tp3) / price * 100

    # TP1 wajib ≥ 2× cost — kalau ATR terlalu kecil, TP1 bisa di bawah biaya
    if abs(tp1_pct) < MIN_TP1_NET_PCT:
        return None

    rr = abs(tp2 - price) / risk
    if rr < MIN_RR:
        return None

    return {
        "entry":    rp(price, price),
        "sl":       rp(sl, price),
        "tp1":      rp(tp1, price),
        "tp2":      rp(tp2, price),
        "tp3":      rp(tp3, price),
        "risk_pct": round(sl_pct, 2),
        "tp1_pct":  round(tp1_pct, 2),
        "tp2_pct":  round(tp2_pct, 2),
        "tp3_pct":  round(tp3_pct, 2),
        "rr_ratio": round(rr, 1),
        "atr_pct":  round(atr_pct, 2),
    }


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_symbol(
    symbol:        str,
    tf_map:        dict[str, FuturesData],
    change_24h:    float,
    quote_vol_24h: float = 0.0,   # P1: 24h USDT volume for slippage tier (B4.1)
) -> list[dict]:
    """
    Returns list of valid setups (0 or 1 — direction inferred from change_24h sign).
    """
    if not tf_map:
        return []

    ref   = tf_map.get("1h") or tf_map.get("15m") or tf_map.get("4h")
    if not ref:
        return []
    price = ref.closes[-1] if ref.closes else 0.0
    if price <= 0:
        return []

    abs_chg = abs(change_24h)
    if abs_chg < MIN_CHANGE_24H or abs_chg > MAX_CHANGE_24H:
        return []

    direction = "LONG" if change_24h > 0 else "SHORT"

    # ── G17 — delisting risk guard ───────────────────────────────────────────
    try:
        from agents.futures.delisting_monitor import is_delisting_risk
        if is_delisting_risk(symbol):
            logger.debug("bigmover_delisting_skip", symbol=symbol)
            return []
    except Exception:
        pass

    # ── G14 — noise filter ────────────────────────────────────────────────────
    if _has_data_gap(ref.closes, ref.volumes, lookback=10):
        return []   # wash/broken feed — skip

    # ── G18 — entry-trap: PLAN_v6 P4a → REDUCE SIZE, not reject ────────────────
    # A 15%+ 30-min burst IS risky (possible local climax), but for a big-mover lane
    # rejecting it outright meant rejecting exactly the coins this lane exists for.
    # Now: enter at half size instead. (price==high guard removed entirely — new highs
    # are a strength signal for momentum, see _looks_like_top removal note above.)
    size_mult = 1.0
    d15 = tf_map.get("15m")
    if d15 and len(d15.closes) >= 3:
        chg_30m = _change_pct(d15.closes, 2)
        if (direction == "LONG" and chg_30m > ENTRY_TRAP_30M_PCT) or \
           (direction == "SHORT" and chg_30m < -ENTRY_TRAP_30M_PCT):
            size_mult *= 0.5

    # PLAN_v6 P4a: extreme tier (150-300%) — tradeable but at half size
    if abs_chg >= EXTREME_CHANGE_24H:
        size_mult *= 0.5
    size_mult = max(size_mult, 0.25)   # floor: compound reductions stop at ¼

    # ── Funding hard gate (also re-checked in auto_trader before order) ───────
    fr_pct = ref.funding_rate * 100
    if direction == "LONG" and fr_pct > MAX_LONG_FUNDING_PCT:
        return []
    if direction == "SHORT" and fr_pct < MIN_SHORT_FUNDING_PCT:
        return []

    # ── Score ─────────────────────────────────────────────────────────────────
    score, signals, diag = _score_bigmover(tf_map, price, change_24h, direction)

    # P3.6: apply adaptive signal weights (BigMover was previously excluded from learning)
    try:
        from agents.futures import weight_updater
        from agents.shared.cross_agent_learning import get_cross_weight, blend_weights
        wc = weight_updater.get_weight_cache(AGENT_NAME)
        for sig in signals:
            key   = weight_updater.normalize_signal_key(sig)
            own_w = wc.get(key, 1.0)
            w     = blend_weights(own_w, get_cross_weight(key))
            score += (w - 1.0) * 7.0
    except Exception:
        pass   # never block scan due to weight error

    if score < MIN_SCORE:
        return []

    levels = _calc_levels(direction, tf_map, price)
    if not levels:
        return []

    # P2: MIN_NET_EV gate — projected TP2 net profit must cover fees + dynamic slippage
    slip_pct = calculate_entry_slippage(quote_vol_24h)
    net_tp2  = levels.get("tp2_pct", 0) - FUTURES_FEE_PCT - slip_pct
    if net_tp2 < MIN_NET_EV_PCT:
        logger.debug("bigmover_min_net_ev_skip", symbol=symbol,
                     tp2_pct=levels.get("tp2_pct"), slip=slip_pct, net=net_tp2)
        return []

    atr_pct = levels.pop("atr_pct")
    # PLAN_v2 P1.2/P1.3 — even with FIXED_LEVERAGE=3 (currently safe), pipe through the cap
    # so any future bump cannot accidentally violate the bigmover lane safety budget (20%).
    leverage = cap_leverage_by_lane(FIXED_LEVERAGE, levels.get("risk_pct", 0.0), lane="bigmover")

    return [{
        "symbol":       symbol,
        "direction":    direction,
        "price":        round(price, 8),
        "score":        round(min(score, 100), 1),
        "signals":      signals,
        "leverage":     leverage,
        "change_24h":   round(change_24h, 2),
        "change_1h":    diag.get("change_1h", 0),
        "change_30m":   diag.get("change_30m", 0),
        "rsi":          diag.get("rsi", 50),
        "funding_rate": round(ref.funding_rate * 100, 4),
        "oi_change":    round(ref.oi_change_pct, 2),
        "liq_long":     round(ref.liq_long_usdt / 1e6, 3),
        "liq_short":    round(ref.liq_short_usdt / 1e6, 3),
        "agent":        AGENT_NAME,
        "setup_type":   "bigmover",
        "regime":       "n/a",         # bigmover lane bypasses regime filter — uses funding/dir confirm instead
        "size_mult":    round(size_mult, 2),   # PLAN_v6 P4a: G18/extreme-tier size reduction (auto_trader applies)
        "atr_pct":       atr_pct,
        "quote_vol_24h": quote_vol_24h,    # P1: stored so auto_trader can compute slippage
        "entry_slippage_pct": slip_pct,    # P1: pre-computed for meta
        **levels,
    }]
