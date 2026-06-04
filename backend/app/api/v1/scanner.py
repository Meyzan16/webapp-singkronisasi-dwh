"""
24H Scanner Agent — early breakout detection per trading style.

Each style has different:
- Timeframe (candle period)
- Scoring weights (what matters most)
- Lookback periods (RSI, BB, recent high/low)
- ATR multipliers (SL/TP sizing)
- Minimum score threshold (noise filter)

Scalping  → momentum speed, RSI extremes, vol spike — fast signals
Day Trade → trend + momentum balance — intraday setups
Swing     → BB squeeze, accumulation, breakout zones — multi-day
Position  → macro trend, weekly S/R, deep accumulation — weeks/months
"""

import asyncio
import math
import time
from dataclasses import dataclass

import httpx
import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.binance_urls import fapi

router = APIRouter(tags=["scanner"])
logger = structlog.get_logger(__name__)


_cache: dict[str, dict] = {}
CACHE_TTL = 300  # 5 min — local live-scan cache (fallback only)


# ── Style configs ──────────────────────────────────────────────────────────────

@dataclass
class StyleConfig:
    timeframe: str
    candle_limit: int
    rsi_period: int
    bb_period: int
    lookback: int
    squeeze_threshold: float
    vol_slope_min: float
    atr_sl_mult: float
    atr_tp_mult: float
    min_score: float
    pump_penalty_pct: float
    min_sl_pct: float   # minimum SL distance from entry (%)
    min_rr: float       # minimum R:R to show signal
    # Signal weights
    w_squeeze: float
    w_accumulation: float
    w_breakout: float
    w_rsi: float
    w_ema: float
    w_pressure: float
    w_candle: float


STYLE_CONFIGS: dict[str, StyleConfig] = {
    "scalping": StyleConfig(
        timeframe="15m", candle_limit=100,
        rsi_period=9, bb_period=14, lookback=10,
        squeeze_threshold=0.03, vol_slope_min=0.20,
        atr_sl_mult=1.0, atr_tp_mult=3.5,
        min_score=25, pump_penalty_pct=5,
        min_sl_pct=0.008,
        min_rr=3.0,
        w_squeeze=1.0, w_accumulation=0.7, w_breakout=1.5,
        w_rsi=2.0, w_ema=1.2, w_pressure=1.8, w_candle=1.5,
    ),
    "daytrading": StyleConfig(
        timeframe="1h", candle_limit=100,
        rsi_period=14, bb_period=20, lookback=15,
        squeeze_threshold=0.045, vol_slope_min=0.25,
        atr_sl_mult=1.2, atr_tp_mult=4.0,
        min_score=28, pump_penalty_pct=8,
        min_sl_pct=0.012,
        min_rr=3.0,
        w_squeeze=1.2, w_accumulation=1.2, w_breakout=1.3,
        w_rsi=1.5, w_ema=1.3, w_pressure=1.5, w_candle=1.2,
    ),
    "swing": StyleConfig(
        timeframe="4h", candle_limit=100,
        rsi_period=14, bb_period=20, lookback=20,
        squeeze_threshold=0.06, vol_slope_min=0.30,
        atr_sl_mult=1.5, atr_tp_mult=5.0,
        min_score=30, pump_penalty_pct=12,
        min_sl_pct=0.020,
        min_rr=3.0,
        w_squeeze=1.8, w_accumulation=2.0, w_breakout=1.5,
        w_rsi=1.0, w_ema=1.0, w_pressure=1.2, w_candle=0.8,
    ),
    "position": StyleConfig(
        timeframe="1d", candle_limit=120,
        rsi_period=21, bb_period=30, lookback=50,
        squeeze_threshold=0.08, vol_slope_min=0.40,
        atr_sl_mult=2.0, atr_tp_mult=7.0,
        min_score=35, pump_penalty_pct=20,
        min_sl_pct=0.030,
        min_rr=3.0,
        w_squeeze=2.0, w_accumulation=2.5, w_breakout=1.8,
        w_rsi=0.8, w_ema=1.5, w_pressure=1.0, w_candle=0.5,
    ),
}

# Style display info (for frontend)
STYLE_LABELS: dict[str, dict] = {
    "scalping":   {"label": "Scalping",  "icon": "⚡", "tf": "15m", "desc": "Menit–Jam"},
    "daytrading": {"label": "Day Trade", "icon": "📅", "tf": "1H",  "desc": "Harian"},
    "swing":      {"label": "Swing",     "icon": "🌊", "tf": "4H",  "desc": "Hari–Minggu"},
    "position":   {"label": "Position",  "icon": "🏔", "tf": "1D",  "desc": "Minggu–Bulan"},
}


# ── Schemas ────────────────────────────────────────────────────────────────────

class ScanSignal(BaseModel):
    symbol: str
    direction: str
    probability: float
    current_price: float
    entry: float                  # optimal entry (at support/resistance zone)
    entry_zone_low: float | None  # zone lower bound
    entry_zone_high: float | None # zone upper bound
    entry_type: str               # "at_zone" | "wait_pullback" | "wait_rally" | "market"
    entry_note: str
    change_24h: float
    volume_ratio: float
    signals: list[str]
    key_level: float | None
    stop_loss: float
    take_profit: float
    risk_reward: str
    alert_type: str
    sl_method: str
    tp_method: str
    style_note: str


class ScannerResponse(BaseModel):
    results: list[ScanSignal]
    scanned: int
    style: str
    style_label: str
    timeframe: str
    generated_at: int


# ── Math helpers ───────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


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
    trs = []
    for i in range(1, min(period + 1, len(closes))):
        tr = max(highs[-i] - lows[-i],
                 abs(highs[-i] - closes[-i - 1]),
                 abs(lows[-i] - closes[-i - 1]))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else closes[-1] * 0.02


def _find_sr_zones(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    lookback: int = 30,
) -> tuple[list[float], list[float]]:
    """
    Find support and resistance zones using swing pivot clustering.

    Method:
    1. Find swing highs (local maxima) → resistance candidates
    2. Find swing lows  (local minima) → support candidates
    3. Cluster nearby levels (within 0.5%) → zones
    4. Sort by number of touches (strongest first)

    Returns (support_levels, resistance_levels) sorted strongest first.
    """
    n = min(lookback, len(closes))
    h = highs[-n:]
    l = lows[-n:]
    price = closes[-1]

    swing_highs: list[float] = []
    swing_lows:  list[float] = []

    for i in range(2, n - 2):
        # Swing high: higher than 2 bars each side
        if h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]:
            swing_highs.append(h[i])
        # Swing low: lower than 2 bars each side
        if l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]:
            swing_lows.append(l[i])

    def _cluster(levels: list[float], tolerance: float = 0.005) -> list[float]:
        """Merge levels within tolerance into single zone (average)."""
        if not levels:
            return []
        sorted_lvls = sorted(levels)
        clusters: list[list[float]] = [[sorted_lvls[0]]]
        for lvl in sorted_lvls[1:]:
            if abs(lvl - clusters[-1][-1]) / clusters[-1][-1] < tolerance:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])
        # Return cluster midpoints sorted by touch count (most touches = strongest)
        return [sum(c) / len(c) for c in sorted(clusters, key=len, reverse=True)]

    supports    = [z for z in _cluster(swing_lows)  if z < price]
    resistances = [z for z in _cluster(swing_highs) if z > price]

    return supports, resistances


def _fibonacci_sl_tp(
    entry: float,
    direction: str,
    swing_high: float,
    swing_low: float,
) -> tuple[float, list[float]]:
    """
    Calculate SL and TP targets using Fibonacci levels.

    For LONG:
      SL  = entry − (swing_high − swing_low) × 0.618  → Fib retracement 61.8%
      TP1 = entry + (swing_high − swing_low) × 1.272  → Fib extension 127.2%
      TP2 = entry + (swing_high − swing_low) × 1.618  → Golden ratio extension
      TP3 = entry + (swing_high − swing_low) × 2.618  → 261.8% extension

    For SHORT: mirror logic (SL above entry, TP below).

    These are the standard Fibonacci extension levels used by institutional traders.
    """
    swing_range = swing_high - swing_low
    if swing_range <= 0:
        return entry * 0.98 if direction == "LONG" else entry * 1.02, []

    if direction == "LONG":
        sl   = entry - swing_range * 0.618
        tps  = [
            entry + swing_range * 1.272,
            entry + swing_range * 1.618,
            entry + swing_range * 2.618,
        ]
    else:
        sl   = entry + swing_range * 0.618
        tps  = [
            entry - swing_range * 1.272,
            entry - swing_range * 1.618,
            entry - swing_range * 2.618,
        ]
    return sl, tps


def _calc_sl_tp(
    entry: float,
    direction: str,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    cfg: "StyleConfig",
) -> tuple[float, float, float, str, str]:
    """
    Calculate SL and TP using TA hierarchy:

    SL Priority:
      1. Below nearest support zone (LONG) / above resistance (SHORT)
         + buffer = 0.3% below the zone
      2. Below recent swing low (structural SL)
      3. Fibonacci 0.618 retracement of last swing
      4. Fallback: ATR × style multiplier

    TP Priority:
      1. Next resistance zone (LONG) / support zone (SHORT) — if R:R ≥ 1:2
      2. Fibonacci 1.618 extension — if R:R ≥ 1:2
      3. Fallback: ATR × style multiplier

    Returns (sl, tp, rr_ratio, sl_method, tp_method)
    """
    atr = _atr(highs, lows, closes)
    lb = min(cfg.lookback + 10, len(closes))
    supports, resistances = _find_sr_zones(highs, lows, closes, lookback=lb)

    # ── Stop Loss ──────────────────────────────────────────────────────────────
    sl = None
    sl_method = ""

    if direction == "LONG":
        # 1. Nearest support zone below entry
        candidates = [z for z in supports if z < entry]
        if candidates:
            nearest_sup = max(candidates)  # highest support below entry
            sl = nearest_sup * (1 - 0.003)  # 0.3% below support
            sl_method = f"S/R Zone ${nearest_sup:.4g} −0.3%"

        # 2. Structural swing low
        if sl is None or (entry - sl) / entry > 0.08:  # if SL too far, use swing low
            lb_lows = lows[-lb:]
            swing_low = min(lb_lows)
            structural_sl = swing_low * 0.997
            if sl is None or structural_sl > sl:  # tighter is better
                sl = structural_sl
                sl_method = f"Swing Low ${swing_low:.4g} −0.3%"

    else:  # SHORT
        candidates = [z for z in resistances if z > entry]
        if candidates:
            nearest_res = min(candidates)
            sl = nearest_res * 1.003
            sl_method = f"S/R Zone ${nearest_res:.4g} +0.3%"

        if sl is None or (sl - entry) / entry > 0.08:
            lb_highs = highs[-lb:]
            swing_high = max(lb_highs)
            structural_sl = swing_high * 1.003
            if sl is None or structural_sl < sl:
                sl = structural_sl
                sl_method = f"Swing High ${swing_high:.4g} +0.3%"

    # 3. Fibonacci 0.618 retracement fallback
    if sl is None:
        recent_swing_high = max(highs[-lb:])
        recent_swing_low  = min(lows[-lb:])
        swing_range = recent_swing_high - recent_swing_low
        if direction == "LONG":
            fib_sl = entry - swing_range * 0.618
            sl = fib_sl
            sl_method = f"Fib 0.618 retracement"
        else:
            fib_sl = entry + swing_range * 0.618
            sl = fib_sl
            sl_method = f"Fib 0.618 retracement"

    # 4. ATR fallback (if SL unreasonably far)
    atr_sl = entry - atr * cfg.atr_sl_mult if direction == "LONG" else entry + atr * cfg.atr_sl_mult
    if sl is None:
        sl = atr_sl
        sl_method = f"ATR×{cfg.atr_sl_mult}"
    else:
        dist_pct = abs(entry - sl) / entry
        if dist_pct > 0.08:
            sl = atr_sl
            sl_method = f"ATR×{cfg.atr_sl_mult} (capped 8%)"

    # ── Enforce minimum SL distance per style ─────────────────────────────────
    # Prevents SL being too tight (stop-hunt zone)
    min_dist = entry * cfg.min_sl_pct
    current_dist = abs(entry - sl)
    if current_dist < min_dist:
        if direction == "LONG":
            sl = entry - min_dist
        else:
            sl = entry + min_dist
        sl_method = f"{sl_method} (min {cfg.min_sl_pct*100:.1f}% enforced)"

    # ── Take Profit ────────────────────────────────────────────────────────────
    risk = abs(entry - sl)
    tp = None
    tp_method = ""

    if direction == "LONG":
        # 1. Next resistance zone with R:R ≥ 1:2
        tp_candidates = [z for z in resistances if z > entry]
        for res_zone in tp_candidates[:3]:
            if (res_zone - entry) / risk >= 2.0:
                tp = res_zone
                tp_method = f"Resistance zone ${res_zone:.4g}"
                break

        # 2. Fibonacci 1.618 extension
        if tp is None:
            recent_swing_low = min(lows[-lb:])
            fib_tp = entry + (entry - recent_swing_low) * 1.618
            if (fib_tp - entry) / risk >= 2.0:
                tp = fib_tp
                tp_method = "Fib 1.618 extension"

    else:  # SHORT
        tp_candidates = [z for z in supports if z < entry]
        for sup_zone in reversed(tp_candidates[-3:]):
            if (entry - sup_zone) / risk >= 2.0:
                tp = sup_zone
                tp_method = f"Support zone ${sup_zone:.4g}"
                break

        if tp is None:
            recent_swing_high = max(highs[-lb:])
            fib_tp = entry - (recent_swing_high - entry) * 1.618
            if (entry - fib_tp) / risk >= 2.0:
                tp = fib_tp
                tp_method = "Fib 1.618 extension"

    # 3. ATR fallback for TP
    if tp is None:
        tp = entry + atr * cfg.atr_tp_mult if direction == "LONG" else entry - atr * cfg.atr_tp_mult
        tp_method = f"ATR×{cfg.atr_tp_mult}"

    reward = abs(tp - entry)
    rr_float = reward / risk if risk > 0 else 0
    rr = f"1:{rr_float:.1f}"

    return sl, tp, rr_float, sl_method, tp_method


# ── Core scoring ──────────────────────────────────────────────────────────────

def _analyze(
    symbol: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    change_24h: float,
    cfg: StyleConfig,
    style: str,
) -> ScanSignal | None:
    if len(closes) < max(cfg.bb_period, cfg.rsi_period) + 10:
        return None

    price = closes[-1]
    signals: list[str] = []
    score = 0.0
    alert_type = "accumulation"
    direction = "LONG"

    # ── 1. Bollinger Band Squeeze ──────────────────────────────────────────────
    bb_closes = closes[-cfg.bb_period:]
    bb_mid = sum(bb_closes) / cfg.bb_period
    bb_std = _stddev(bb_closes)
    bb_width = (bb_std * 4) / bb_mid if bb_mid > 0 else 1.0

    if bb_width < cfg.squeeze_threshold:
        pts = 25 * cfg.w_squeeze
        score += pts
        signals.append(f"🔵 BB Squeeze {bb_width*100:.1f}% — coiling")
        alert_type = "squeeze"
    elif bb_width < cfg.squeeze_threshold * 1.5:
        score += 12 * cfg.w_squeeze
        signals.append(f"BB tightening {bb_width*100:.1f}%")

    # ── 2. Volume Accumulation ─────────────────────────────────────────────────
    avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else volumes[-1]
    last_vol = volumes[-1]
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0

    vol5 = volumes[-5:]
    vol_slope = (vol5[-1] - vol5[0]) / (vol5[0] + 1e-10)
    price_slope = (closes[-1] - closes[-5]) / (closes[-5] + 1e-10)

    if vol_slope > cfg.vol_slope_min and abs(price_slope) < 0.04:
        pts = 22 * cfg.w_accumulation
        score += pts
        signals.append(f"📦 Akumulasi: vol +{vol_slope*100:.0f}% harga flat")
        alert_type = "accumulation"
    elif vol_slope > cfg.vol_slope_min * 0.6 and price_slope < 0:
        score += 18 * cfg.w_accumulation
        signals.append("💪 Vol naik saat harga turun (hidden strength)")
    elif vol_ratio > 1.5 and abs(price_slope) < 0.03:
        score += 10 * cfg.w_accumulation
        signals.append(f"Vol {vol_ratio:.1f}x avg, harga masih flat")

    # ── 3. Near Breakout Zone ──────────────────────────────────────────────────
    lb = min(cfg.lookback, len(highs))
    recent_high = max(highs[-lb:])
    recent_low  = min(lows[-lb:])

    dist_high = (recent_high - price) / price
    dist_low  = (price - recent_low) / price

    breakout_pct = 0.015 if style == "scalping" else (0.02 if style == "daytrading" else 0.025)
    if 0 < dist_high < breakout_pct:
        score += 20 * cfg.w_breakout
        signals.append(f"🎯 Near breakout ${recent_high:.6g}")
        alert_type = "breakout"
        direction = "LONG"
    elif 0 < dist_low < breakout_pct:
        score += 15 * cfg.w_breakout
        signals.append(f"🎯 Near support ${recent_low:.6g} — reversal")
        alert_type = "reversal"

    # ── 4. RSI (period depends on style) ──────────────────────────────────────
    rsi = _rsi(closes, cfg.rsi_period)
    if rsi < 30:
        score += 15 * cfg.w_rsi
        signals.append(f"RSI({cfg.rsi_period}) {rsi:.0f} — oversold reversal")
        direction = "LONG"
        alert_type = "reversal"
    elif 30 <= rsi <= 50:
        score += 12 * cfg.w_rsi
        signals.append(f"RSI({cfg.rsi_period}) {rsi:.0f} — energy building")
        direction = "LONG"
    elif 50 <= rsi <= 65:
        score += 8 * cfg.w_rsi
        signals.append(f"RSI({cfg.rsi_period}) {rsi:.0f} — momentum building")
    elif rsi > 75:
        score -= 10 * cfg.w_rsi
        # Overbought = potential short
        if style in ("scalping", "daytrading"):
            signals.append(f"RSI({cfg.rsi_period}) {rsi:.0f} — overbought SHORT")
            direction = "SHORT"
            score += 8 * cfg.w_rsi

    # ── 5. EMA Compression ────────────────────────────────────────────────────
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else ema21
    spread = abs(ema9 - ema21) / price if price > 0 else 1.0

    compress_thresh = 0.003 if style == "scalping" else (0.005 if style == "daytrading" else 0.008)
    if spread < compress_thresh:
        score += 15 * cfg.w_ema
        signals.append(f"⚡ EMA 9/21 terkompresi ({spread*100:.2f}%)")
        alert_type = "squeeze"
    elif ema9 > ema21 > ema50:
        score += 8 * cfg.w_ema
        signals.append("EMA 9>21>50 bullish")
        direction = "LONG"
    elif ema9 < ema21 < ema50:
        score += 8 * cfg.w_ema
        signals.append("EMA 9<21<50 bearish")
        direction = "SHORT"

    # ── 6. Buy/Sell pressure shift ────────────────────────────────────────────
    def _bp(o_l, c_l, v_l):
        bull = sum(v for o, c, v in zip(o_l, c_l, v_l) if c >= o)
        return bull / (sum(v_l) or 1)

    n = min(5, len(opens) // 2)
    if len(opens) >= n * 2:
        bp_now  = _bp(opens[-n:], closes[-n:], volumes[-n:])
        bp_prev = _bp(opens[-n*2:-n], closes[-n*2:-n], volumes[-n*2:-n])
        shift = bp_now - bp_prev
        if shift > 0.15:
            score += 15 * cfg.w_pressure
            signals.append(f"🟢 Buy pressure +{shift*100:.0f}% ({bp_now*100:.0f}% bullish)")
            direction = "LONG"
        elif shift < -0.15:
            score += 12 * cfg.w_pressure
            signals.append(f"🔴 Sell pressure +{abs(shift)*100:.0f}%")
            direction = "SHORT"

    # ── 7. Candle body shrinking ───────────────────────────────────────────────
    if style in ("scalping", "daytrading", "swing"):
        bodies = [abs(c - o) for o, c in zip(opens[-7:], closes[-7:])]
        if len(bodies) >= 4 and bodies[0] > 0:
            body_slope = (bodies[-1] - bodies[0]) / bodies[0]
            if body_slope < -0.5:
                score += 10 * cfg.w_candle
                signals.append("Candle bodies mengecil (kompresi)")

    # ── Penalty: already pumped/dumped ────────────────────────────────────────
    if abs(change_24h) > cfg.pump_penalty_pct * 2:
        score -= 20
        signals.append(f"⚠️ Sudah bergerak {change_24h:+.1f}% (entry terlambat)")
    elif abs(change_24h) > cfg.pump_penalty_pct:
        score -= 8

    # ── Filter ────────────────────────────────────────────────────────────────
    if score < cfg.min_score or len([s for s in signals if not s.startswith("⚠️")]) < 2:
        return None

    # ── Direction from majority signals ───────────────────────────────────────
    long_hints  = sum(1 for s in signals if any(k in s for k in ["bullish", "oversold", "Buy", "Akumulasi", "hidden", "breakout", "LONG", "🟢", "flat"]))
    short_hints = sum(1 for s in signals if any(k in s for k in ["bearish", "overbought", "Sell", "🔴", "SHORT"]))
    if short_hints > long_hints:
        direction = "SHORT"

    # ── Zone-based entry (support for LONG, resistance for SHORT) ─────────────
    lb = min(cfg.lookback + 10, len(closes))
    supports, resistances = _find_sr_zones(highs, lows, closes, lookback=lb)

    entry_price    = price
    entry_zone_low: float | None  = None
    entry_zone_high: float | None = None
    entry_type     = "market"
    entry_note     = ""

    if direction == "LONG" and supports:
        zone_mid = max(z for z in supports if z < price)  # strongest support below price
        dist = (price - zone_mid) / zone_mid
        # Estimate zone width (±1% of zone mid as approximation)
        entry_zone_low  = zone_mid * 0.99
        entry_zone_high = zone_mid * 1.01

        if dist <= 0.015:
            entry_price = price
            entry_type  = "at_zone"
            entry_note  = f"Harga sudah di area support ${zone_mid:.4g} — entry sekarang valid"
        elif dist <= 0.06:
            entry_price = zone_mid
            entry_type  = "wait_pullback"
            entry_note  = f"Tunggu pullback ke support ${zone_mid:.4g} (harga sekarang {dist*100:.1f}% di atas) — pasang limit buy"
        else:
            entry_price = zone_mid
            entry_type  = "wait_pullback"
            entry_note  = f"Harga terlalu jauh dari support ${zone_mid:.4g} ({dist*100:.1f}%) — tunggu pullback signifikan"

    elif direction == "SHORT" and resistances:
        zone_mid = min(z for z in resistances if z > price)  # strongest resistance above price
        dist = (zone_mid - price) / zone_mid
        entry_zone_low  = zone_mid * 0.99
        entry_zone_high = zone_mid * 1.01

        if dist <= 0.015:
            entry_price = price
            entry_type  = "at_zone"
            entry_note  = f"Harga sudah di area resistance ${zone_mid:.4g} — entry SHORT sekarang valid"
        elif dist <= 0.06:
            entry_price = zone_mid
            entry_type  = "wait_rally"
            entry_note  = f"Tunggu rally ke resistance ${zone_mid:.4g} (harga sekarang {dist*100:.1f}% di bawah) — pasang limit sell"
        else:
            entry_price = zone_mid
            entry_type  = "wait_rally"
            entry_note  = f"Harga terlalu jauh dari resistance ${zone_mid:.4g} ({dist*100:.1f}%) — tunggu rally"
    else:
        entry_note = "Tidak ada S/R zone yang jelas — entry di market price"

    # ── SL / TP dihitung dari entry zone, bukan current price ─────────────────
    sl, tp, rr_float, sl_method, tp_method = _calc_sl_tp(
        entry_price, direction, highs, lows, closes, cfg
    )

    # Filter: R:R must meet per-style minimum
    if rr_float < cfg.min_rr:
        return None

    rr = f"1:{rr_float:.1f}"
    key_level = recent_high if direction == "LONG" else recent_low

    info = STYLE_LABELS[style]
    style_note = f"{info['label']} | {info['tf']} | {entry_type}"

    return ScanSignal(
        symbol=symbol,
        direction=direction,
        probability=round(min(score, 99), 1),
        current_price=round(price, 8),
        entry=round(entry_price, 8),
        entry_zone_low=round(entry_zone_low, 8) if entry_zone_low else None,
        entry_zone_high=round(entry_zone_high, 8) if entry_zone_high else None,
        entry_type=entry_type,
        entry_note=entry_note,
        change_24h=round(change_24h, 2),
        volume_ratio=round(vol_ratio, 2),
        signals=[s for s in signals if not s.startswith("⚠️")][:4],
        key_level=round(key_level, 8),
        stop_loss=round(sl, 8),
        take_profit=round(tp, 8),
        risk_reward=rr,
        alert_type=alert_type,
        sl_method=sl_method,
        tp_method=tp_method,
        style_note=style_note,
    )


# ── Fetch ─────────────────────────────────────────────────────────────────────

async def _klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list:
    try:
        r = await client.get(fapi(f"/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"))
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list) and d:
                return d
    except Exception:
        pass
    return []


# ── Core scan logic (called by scheduler — single source of truth) ─────────────

async def scan_market_core(style: str) -> ScannerResponse:
    """
    Run a full Binance scan for the given style. Pure computation — no DB writes.
    Called exclusively by the scheduler. Results are cached in scan_store.
    """
    cfg  = STYLE_CONFIGS[style]
    info = STYLE_LABELS[style]
    now  = int(time.time())

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(fapi("/fapi/v1/ticker/24hr"))
        if r.status_code != 200:
            return ScannerResponse(results=[], scanned=0, style=style,
                                   style_label=info["label"], timeframe=info["tf"], generated_at=now)
        tickers = [t for t in r.json() if str(t.get("symbol", "")).endswith("USDT")]

    tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    candidates = tickers[:100]

    async with httpx.AsyncClient(timeout=25) as client:
        kline_results = await asyncio.gather(
            *[_klines(client, t["symbol"], cfg.timeframe, cfg.candle_limit) for t in candidates],
            return_exceptions=True,
        )

    results: list[ScanSignal] = []
    for ticker, kdata in zip(candidates, kline_results):
        if isinstance(kdata, Exception) or not kdata:
            continue
        try:
            opens  = [float(k[1]) for k in kdata]
            highs  = [float(k[2]) for k in kdata]
            lows   = [float(k[3]) for k in kdata]
            closes = [float(k[4]) for k in kdata]
            vols   = [float(k[5]) for k in kdata]
            change = float(ticker.get("priceChangePercent", 0))
            sig    = _analyze(ticker["symbol"], opens, highs, lows, closes, vols, change, cfg, style)
            if sig:
                results.append(sig)
        except Exception:
            continue

    results.sort(key=lambda r: r.probability, reverse=True)
    results = results[:25]

    response = ScannerResponse(
        results=results,
        scanned=len(candidates),
        style=style,
        style_label=info["label"],
        timeframe=info["tf"],
        generated_at=now,
    )
    logger.info("scanner_done", style=style, tf=cfg.timeframe, found=len(results))
    return response


# ── API Endpoint (read-only — serves scheduler cache) ─────────────────────────

@router.get("/scanner/scan", response_model=ScannerResponse)
async def scan_market(
    style: str = Query(default="swing", description="scalping | daytrading | swing | position"),
) -> ScannerResponse:
    """
    Return scanner results. Serves the scheduler's cached results when available.
    Falls back to a live scan (read-only, no DB logging) if cache is empty.
    """
    from app.services.scheduler import scan_store

    style = style.lower()
    if style not in STYLE_CONFIGS:
        style = "swing"

    # ── 1. Serve scheduler cache (preferred) ──────────────────────────────────
    cached = scan_store.get_result(style)
    if cached is not None:
        return cached

    # ── 2. Fallback: live scan if scheduler hasn't run yet ────────────────────
    #    (first few minutes after startup, before first scheduler cycle)
    now       = int(time.time())
    cache_key = style
    if cache_key in _cache and now - _cache[cache_key].get("ts", 0) < CACHE_TTL:
        return _cache[cache_key]["data"]

    response = await scan_market_core(style)
    _cache[cache_key] = {"data": response, "ts": now}
    return response
