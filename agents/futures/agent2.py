"""
Agent 2 — Accumulation Detector.

Goal: Find coins in the ACCUMULATION phase — the Wyckoff stage just before markup.
      Use T0-T4 pipeline but tuned for "about to move" rather than "already moving".

Philosophy:
  T0-T4 pipeline finds the SETUP from price/volume structure.
  On-chain data (OI, Funding) CONFIRMS the accumulation is real.
  A clean Wyckoff accumulation + compressed volatility + rising OI + neutral funding
  = the highest-probability pre-pump signal in futures markets.

Key difference from old Agent 2:
  OLD: scored confirmed setups (could already be mid-move)
  NEW: penalizes "already moved" coins, rewards compression & quiet accumulation

Pipeline (0-100 pts):
  T0  Wyckoff Accumulation    0-20 pts  smart money activity before markup
      └─ OI Confirmation      0-8  pts  OI rising during accumulation = institutions
  T1  Trend setup             0-15 pts  flat / recovering trend preferred (pre-move)
      └─ Funding Alignment    0-8  pts  neutral/negative = fuel not yet used
  T2  S/R Breakout Zone       0-14 pts  entry just below resistance (pre-breakout)
      └─ Volume at Zone       0-4  pts  volume active at S/R = level is real
  T3  Compression Signals     0-18 pts  BB Squeeze primary, vol accumulation, coil
  T4  Early Trigger           0-13 pts  RSI 40-55 sweet spot + buying pressure

Direction: LONG primary (accumulation precedes markup, not markdown).
           SHORT only when strong distribution phase detected (bonus mode).
Min score: 52  |  Min R:R: 1:3  |  Leverage: dynamic (ATR-based)

Penalties:
  24h change > 12%    -20 pts  (already in markup — late entry)
  24h change > 7%     -10 pts  (partially missed — higher risk)
  24h change < -15%   -8  pts  (panic selling — wrong direction for LONG)
"""

import math
from typing import Optional

import structlog

from .data import FuturesData
from .agent1 import (
    _ema, _rsi, _atr, _swing_lows, _swing_highs,
    _round_price, calc_leverage,
    _bb_squeeze, _bb_squeeze_persistence, _volume_accumulation, _candle_coil,
    _volume_zscore,
)

logger = structlog.get_logger(__name__)

MIN_RR     = 3.0
AGENT_NAME = "futures_agent2"


# ── T0: Wyckoff Phase ─────────────────────────────────────────────────────────

def _wyckoff_phase(closes: list[float], volumes: list[float]) -> tuple[str, float]:
    """
    Detect Wyckoff phase from price + volume structure.
    Returns (phase, vol_expansion_ratio).

    accumulation: price flat/slight decline + volume expanding = smart money buying
    markup:       price rising + volume expanding = trend in progress (partially late)
    distribution: price flat/slight rise at top + volume expanding = smart money selling
    markdown:     price falling + volume expanding = trend down
    neutral:      no clear signal
    """
    if len(closes) < 30 or len(volumes) < 30:
        return "neutral", 1.0

    mid           = len(closes) // 2
    recent_closes = closes[mid:]
    prior_closes  = closes[:mid]
    recent_vols   = volumes[mid:]
    prior_vols    = volumes[:mid]

    price_change   = (recent_closes[-1] - prior_closes[0]) / max(abs(prior_closes[0]), 1e-10)
    avg_vol_recent = sum(recent_vols) / len(recent_vols)
    avg_vol_prior  = sum(prior_vols)  / len(prior_vols)
    vol_expansion  = avg_vol_recent / avg_vol_prior if avg_vol_prior > 0 else 1.0

    recent_range = (max(recent_closes) - min(recent_closes)) / max(abs(recent_closes[0]), 1e-10)
    prior_range  = (max(prior_closes)  - min(prior_closes))  / max(abs(prior_closes[0]),  1e-10)
    is_compressed = recent_range < prior_range * 0.65

    # Accumulation: compressed range + rising volume + flat/slight down price
    if is_compressed and vol_expansion > 1.2 and abs(price_change) < 0.04:
        return "accumulation", vol_expansion

    # Markup: price rising meaningfully + volume confirms
    if price_change > 0.03 and vol_expansion > 1.0 and not is_compressed:
        return "markup", vol_expansion

    # Distribution: compressed at top + volume + flat/slight up price
    if is_compressed and vol_expansion > 1.1 and 0 <= price_change < 0.04:
        return "distribution", vol_expansion

    # Markdown: price falling + volume confirms
    if price_change < -0.03 and vol_expansion > 1.0:
        return "markdown", vol_expansion

    return "neutral", vol_expansion


# ── T1: Trend setup ───────────────────────────────────────────────────────────

def _trend_setup(closes: list[float]) -> str:
    """
    Detect trend setup optimized for pre-move detection.
    Returns: 'recovering' | 'flat' | 'up' | 'down' | 'unknown'
    Pre-move ideal: 'recovering' or 'flat' (before markup begins)
    Already moving: 'up' (markup may be partial or done)
    """
    if len(closes) < 50:
        return "unknown"
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, 50)

    if ema9 > ema21 > ema50:
        return "up"
    if ema9 < ema21 < ema50:
        return "down"
    # EMA9 crossed above EMA21 but not above EMA50 yet = early recovery
    if ema9 > ema21 and ema21 < ema50:
        return "recovering"
    return "flat"


# ── T4: Trigger helpers ───────────────────────────────────────────────────────

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


def _rsi_sweet_spot(rsi: float) -> tuple[int, str]:
    """Score RSI position for pre-move entry."""
    if 43 <= rsi <= 55:
        return 13, "sweet"       # ideal pre-pump zone
    if 35 <= rsi < 43:
        return 8, "recovering"   # recovering from dip
    if 55 < rsi <= 63:
        return 5, "building"     # building momentum
    if rsi < 35:
        return 3, "oversold"     # very oversold, could bounce but also could dump more
    return 0, "outside"          # overbought or unclear


# ── Main scorer ───────────────────────────────────────────────────────────────

def _score_accumulation(
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """Score a symbol for accumulation-phase LONG setup."""
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref  = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── T0: Wyckoff Phase (0-20 pts) ─────────────────────────────────────────
    # Primary: accumulation phase = coin coiling before markup
    phase, vol_exp = _wyckoff_phase(ref.closes, ref.volumes)

    if phase == "accumulation":
        score += 20
        signals.append(f"📦 Wyckoff Accumulation — vol {vol_exp:.1f}× saat harga flat (pre-markup)")
    elif phase == "markup":
        # Markup already started — still tradable but partially missed
        score += 8
        signals.append(f"📈 Wyckoff Markup awal — masih bisa entry jika baru mulai")
    elif phase in ("distribution", "markdown"):
        # Wrong direction for LONG pre-gainer
        score -= 10

    # D3.6 (PLAN_v3): Wyckoff multi-TF confidence — require BOTH 4h and 1h to agree.
    # Single-TF Wyckoff can be noisy; dual confirmation = much stronger signal.
    if d4h and d1h and len(d4h.closes) >= 30 and len(d1h.closes) >= 30:
        phase4h, _ = _wyckoff_phase(d4h.closes, d4h.volumes)
        phase1h, _ = _wyckoff_phase(d1h.closes, d1h.volumes)
        if phase4h == "accumulation" and phase1h == "accumulation":
            score += 8
            signals.append("🔵 Wyckoff Accumulation 4H+1H konfirmasi — dual-TF pre-markup conviction")
        elif phase4h == "accumulation" and phase1h in ("markup", "neutral"):
            score += 3   # 4h accumulation starting to mark up on 1h
        elif phase4h == phase1h == "markup" and phase == "accumulation":
            pass   # already gave markup pts above, avoid double-counting

    # ── T0 on-chain: OI Confirmation (0-8 pts) + Acceleration (0-6 pts) ────────
    # OI rising during accumulation = institutions entering quietly
    oi_chg      = ref.oi_change_pct
    oi_chg_prev = ref.oi_change_pct_prev

    if phase == "accumulation" and oi_chg > 2.0:
        score += 8
        signals.append(f"📊 OI +{oi_chg:.1f}% selama akumulasi — institusi masuk diam-diam")
    elif phase == "accumulation" and oi_chg > 1.0:
        score += 5
        signals.append(f"OI +{oi_chg:.1f}% — posisi baru terbentuk")
    elif oi_chg > 3.0 and change_24h < 2:
        # OI surging while price barely moves = heavy accumulation
        score += 6
        signals.append(f"📊 OI +{oi_chg:.1f}% tanpa pergerakan harga — akumulasi tersembunyi")
    elif oi_chg < -2.0:
        score -= 4   # OI falling = exit / liquidation risk

    # P1.2: OI acceleration during accumulation = institutional conviction building
    if oi_chg > oi_chg_prev > 0:
        score += 6
        signals.append(f"📈 OI acceleration {oi_chg_prev:.1f}% → {oi_chg:.1f}% — momentum institusional membangun")

    # ── T1: Trend Setup (0-15 pts) ────────────────────────────────────────────
    # Recovering / flat trend = pre-move ideal, uptrend = markup already started
    # F100: evaluate BOTH 4h and 1h — removed unconditional break that skipped 1h
    trend_pts   = 0
    trend_sig   = None
    for tf_key in ["4h", "1h"]:
        d = tf_map.get(tf_key)
        if not d or len(d.closes) < 50:
            continue
        ts = _trend_setup(d.closes)
        if ts == "recovering":
            pts = 15 if tf_key == "4h" else 10
            if pts > trend_pts:
                trend_pts = pts
                trend_sig = f"⚡ Trend recovering {tf_key} — EMA9 baru cross EMA21 ke atas"
        elif ts == "flat":
            pts = 10 if tf_key == "4h" else 7
            if pts > trend_pts:
                trend_pts = pts
                trend_sig = f"Trend sideways {tf_key} — fase akumulasi terkonfirmasi"
        elif ts == "up":
            pts = 6 if tf_key == "4h" else 4
            if pts > trend_pts:
                trend_pts = pts
                trend_sig = None   # uptrend = no explicit signal label

    if trend_sig:
        signals.append(trend_sig)
    score += trend_pts

    # ── T1 on-chain: Funding Alignment (0-8 pts) ─────────────────────────────
    # Neutral/negative funding = market not yet positioned → fuel available
    fr = ref.funding_rate

    if fr < -0.03 / 100:
        score += 8
        signals.append(f"💰 Funding {fr*100:.3f}% sangat negatif — short squeeze fuel siap meledak")
    elif fr < 0:
        score += 5
        signals.append(f"Funding {fr*100:.3f}% negatif — posisi belum crowded LONG")
    elif fr <= 0.02 / 100:
        score += 3   # near-neutral = still usable
    elif fr > 0.06 / 100:
        # Longs already crowded = headwind
        score -= 6

    # ── T2: S/R Breakout Zone (0-14 pts) ─────────────────────────────────────
    # Price near resistance = breakout catalyst within reach
    sr_found = False
    _res_near_price = None
    for tf_key in ["4h", "1h", "15m"]:
        d = tf_map.get(tf_key)
        if not d or not d.lows or not d.highs:
            continue
        s_lows  = _swing_lows(d.lows,  lookback=5)
        s_highs = _swing_highs(d.highs, lookback=5)

        # Near resistance (< 3% away) = about to break out
        near_res = [r for r in s_highs if 0 < (r - price) / price < 0.03]
        if near_res:
            dist = (near_res[0] - price) / price * 100
            score    += 14
            signals.append(f"🎯 {dist:.1f}% ke resistance {tf_key} — breakout trigger zone")
            sr_found = True
            _res_near_price = near_res[0]
            break

        # Also check: price bouncing off support (entry near support = safe LONG)
        near_sup = [s for s in s_lows if 0 < (price - s) / price < 0.02]
        if near_sup and not sr_found:
            score    += 8
            signals.append(f"📍 Bouncing dari support {tf_key} — entry aman dengan SL jelas")
            sr_found = True
            break

    # D3.4 (PLAN_v3): resistance test count bonus — level tested multiple times = proven.
    # Count 1h candles whose high touched within 1% of the resistance level.
    if _res_near_price and d1h and len(d1h.highs) >= 20:
        _test_count = sum(
            1 for h in d1h.highs[-50:]
            if abs(h - _res_near_price) / _res_near_price < 0.01
        )
        if _test_count >= 5:
            score += 4
            signals.append(f"🏋 Resistance diuji {_test_count}× (1h) — level solid, breakout makin dekat")
        elif _test_count >= 3:
            score += 2

    # ── T2 on-chain: Volume at S/R zone (0-4 pts) ────────────────────────────
    if sr_found and ref.volumes:
        avg_vol = sum(ref.volumes[-21:-1]) / 20 if len(ref.volumes) >= 21 else 0
        cur_vol = ref.volumes[-1]
        if avg_vol > 0 and cur_vol > avg_vol * 1.5:
            score   += 4
            signals.append(f"Vol {cur_vol/avg_vol:.1f}× di zona S/R — level sedang diuji aktif")

    # ── T3: Compression Signals (0-18 pts) ───────────────────────────────────
    # BB Squeeze primary, vol accumulation, candle coil
    primary = d1h or d4h or d15
    if primary and primary.closes:
        # D3.1 (PLAN_v3): compute ATR to feed adaptive BB thresholds
        _atr_val = _atr(primary.highs, primary.lows, primary.closes, 14) if (
            primary.highs and primary.lows and len(primary.closes) >= 14) else 0.0
        _atr_pct = _atr_val / primary.closes[-1] * 100 if primary.closes[-1] > 0 else 0.0

        # BB Squeeze (primary compression signal) — D3.1: ATR-adaptive thresholds
        is_sq4h, bw4h, label4h = (
            _bb_squeeze(d4h.closes, atr_pct=_atr_pct) if d4h else (False, 100.0, "none")
        )
        is_sq1h, bw1h, label1h = _bb_squeeze(primary.closes, atr_pct=_atr_pct)

        if label4h == "strong" and label1h in ("strong", "moderate"):
            score += 18
            signals.append(f"🔵 BB Squeeze multi-TF (4H {bw4h:.1f}% / 1H {bw1h:.1f}%) — BREAKOUT IMMINENT")
        elif label4h == "strong":
            score += 12
            signals.append(f"🔵 BB Squeeze 4H ({bw4h:.1f}%) — energi besar terkompresi")
        elif label1h == "strong":
            score += 10
            signals.append(f"🔵 BB Squeeze 1H ({bw1h:.1f}%) — volatilitas sangat rendah")
        elif label1h == "moderate":
            score += 6

        # D3.5 (PLAN_v3): squeeze persistence bonus — longer compression = bigger breakout energy
        if label1h in ("strong", "moderate"):
            _persist = _bb_squeeze_persistence(primary.closes, atr_pct=_atr_pct)
            if _persist >= 8:
                score += 5
                signals.append(f"🔵 Squeeze {_persist} candle beruntun (1H) — energi terkompresi lama")
            elif _persist >= 5:
                score += 3

        # Volume accumulation (smart money buying quietly)
        is_accum, vol_r, accum_label = _volume_accumulation(primary.closes, primary.volumes)
        if accum_label == "strong":
            score += 8
            signals.append(f"📦 Volume akumulasi {vol_r:.1f}× — smart money entry senyap")
        elif accum_label == "moderate":
            score += 4

        # P1.1: Volume Z-Score — current vol vs 200-candle 1h baseline
        if d1h and len(d1h.volumes) >= 10:
            vol_z = _volume_zscore(d1h.volumes)
            if vol_z >= 2.5:
                score += 10
                signals.append(f"🚀 Volume spike +{vol_z:.1f}σ vs baseline 200 candle — surge institusional")
            elif vol_z >= 1.5:
                score += 5
                signals.append(f"Volume +{vol_z:.1f}σ di atas baseline 1h — akumulasi di atas normal")

        # Candle coil (energy compressing in bodies)
        if primary.opens and _candle_coil(primary.opens, primary.closes):
            score += 3

    # ── T4: Early Trigger (0-13 pts) ─────────────────────────────────────────
    # RSI sweet spot 40-55 = momentum turning, not yet overbought
    trigger = d1h or d15 or d4h
    if trigger and trigger.closes:
        rsi = _rsi(trigger.closes, 14)
        rsi_pts, rsi_zone = _rsi_sweet_spot(rsi)
        score += rsi_pts
        if rsi_zone == "sweet":
            signals.append(f"RSI {rsi:.0f} sweet spot (40-55) — momentum turning, entry ideal")
        elif rsi_zone == "recovering":
            signals.append(f"RSI {rsi:.0f} recovering — bounce dari oversold")

        # Buying pressure shift (buyers becoming more aggressive)
        if trigger.opens:
            pressure = _pressure_shift(trigger.opens, trigger.closes, trigger.volumes)
            if pressure > 0.20:
                score += 8
                signals.append(f"🟢 Buy pressure +{pressure*100:.0f}% — buyer mengambil alih pasar")
            elif pressure > 0.12:
                score += 4
                signals.append(f"Buy pressure shift {pressure*100:.0f}% — buyer mulai dominan")
            elif pressure < -0.20:
                # Strong selling pressure = bad for LONG
                score -= 5

    # ── Liquidation proxy (BUG-L14: directional only, not real USDT) ──────────
    if ref.liq_short_usdt > 100_000:
        score += 2
        signals.append("Short squeeze terdeteksi (proxy arah) — bias bullish")
    elif ref.liq_long_usdt > 300_000:
        # Long liquidation spike = capitulation = potential reversal bottom
        score += 1

    # ── Penalties: already big mover ─────────────────────────────────────────
    # If the coin already moved big, we're late — this is NOT pre-gainer anymore
    if change_24h > 12:
        score -= 20   # already in markup — dangerous late entry
    elif change_24h > 7:
        score -= 10   # partially missed
    elif change_24h < -15:
        score -= 8    # dumping = wrong direction for LONG pre-gainer

    return score, signals[:5]


# ── SHORT detection (secondary mode — only for strong distribution) ───────────

def _score_distribution(
    tf_map:     dict[str, FuturesData],
    price:      float,
    change_24h: float,
) -> tuple[float, list[str]]:
    """
    Detect pre-dump SHORT setup via Wyckoff distribution phase + on-chain confirmation.

    Scoring (max ~90 pts):
      Wyckoff distribution/markdown   0-20 pts  primary — smart money selling at top
      BB Squeeze at resistance        0-15 pts  compression at top = dump loading
      Funding HIGH                    0-12 pts  longs overcrowded = forced unwind
      Near resistance / at top        0-12 pts  rejection zone
      OI rising at top (long trap)    0-10 pts  forced unwind when support breaks
      RSI 55-80 fading zone           0-10 pts  momentum stalling
      Long liquidation pressure       0-8  pts  bearish cascade fuel
      Sell pressure shift             0-5  pts  sellers taking over
    """
    score   = 0.0
    signals: list[str] = []

    d1h = tf_map.get("1h")
    d4h = tf_map.get("4h")
    d15 = tf_map.get("15m")
    ref  = d1h or d4h or d15
    if not ref:
        return 0.0, []

    # ── T0: Wyckoff phase (0-20 pts) ─────────────────────────────────────────
    phase, vol_exp = _wyckoff_phase(ref.closes, ref.volumes)
    if phase == "distribution":
        score += 20
        signals.append(f"📤 Wyckoff Distribution — vol {vol_exp:.1f}× saat harga flat di puncak")
    elif phase == "markdown":
        score += 13
        signals.append(f"📉 Wyckoff Markdown — trend turun vol {vol_exp:.1f}× terkonfirmasi")
    else:
        # F5: no Wyckoff distribution/markdown = weak setup — heavy penalty to filter out
        # Other signals (BB+funding+resistance) can still build score but need much higher bar
        score -= 15

    # ── BB Squeeze at resistance (0-15 pts) ───────────────────────────────────
    # Compression at TOP = dump loading (mirror of accumulation at bottom)
    primary = d1h or d4h or d15
    if primary and primary.closes:
        # D3.1: ATR-adaptive thresholds (same as _score_accumulation T3)
        _atr_v_dist = _atr(primary.highs, primary.lows, primary.closes, 14) if (
            primary.highs and primary.lows and len(primary.closes) >= 14) else 0.0
        _atr_pct_dist = _atr_v_dist / primary.closes[-1] * 100 if primary.closes[-1] > 0 else 0.0
        is_sq1h, bw1h, label1h = _bb_squeeze(primary.closes, atr_pct=_atr_pct_dist)
        is_sq4h, bw4h, label4h = _bb_squeeze(d4h.closes, atr_pct=_atr_pct_dist) if d4h else (False, 100.0, "none")

        if label4h in ("strong", "moderate") and label1h in ("strong", "moderate"):
            score += 15
            signals.append(f"🔴 BB Squeeze multi-TF di area puncak — dump semakin dekat")
        elif label4h == "strong":
            score += 10
            signals.append(f"🔴 BB Squeeze 4H ({bw4h:.1f}%) — energi besar di zona puncak")
        elif label1h == "strong":
            score += 8
            signals.append(f"🔴 BB Squeeze 1H ({bw1h:.1f}%) — volatilitas sangat rendah di atas")
        elif label1h == "moderate":
            score += 4

    # ── Funding rate HIGH (0-12 pts) ──────────────────────────────────────────
    fr = ref.funding_rate
    if fr > 0.08 / 100:
        score += 12
        signals.append(f"💰 Funding +{fr*100:.3f}% ekstrem — longs overcrowded, long squeeze fuel")
    elif fr > 0.05 / 100:
        score += 8
        signals.append(f"Funding +{fr*100:.3f}% tinggi — longs bayar mahal, potensi exit massal")
    elif fr > 0.02 / 100:
        score += 4
    elif fr < -0.02 / 100:
        # Negative funding = shorts overpaying = headwind for SHORT
        score -= 6

    # ── Near resistance / at price high (0-12 pts) ────────────────────────────
    sr_found = False
    for tf_key in ["4h", "1h"]:
        d = tf_map.get(tf_key)
        if not d or not d.highs:
            continue
        s_highs = _swing_highs(d.highs, lookback=5)
        # At or just below resistance = ideal SHORT entry
        at_res = [r for r in s_highs if abs(price - r) / price < 0.025 and r >= price * 0.98]
        if at_res:
            dist_pct = abs(at_res[0] - price) / price * 100
            score    += 12
            signals.append(f"🎯 Di zona resistance {tf_key} ({dist_pct:.1f}% dari level) — SHORT trigger")
            sr_found = True
            break

    if not sr_found and primary:
        # Check if price near recent highs (even without formal S/R)
        recent_high = max(primary.highs[-30:]) if len(primary.highs) >= 30 else max(primary.highs)
        if price >= recent_high * 0.97:
            score += 6
            signals.append("Price dekat recent high — zona distribusi aktif")

    # ── OI rising at top = long trap (0-10 pts) ───────────────────────────────
    oi_chg = ref.oi_change_pct
    if oi_chg > 2.0 and change_24h > 2:
        score += 10
        signals.append(f"📊 OI +{oi_chg:.1f}% saat harga naik — long trap terbentuk, forced unwind imminent")
    elif oi_chg > 1.0 and change_24h > 0:
        score += 6
        signals.append(f"OI +{oi_chg:.1f}% — posisi long baru di puncak, berisiko")
    elif oi_chg < -2.0:
        score -= 4   # OI falling = longs already exiting

    # ── RSI fading zone 55-80 (0-10 pts) ─────────────────────────────────────
    if primary and primary.closes:
        rsi = _rsi(primary.closes, 14)
        if 58 <= rsi <= 72:
            score += 10
            signals.append(f"RSI {rsi:.0f} fading zone — momentum stalling, ideal SHORT entry")
        elif rsi > 72:
            score += 6
            signals.append(f"RSI {rsi:.0f} overbought — extended, koreksi tajam rawan terjadi")
        elif rsi < 40:
            score -= 8   # oversold = wrong direction for SHORT

    # ── Long liquidation pressure (BUG-L14: directional proxy, not real USDT) ──
    if ref.liq_long_usdt > 300_000:
        score += 3
        signals.append("💥 Long liquidation terdeteksi (proxy arah) — bearish cascade")
    elif ref.liq_long_usdt > 100_000:
        score += 2
        signals.append("Long liq pressure (proxy arah) — momentum bearish")

    # ── Sell pressure shift (0-5 pts) ─────────────────────────────────────────
    if primary and primary.opens and primary.closes and primary.volumes:
        pressure = _pressure_shift(primary.opens, primary.closes, primary.volumes)
        if pressure < -0.20:
            score += 5
            signals.append(f"🔴 Sell pressure {pressure*100:.0f}% — seller mengambil alih")
        elif pressure < -0.10:
            score += 3

    # ── Penalties ─────────────────────────────────────────────────────────────
    # Already dumped too much = short covered, don't chase
    if change_24h < -12:
        score -= 20
    elif change_24h < -6:
        score -= 10

    # Strong uptrend = don't fight the trend without very high conviction
    if change_24h > 20:
        score -= 15
    elif change_24h > 10:
        score -= 8

    return score, signals[:5]


# ── Trade levels ──────────────────────────────────────────────────────────────

def _calc_levels(direction: str, tf_map: dict[str, FuturesData], price: float) -> Optional[dict]:
    """Trade level calculator — delegates to Agent 1 to avoid duplication (F3)."""
    from .agent1 import _calc_levels as _a1_levels
    return _a1_levels(direction, tf_map, price)


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_symbol(
    symbol:     str,
    tf_map:     dict[str, FuturesData],
    change_24h: float,
) -> list[dict]:
    """
    Evaluate symbol for Agent 2 (Accumulation Detector).
    F52: Returns ALL valid directions where score ≥ MIN_SCORE.
    Primary: LONG on accumulation. Secondary: SHORT on clear distribution.
    Both are returned independently if both qualify.
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
    try:
        regime = detect_coin_regime(tf_map.get("1h") or ref)
    except Exception:
        regime = "neutral"
    # P3.5: regime-conditional weight cache (falls back to "all" for missing keys)
    weight_cache  = weight_updater.get_weight_cache(AGENT_NAME, regime=regime)

    try:
        long_score,  long_sigs  = _score_accumulation(tf_map, price, change_24h)
        short_score, short_sigs = _score_distribution(tf_map, price, change_24h)
    except Exception:
        return []

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
        try:
            score += weight_updater.get_coin_bonus(symbol, direction)  # P4.8: directional
        except Exception:
            pass

        if score < effective_min:   # F69: adaptive threshold
            # P7.1: log rejection
            try:
                _weak2 = sorted(
                    ((weight_updater.normalize_signal_key(s),
                      weight_cache.get(weight_updater.normalize_signal_key(s), 1.0))
                     for s in signals),
                    key=lambda x: x[1]
                )[:3]
                weight_updater.log_rejection(symbol, AGENT_NAME, direction, score, effective_min,
                                             regime=regime, weak_signals=[f"{k}:{w}" for k, w in _weak2])
            except Exception:
                pass
            continue
        levels = _calc_levels(direction, tf_map, price)
        if not levels:
            continue
        atr_pct  = levels.pop("atr_pct")
        # PLAN_v2 P1.3 — accumulation hold-time lebih lama → cap margin loss lebih ketat (15%).
        leverage = calc_leverage(atr_pct, score, levels["risk_pct"], lane="accumulation")
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
            "setup_type":   "accumulation",  # PLAN_v2 — disambiguated from pre_gainer
            "regime":       regime,          # BUG-L13: per-coin regime (for trade.regime/learning)
            **levels,
        })

    # D2.3 (PLAN_v3): when both LONG and SHORT qualify for accumulation/distribution,
    # contradictory setups on the same coin reduce confidence — keep only the higher-scored.
    if len(results) == 2:
        results = [max(results, key=lambda x: x["score"])]

    return results
