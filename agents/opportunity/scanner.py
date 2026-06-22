"""
Opportunity Scanner (SPOT) — cari koin berpotensi kenaikan berkali lipat.

Tujuan:
  Temukan koin yang sedang dalam fase akumulasi SEBELUM breakout besar.
  Fokus pada sinyal yang menunjukkan potensi kenaikan 2x–10x.

Cara kerja (konstanta di bawah adalah sumber kebenaran — jangan tulis angka di docs):
  1. Scan top-100 USDT pairs by quote volume (likuiditas minimum $5M/24h)
  2. Score multi-sinyal; INDIKATOR dihitung dari candle SELESAI saja (§10.1)
  3. raw_score (tanpa cap) ≥ AUTO_OPEN_SCORE + GERBANG ARAH terpenuhi → auto-open
  4. MIN_SCORE ≤ score < AUTO_OPEN_SCORE → rekomendasi manual
  5. Ranking & TOP_N dipotong berdasarkan EV per unit risk (§11.4), bukan score

Gerbang arah (§12.1 — sistem LONG-only WAJIB konfirmasi arah untuk auto-open):
  taker_ratio ≥ 0.55 ATAU EMA9 > EMA21 di 1h. Tanpa itu squeeze hanya 10 pts
  dan auto_open=False (tetap tampil sebagai rekomendasi manual).

Regime gate (§12.5): BTC 24h < −3% atau EMA 4h bearish → semua auto-open OFF.

Sinyal scoring:
  BB Squeeze multi-TF  : 35 pts  (energi terkompresi, ledakan mendekat)
  Volume Accumulation  : 25 pts  (smart money masuk diam-diam)
  Taker Buy Ratio      : 15 pts  (institusi akumulasi — proxy order flow)
  Buy Pressure Surge   : 15 pts  (shift momentum beli)
  Near Breakout Level  : 15 pts  (dekat resistance kritis)
  RSI Zone             : 12 pts  (tidak overbought, ruang naik masih ada)
  EMA Alignment        : 10 pts  (uptrend multi-TF terkonfirmasi)
  Volume Spike         : 10 pts  (volume >5x normal = institutional interest)
  Momentum Healthy     :  8 pts  (sudah bergerak tapi belum late)
"""

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from app.services.binance_urls import spot
from app.services.trading_costs import EXECUTION_COST_PCT

logger = structlog.get_logger(__name__)

TIMEFRAMES        = ["15m", "1h", "4h"]
CANDLE_LIMIT      = 100
TOP_N             = 15     # hanya 15 terbaik — kualitas > kuantitas
MIN_SCORE         = 65     # threshold lebih tinggi = hanya high-conviction
AUTO_OPEN_SCORE   = 85     # auto-open untuk RAW score (pre-weight, tanpa cap)
MIN_QUOTE_VOLUME  = 5_000_000   # §11.7: likuiditas minimum supaya eksekutable

# Momentum fast-track (R4): coin sudah bergerak kuat → threshold lebih rendah
FASTTRACK_24H_PCT   = 8.0   # change_24h ≥ 8% → momentum nyata, tidak perlu score setinggi normal
FASTTRACK_MIN_SCORE = 80    # masih butuh score ≥ 80 + direction gate — bukan open sembarang

# R7: Momentum priority scan — inject high-momentum coins outside top-100 by volume
MOMENTUM_SCAN_MIN_PCT   = 5.0   # change_24h ≥ 5% layak masuk supplement list
MOMENTUM_SCAN_EXTRA     = 20    # max 20 coin tambahan di luar top-100 volume

# R8: Momentum chase scoring — coin sudah bergerak ≥ 10%, pullback sehat, siap second leg
MOMENTUM_CHASE_MIN_24H  = 10.0  # minimal 24h change sebelum dianggap "momentum chase"

# PLAN-SPOT-GAP S4: weekly-momentum universe supplement — koin yang sudah "selesai
# moon" minggu ini lalu sekarang sepi (change_24h kecil) tidak pernah masuk top-100
# volume MAUPUN R7 momentum supplement (yang cuma lihat 24h). Pass terpisah ini
# fetch HANYA klines 4h (murah) untuk pool lebih luas, semata untuk ukur change_7d.
WEEKLY_SCAN_POOL        = 150       # ranking volume 100..250 dicek change_7d-nya
WEEKLY_SCAN_MIN_VOLUME  = 1_000_000 # likuiditas lebih relaks dari MIN_QUOTE_VOLUME
WEEKLY_CHANGE_MIN_PCT   = 20.0      # change_7d minimal untuk masuk supplement
WEEKLY_SCAN_EXTRA       = 15        # max coin tambahan dari jalur ini

# Gerbang arah untuk auto-open (§12.1)
DIRECTION_TAKER_MIN = 0.55

# Regime gate BTC (§12.5)
# Phase 3 G3-regime: 3-state OPEN / REDUCED / CLOSED (was binary).
# CLOSED:  hard stop, no auto-open
# REDUCED: max 1 open per cycle (was 3), system konservatif
# OPEN:    normal full quota
BTC_REGIME_CLOSED_24H  = -5.0    # BTC 24h ≤ −5% → CLOSED
BTC_REGIME_REDUCED_24H = -3.0    # BTC 24h ≤ −3% (and > −5%) → REDUCED
BTC_REGIME_DOUBLE_CONFIRM_24H = -1.0  # 4h EMA bearish + 24h < −1% → REDUCED
BTC_REGIME_24H_MIN  = BTC_REGIME_REDUCED_24H   # legacy alias (kept for back-compat)

# Stablecoin / fiat / low-vol token blacklist
# BB Width secara natural sempit → false squeeze signals
# Updated: tambah fiat pairs, wrapped tokens, algorithmic stables
STABLECOIN_BLACKLIST = {
    # USD stablecoins
    "USDC", "FDUSD", "TUSD", "USDP", "GUSD", "USDD", "FRAX",
    "DAI", "LUSD", "SUSD", "ALUSD", "HUSD", "USDN", "USDE",
    "UST", "USTC", "RLUSD", "USD1", "UUSD", "BFUSD", "BUSD",
    "USDX", "USDY", "USDZ", "USDV", "MUSD", "CUSD", "SUSD",
    "YUSD", "HUSD", "ZUSD", "DUSD", "NUSD", "XUSD", "PUSD",
    # EUR / fiat pairs
    "AEUR", "EURT", "EURS", "EUR",
    # Asian fiat proxies
    "XSGD", "BIDR", "IDRT", "THBX", "BRLA",
    # Wrapped BTC/ETH (track BTC/ETH directly instead)
    "WBTC", "WETH", "WEETH", "RETH", "STETH", "CBETH", "BETH",
    # Liquid staking rebasing tokens (price tracks ETH = tight BB)
    "FRXETH", "ANKRBNB", "SFRXETH",
    # Stable algorithmic (FRAX/LUSD/USDD sudah di atas)
    "MKUSD", "CRVUSD",
}

# PLAN-SPOT-GAP S6: token komoditas/TradFi — tidak respons ke sinyal TA crypto
# (Wyckoff/EMA/BB), sama seperti exclude list di agents/futures/data.py.
COMMODITY_BLACKLIST = {
    "PAXG", "XAUT", "XAU",       # tokenized gold
    "COPPER", "SILVER", "GOLD", "OIL", "WTI", "CORN", "WHEAT", "NATGAS",
}

# Biaya eksekusi penuh (fee + spread + slippage) dari satu sumber (§15.1).
# Sizing TIDAK dihitung di sini — compute_spot_sizing (balance.py) adalah
# satu-satunya sumber ukuran posisi dari balance real (§10.3).

# ── Breakout Hunter lane (PLAN-SPOT-BREAKOUT B1-B3) ──────────────────────────
# Lane terpisah dari akumulasi — tangkap coin di AWAL pump, bukan sebelum pump.
BREAKOUT_VOL_SPIKE_MIN    = 5.0     # 15m volume > 5x average = momentum mulai
BREAKOUT_VOL_SPIKE_STRONG = 10.0   # > 10x = pump baru dimulai (full score)
BREAKOUT_CHANGE_24H_GATE  = 3.0    # minimum change_24h untuk masuk breakout pool
BREAKOUT_CHANGE_24H_MAX   = 100.0  # > 100% = parabolic, skip auto-open
BREAKOUT_MIN_VOLUME       = 500_000  # $500K 24h min (lebih relaks dari $5M akumulasi)
BREAKOUT_SCAN_POOL        = 50      # ambil top-50 mover sebagai kandidat
BREAKOUT_MIN_SCORE        = 60      # min score untuk tampil
BREAKOUT_AUTO_SCORE       = 75      # auto-open threshold (lebih rendah dari akumulasi 85)
BREAKOUT_ATR_MULTIPLIER   = 1.5    # SL = price − ATR(14) × 1.5
BREAKOUT_RISK_MIN_PCT     = 2.0    # min SL distance
BREAKOUT_RISK_MAX_PCT     = 12.0   # max SL distance (lebih lebar dari akumulasi 5%)

# ── Big Mover Chase lane (PLAN-BIG-MOVERS Phase 2 BM2) ───────────────────────
# Lane LONG-only untuk coin yang sudah pump ≥ 20% 24h atau ≥ 30% 7d. Simplified
# scoring tanpa BB Squeeze (irrelevant di breakout). B2.3: hapus full direction
# gate, ganti dengan lighter check (change_1h>0 + 5m majority green).
BIGMOVER_MIN_CHANGE_24H   = 20.0   # ≥20% qualifies
BIGMOVER_MIN_CHANGE_7D    = 30.0   # ≥30% weekly qualifies
BIGMOVER_MAX_CHANGE_24H   = 150.0  # >150% parabolic — skip
BIGMOVER_MIN_VOLUME       = 1_000_000   # $1M min (plan spec)
BIGMOVER_AUTO_SCORE       = 65     # auto-open threshold
BIGMOVER_MIN_SCORE        = 55     # min display score
BIGMOVER_RISK_PCT_DEFAULT = 0.7    # 0.7% per-trade risk (separuh accumulation 1%)
BIGMOVER_SL_PCT_MAX       = 5.0    # SL floor 5%
BIGMOVER_TP1_PCT          = 3.0
BIGMOVER_TP2_PCT          = 6.0
BIGMOVER_TP3_PCT          = 10.0
BIGMOVER_GAP_5M_LIMIT     = 5.0    # skip kalau gap antar candle 5m > 5%
BIGMOVER_ENTRY_TRAP_30M   = 15.0   # G18 entry-trap: change_30m > 15% same dir = puncak


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


def _bb_width(closes: list[float], period: int = 20) -> float:
    if len(closes) < period:
        return 1.0
    bb_closes = closes[-period:]
    mid = sum(bb_closes) / period
    std = _stddev(bb_closes)
    return (std * 4) / mid if mid > 0 else 1.0


def _vol_ratio(volumes: list[float]) -> float:
    if len(volumes) < 21:
        return 1.0
    avg = sum(volumes[-21:-1]) / 20
    return volumes[-1] / avg if avg > 0 else 1.0


def _calc_atr(klines: list, period: int = 14) -> float:
    """Average True Range — used for ATR-based SL in Breakout Hunter lane."""
    if len(klines) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        try:
            high       = float(klines[i][2])
            low        = float(klines[i][3])
            prev_close = float(klines[i - 1][4])
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        except (IndexError, ValueError):
            continue
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def _round_price(price: float, ref: float) -> float:
    """Round price to appropriate decimal places based on magnitude."""
    if ref >= 1000:  return round(price, 2)
    if ref >= 10:    return round(price, 4)
    if ref >= 0.1:   return round(price, 5)
    if ref >= 0.001: return round(price, 7)
    return round(price, 8)


# ── Per-symbol TF analysis ─────────────────────────────────────────────────────

@dataclass
class TFData:
    tf:           str
    closes:       list[float]
    volumes:      list[float]
    opens:        list[float]
    highs:        list[float]
    lows:         list[float]
    bb_width:     float = 0.0
    rsi:          float = 50.0
    vol_ratio:    float = 1.0
    ema9:         float = 0.0
    ema21:        float = 0.0
    price_slope:  float = 0.0
    vol_slope:    float = 0.0
    taker_ratio:  float = 0.5   # buy/(buy+sell) — >0.55 bullish
    live_price:   float = 0.0   # harga candle berjalan (untuk entry, BUKAN indikator)


def _analyze_tf(tf: str, klines: list) -> Optional[TFData]:
    if len(klines) < 31:
        return None
    try:
        # §10.1: candle terakhir SEDANG BERJALAN — volume parsial & close bergerak
        # membuat semua indikator (BB, RSI, vol_ratio) flicker antar scan.
        # Indikator pakai candle SELESAI saja; harga live diambil terpisah.
        live_price = float(klines[-1][4])
        klines = klines[:-1]

        opens  = [float(k[1]) for k in klines]
        highs  = [float(k[2]) for k in klines]
        lows   = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        vols   = [float(k[5]) for k in klines]

        d             = TFData(tf=tf, closes=closes, volumes=vols, opens=opens, highs=highs, lows=lows)
        d.live_price  = live_price
        d.bb_width    = _bb_width(closes)
        d.rsi         = _rsi(closes, 14)
        d.vol_ratio   = _vol_ratio(vols)
        d.ema9        = _ema(closes, 9)
        d.ema21       = _ema(closes, 21)
        d.price_slope = (closes[-1] - closes[-5]) / (closes[-5] + 1e-10) if closes[-5] > 0 else 0
        v5            = vols[-5:]
        d.vol_slope   = (v5[-1] - v5[0]) / (v5[0] + 1e-10) if v5[0] > 0 else 0

        # Taker buy/sell ratio (kline col9 = taker_buy_base, col5 = total_vol)
        ratios = []
        for k in klines[-15:]:
            try:
                total = float(k[5]); buy = float(k[9])
                if total > 0: ratios.append(buy / total)
            except (IndexError, ValueError):
                pass
        d.taker_ratio = sum(ratios) / len(ratios) if ratios else 0.5

        return d
    except Exception:
        return None


# ── Trade level calculation ────────────────────────────────────────────────────

def _calc_trade_levels(tf_data: dict[str, TFData], entry: float) -> Optional[dict]:
    """
    Risk-adjusted SPOT trade levels — designed for HIGH return in volatile crypto.

    Design philosophy:
      - SL must be wide enough to survive noise (≥1.5%, ≤5%)
      - TP must be >> fee cost: TP2 min 6%, TP3 min 10%
      - R:R to TP2 ≥ 3.5 (not 2.0) — only asymmetric trades
      - Fee-aware: 0.2% round-trip deducted from net targets

    Position sizing (built into fee math):
      - Paper balance $1000, risk 1% = $10 per trade
      - If SL=2% → position = $10/2% = $500 notional
      - If SL=3% → position = $10/3% = $333 notional

    Levels:
      SL  : swing low 4h (more stable than 1h) - 0.8% buffer
      TP1 : entry + 2.5×risk  (must net ≥ 3% after fee)
      TP2 : max(4×risk, entry+6%) — guaranteed 6% minimum
      TP3 : max(7×risk, entry+10%) — crypto 10%+ target
    """
    d1h = tf_data.get("1h")
    d4h = tf_data.get("4h")

    if not d1h or len(d1h.lows) < 10:
        return None

    # SL: swing low from 4h (more stable) with 0.8% buffer, fallback to 1h
    if d4h and len(d4h.lows) >= 10:
        recent_lows = d4h.lows[-20:] if len(d4h.lows) >= 20 else d4h.lows
    else:
        recent_lows = d1h.lows[-20:] if len(d1h.lows) >= 20 else d1h.lows
    swing_low = min(recent_lows)
    sl        = swing_low * 0.992   # 0.8% buffer below swing low

    if sl >= entry:
        return None

    risk     = entry - sl
    risk_pct = risk / entry * 100

    # SL must be 1.5%–5%: tight enough for good R:R, wide enough to survive noise
    if risk_pct > 5.0 or risk_pct < 1.5:
        return None

    # TP1: 2.5×risk — quick partial profit, net ~2.3% after fee on 2% SL
    tp1 = entry + risk * 2.5
    tp1_pct = (tp1 - entry) / entry * 100

    # TP2: 4×risk OR 6% minimum — primary target (whichever is HIGHER)
    tp2_rr    = entry + risk * 4.0
    tp2_pct_min = entry * 1.06   # min 6% from entry
    tp2       = max(tp2_rr, tp2_pct_min)

    # Check if 4h resistance is a better/higher TP2
    if d4h and len(d4h.highs) >= 10:
        highs_4h  = d4h.highs[-30:] if len(d4h.highs) >= 30 else d4h.highs
        r4h = max(highs_4h)
        rr_to_res = (r4h - entry) / risk if risk > 0 else 0
        # Use resistance only if it's ABOVE our minimum TP2 and has good R:R
        if r4h > tp2 and rr_to_res >= 3.5:
            tp2 = r4h

    # TP3: 7×risk OR 10% minimum — extended target for high volatility crypto
    tp3_rr      = entry + risk * 7.0
    tp3_pct_min = entry * 1.10   # min 10% from entry
    tp3         = max(tp3_rr, tp3_pct_min)

    # R:R check to TP2 (must be ≥ 3.5 — strict asymmetry requirement)
    rr = (tp2 - entry) / risk
    if rr < 3.5:
        return None

    # Net P&L setelah BIAYA EKSEKUSI PENUH — fee + spread + slippage (§15.1)
    def net_pct(tp: float) -> float:
        return round((tp - entry) / entry * 100 - EXECUTION_COST_PCT, 2)

    rp = _round_price

    return {
        "entry":       rp(entry, entry),
        "sl":          rp(sl, entry),
        "tp1":         rp(tp1, entry),
        "tp2":         rp(tp2, entry),
        "tp3":         rp(tp3, entry),
        "risk_pct":    round(risk_pct, 2),
        "tp1_pct":     round(tp1_pct, 2),
        "tp2_pct":     round((tp2 - entry) / entry * 100, 2),
        "tp3_pct":     round((tp3 - entry) / entry * 100, 2),
        "tp1_net_pct": net_pct(tp1),
        "tp2_net_pct": net_pct(tp2),
        "tp3_net_pct": net_pct(tp3),
        "rr_ratio":    round(rr, 1),
    }


# ── Breakout trade levels (ATR-based SL) ──────────────────────────────────────

# ── Big Mover Chase trade levels — fixed % bracket ───────────────────────────

def _calc_trade_levels_bigmover(
    klines_15m: list,
    entry: float,
) -> Optional[dict]:
    """
    SL = max(1.5% below swing-low 15m, -5%) — wider than accumulation.
    TP: fixed +3%/+6%/+10% (R:R ≥ 1.2 to TP1, ≥ 1.5 to TP2 even at max SL).
    """
    if entry <= 0 or len(klines_15m) < 20:
        return None

    # Swing low — lowest low over last 12 candles (~3 hours)
    try:
        lows = [float(k[3]) for k in klines_15m[-13:-1]]   # exclude current candle
    except (IndexError, ValueError):
        return None
    if not lows:
        return None
    swing_low = min(lows)

    sl_from_swing = swing_low * 0.985    # 1.5% below swing-low
    sl_from_floor = entry * (1 - BIGMOVER_SL_PCT_MAX / 100)
    sl = max(sl_from_swing, sl_from_floor)   # take the tighter (HIGHER for LONG)
    if sl >= entry:
        sl = entry * (1 - BIGMOVER_SL_PCT_MAX / 100)

    risk     = entry - sl
    risk_pct = risk / entry * 100
    if risk_pct < 1.0 or risk_pct > BIGMOVER_SL_PCT_MAX + 0.5:
        return None

    tp1 = entry * (1 + BIGMOVER_TP1_PCT / 100)
    tp2 = entry * (1 + BIGMOVER_TP2_PCT / 100)
    tp3 = entry * (1 + BIGMOVER_TP3_PCT / 100)

    rr = (tp2 - entry) / risk
    if rr < 1.2:
        return None

    rp = _round_price
    def net_pct(tp: float) -> float:
        return round((tp - entry) / entry * 100 - EXECUTION_COST_PCT, 2)

    return {
        "entry":       rp(entry, entry),
        "sl":          rp(sl, entry),
        "tp1":         rp(tp1, entry),
        "tp2":         rp(tp2, entry),
        "tp3":         rp(tp3, entry),
        "risk_pct":    round(risk_pct, 2),
        "tp1_pct":     BIGMOVER_TP1_PCT,
        "tp2_pct":     BIGMOVER_TP2_PCT,
        "tp3_pct":     BIGMOVER_TP3_PCT,
        "tp1_net_pct": net_pct(tp1),
        "tp2_net_pct": net_pct(tp2),
        "tp3_net_pct": net_pct(tp3),
        "rr_ratio":    round(rr, 1),
    }


def _calc_trade_levels_breakout(klines_15m: list, entry: float) -> Optional[dict]:
    """
    ATR-based trade levels for Breakout Hunter lane (B2).
    SL = price − ATR(14) × 1.5 — survives normal volatility noise.
    R:R to TP2 ≥ 3.0 required.
    """
    atr = _calc_atr(klines_15m, 14)
    if atr <= 0 or entry <= 0:
        return None

    sl       = entry - atr * BREAKOUT_ATR_MULTIPLIER
    risk     = entry - sl
    risk_pct = risk / entry * 100

    if risk_pct < BREAKOUT_RISK_MIN_PCT or risk_pct > BREAKOUT_RISK_MAX_PCT:
        return None

    tp1 = entry + risk * 2.0   # quick partial — 2× risk
    tp2 = entry + risk * 3.5   # primary target
    tp3 = entry + risk * 6.0   # extended — let momentum run

    rr = (tp2 - entry) / risk
    if rr < 3.0:
        return None

    rp = _round_price

    def net_pct(tp: float) -> float:
        return round((tp - entry) / entry * 100 - EXECUTION_COST_PCT, 2)

    return {
        "entry":       rp(entry, entry),
        "sl":          rp(sl, entry),
        "tp1":         rp(tp1, entry),
        "tp2":         rp(tp2, entry),
        "tp3":         rp(tp3, entry),
        "risk_pct":    round(risk_pct, 2),
        "tp1_pct":     round((tp1 - entry) / entry * 100, 2),
        "tp2_pct":     round((tp2 - entry) / entry * 100, 2),
        "tp3_pct":     round((tp3 - entry) / entry * 100, 2),
        "tp1_net_pct": net_pct(tp1),
        "tp2_net_pct": net_pct(tp2),
        "tp3_net_pct": net_pct(tp3),
        "rr_ratio":    round(rr, 1),
    }


# ── Breakout scoring (B3) ──────────────────────────────────────────────────────

def _score_breakout(
    symbol:     str,
    tf_data:    dict[str, "TFData"],
    change_24h: float,
    change_1h:  float,
) -> Optional[dict]:
    """
    Score a symbol for Breakout Hunter lane (B3).
    Focus: volume explosion + early price movement, NOT pre-pump accumulation.
    BM5: BB squeeze uses relative threshold (P20 of coin's own history).
    """
    score   = 0.0
    signals: list[str] = []

    d15 = tf_data.get("15m")
    d1h = tf_data.get("1h")
    ref = d15 or d1h
    if not ref:
        return None

    current_price = ref.live_price or ref.closes[-1]

    # 1. Volume spike 15m — primary signal (B1)
    vol_spike_15m = 0.0
    if d15 and len(d15.volumes) >= 21:
        avg15 = sum(d15.volumes[-21:-1]) / 20
        if avg15 > 0:
            vol_spike_15m = d15.volumes[-1] / avg15

    if vol_spike_15m >= BREAKOUT_VOL_SPIKE_STRONG:
        score += 40
        signals.append(f"🔥 Volume spike 15m {vol_spike_15m:.0f}x normal — pump baru dimulai")
    elif vol_spike_15m >= BREAKOUT_VOL_SPIKE_MIN:
        score += 20
        signals.append(f"Volume spike 15m {vol_spike_15m:.1f}x — momentum mulai")
    else:
        return None   # no volume explosion = not a breakout candidate

    # 2. Volume spike 1h
    vol_spike_1h = 0.0
    if d1h and len(d1h.volumes) >= 21:
        avg1h = sum(d1h.volumes[-21:-1]) / 20
        if avg1h > 0:
            vol_spike_1h = d1h.volumes[-1] / avg1h

    if vol_spike_1h >= 5.0:
        score += 25
        signals.append(f"🚀 Volume 1h {vol_spike_1h:.0f}x — institutional surge")
    elif vol_spike_1h >= 3.0:
        score += 12
        signals.append(f"Volume 1h {vol_spike_1h:.1f}x rata-rata")

    # 3. Price change 1h
    if change_1h >= 5.0:
        score += 15
        signals.append(f"🟢 +{change_1h:.1f}% dalam 1 jam — momentum kuat")
    elif change_1h >= 3.0:
        score += 10
        signals.append(f"+{change_1h:.1f}% dalam 1 jam")
    elif change_1h >= 2.0:
        score += 5

    # 4. Price change 15m
    change_15m = 0.0
    if d15 and len(d15.closes) >= 2 and d15.closes[-2] > 0:
        change_15m = (d15.closes[-1] - d15.closes[-2]) / d15.closes[-2] * 100
    if change_15m >= 3.0:
        score += 10
        signals.append(f"Candle 15m +{change_15m:.1f}% — breakout candle")
    elif change_15m >= 2.0:
        score += 5

    # 5. EMA9 > EMA21 di 15m
    if d15 and d15.ema9 > d15.ema21:
        score += 10
        signals.append("EMA9 > EMA21 (15m) — short-term trend up")

    # 6. Taker buy ratio
    taker_vals = [d.taker_ratio for d in tf_data.values()]
    avg_taker  = sum(taker_vals) / len(taker_vals) if taker_vals else 0.5
    if avg_taker >= 0.65:
        score += 15
        signals.append(f"🟢 Taker buy {avg_taker:.0%} — aggressive buyers masuk")
    elif avg_taker >= 0.60:
        score += 10
        signals.append(f"Taker buy {avg_taker:.0%} — buyer dominan")
    elif avg_taker >= 0.55:
        score += 5

    # 7. BM5: relative BB squeeze — compare vs coin's own P20 history
    if d15 and len(d15.closes) >= 50:
        historical_bws = [
            _bb_width(d15.closes[i - 20:i])
            for i in range(20, len(d15.closes))
        ]
        if historical_bws:
            p20_thresh = sorted(historical_bws)[max(0, len(historical_bws) // 5)]
            current_bw = _bb_width(d15.closes)
            if current_bw < p20_thresh:
                score += 10
                signals.append(f"BB Squeeze (15m) vs historis — kompresi sebelum ledakan")

    # 8. 24h context
    if change_24h < 20.0:
        score += 10
        signals.append(f"24h +{change_24h:.1f}% — early mover, belum terlambat")
    elif change_24h > 50.0:
        score -= 20
        signals.append(f"⚠️ Sudah naik {change_24h:.1f}% (24h) — risiko FOMO tinggi")

    # ── Filter ────────────────────────────────────────────────────────────────
    if score < BREAKOUT_MIN_SCORE:
        return None
    clean_signals = [s for s in signals if not s.startswith("⚠️")]
    if len(clean_signals) < 2:
        return None

    raw_score = round(score, 1)
    auto_open = (
        raw_score >= BREAKOUT_AUTO_SCORE
        and change_24h <= BREAKOUT_CHANGE_24H_MAX
        and avg_taker >= 0.55
    )

    d1h_ref = tf_data.get("1h")
    return {
        "symbol":              symbol,
        "current_price":       round(current_price, 8),
        "opportunity_score":   round(min(score, 99), 1),
        "raw_score":           raw_score,
        "direction_confirmed": avg_taker >= 0.55,
        "auto_open":           auto_open,
        "entry_mode":          "momentum_entry",
        "signals":             clean_signals[:5],
        "alert_type":          "breakout_pump",
        "change_24h":          round(change_24h, 2),
        "change_1h":           round(change_1h, 2),
        "change_7d":           0.0,
        "vol_ratio":           round(vol_spike_15m, 2),
        "avg_taker":           round(avg_taker, 3),
        "vol_spike_15m":       round(vol_spike_15m, 1),
        "vol_spike_1h":        round(vol_spike_1h, 1),
        "ema_bullish":         bool(d15 and d15.ema9 > d15.ema21),
        "squeeze_tfs":         [],
        # Fields required by frontend card components
        "tfs_confirmed":       list(tf_data.keys()),
        "bb_width_15m":        round(d15.bb_width * 100, 2) if d15 else None,
        "rsi_1h":              round(d1h_ref.rsi, 1) if d1h_ref else None,
        "weight_applied":      1.0,
        "banned_by_learning":  False,
    }


# ── Big Mover Chase scoring (PLAN-BIG-MOVERS Phase 2 BM2) ─────────────────────

def _score_bigmover_chase(
    symbol:     str,
    tf_data:    dict[str, "TFData"],
    change_24h: float,
    change_1h:  float,
    change_7d:  float,
) -> Optional[dict]:
    """
    LONG-only lane untuk coin yang sudah pump kuat. Simplified scoring:
      vol_ratio + RSI bracket + EMA bullish + buy pressure.
    TIDAK pakai BB Squeeze (irrelevant di breakout).
    B2.3 lighter direction gate: change_1h > 0 AND 3-candle 5m majority green.
    G14 noise filter: skip gap 5m > 5%, candle 5m zero-vol.
    G18 entry-trap: skip kalau change_30m > 15% (puncak literal).
    """
    score   = 0.0
    signals: list[str] = []

    d15 = tf_data.get("15m")
    d1h = tf_data.get("1h")
    ref = d15 or d1h
    if not ref:
        return None

    current_price = ref.live_price or ref.closes[-1]
    if current_price <= 0:
        return None

    # ── G14 noise filter ──────────────────────────────────────────────────────
    if d15 and len(d15.closes) >= 3:
        # Gap between last 2 candles > 5%
        prev2 = d15.closes[-2]
        if prev2 > 0:
            gap_pct = abs(d15.closes[-1] - prev2) / prev2 * 100
            if gap_pct > BIGMOVER_GAP_5M_LIMIT:
                return None
        # Zero-vol candle count
        zero_vol = sum(1 for v in d15.volumes[-5:] if v == 0)
        if zero_vol >= 2:
            return None

    # ── G18 entry-trap (puncak literal) ───────────────────────────────────────
    if d15 and len(d15.closes) >= 7:
        # change_30m = 2 × 15m
        prev30 = d15.closes[-3]
        if prev30 > 0:
            chg_30m = (d15.closes[-1] - prev30) / prev30 * 100
            if chg_30m > BIGMOVER_ENTRY_TRAP_30M:
                return None
        # recent_high_5m == current (literal top)
        if current_price >= max(d15.highs[-5:]) * 0.999:
            return None

    # ── B2.3 lighter direction gate ───────────────────────────────────────────
    # change_1h > 0 AND last 3 (15m) candles majority green
    if change_1h <= 0:
        return None
    if d15 and len(d15.opens) >= 3 and len(d15.closes) >= 3:
        green = sum(1 for i in (-3, -2, -1) if d15.closes[i] >= d15.opens[i])
        if green < 2:
            return None

    # ── 1. Volume ratio (0-25 pts) ────────────────────────────────────────────
    best_vol = 0.0
    if d15 and d15.vol_ratio >= 3.0:
        best_vol = 25
        signals.append(f"Volume 15m {d15.vol_ratio:.1f}× — pressure dikonfirmasi")
    elif d15 and d15.vol_ratio >= 2.0:
        best_vol = 18
        signals.append(f"Volume 15m {d15.vol_ratio:.1f}× rata-rata")
    elif d15 and d15.vol_ratio >= 1.3:
        best_vol = 10
    score += best_vol

    # ── 2. RSI < 80 sweet zone (0-15 pts) ─────────────────────────────────────
    rsi_val = d1h.rsi if d1h else (d15.rsi if d15 else 50)
    if 55 <= rsi_val <= 72:
        score += 15
        signals.append(f"RSI {rsi_val:.0f} — momentum zone, masih ada room")
    elif 50 <= rsi_val < 55:
        score += 10
    elif 72 < rsi_val <= 80:
        score += 7
        signals.append(f"RSI {rsi_val:.0f} extended — hati-hati exhaustion")
    elif rsi_val > 80:
        return None   # overbought hard skip

    # ── 3. EMA alignment (0-15 pts) ───────────────────────────────────────────
    aligned = sum(1 for d in tf_data.values() if d.ema9 > d.ema21)
    if aligned >= 3:
        score += 15
        signals.append("EMA bullish 3 TF — trend kuat semua")
    elif aligned == 2:
        score += 10
    elif aligned == 1:
        score += 4

    # ── 4. Buy pressure (taker ratio) (0-15 pts) ──────────────────────────────
    taker_vals = [d.taker_ratio for d in tf_data.values()]
    avg_taker  = sum(taker_vals) / len(taker_vals) if taker_vals else 0.5
    if avg_taker >= 0.62:
        score += 15
        signals.append(f"Taker buy {avg_taker:.0%} — buyer agresif")
    elif avg_taker >= 0.55:
        score += 9

    # ── 5. Momentum context (0-20 pts) ────────────────────────────────────────
    if 20 <= change_24h < 35:
        score += 12
        signals.append(f"Δ24h +{change_24h:.1f}% — wave matang, room masih ada")
    elif 35 <= change_24h < 70:
        score += 18
        signals.append(f"💥 Δ24h +{change_24h:.1f}% — momentum kuat")
    elif 70 <= change_24h <= 100:
        score += 20
        signals.append(f"🚀 Δ24h +{change_24h:.1f}% — parabolic ride")
    elif change_24h > BIGMOVER_MAX_CHANGE_24H:
        return None
    # Weekly bonus
    if change_7d >= 50:
        score += 8
        signals.append(f"7d +{change_7d:.0f}% — weekly momentum kuat")
    elif change_7d >= 30:
        score += 5

    # ── 6. 1h confirm (0-10 pts) ──────────────────────────────────────────────
    if change_1h >= 3:
        score += 10
        signals.append(f"1h +{change_1h:.1f}% — masih chasing")
    elif change_1h >= 1:
        score += 5

    # ── Finalize ──────────────────────────────────────────────────────────────
    if score < BIGMOVER_MIN_SCORE:
        return None
    clean_signals = [s for s in signals if not s.startswith("⚠")]

    raw_score = round(score, 1)
    auto_open = raw_score >= BIGMOVER_AUTO_SCORE   # B2.3: direction gate sudah lighter, OK to auto

    return {
        "symbol":              symbol,
        "current_price":       round(current_price, 8),
        "opportunity_score":   round(min(score, 99), 1),
        "raw_score":           raw_score,
        "direction_confirmed": True,    # passed lighter gate above
        "auto_open":           auto_open,
        "entry_mode":          "bigmover_chase",
        "signals":             clean_signals[:5],
        "alert_type":          "bigmover_chase",
        "change_24h":          round(change_24h, 2),
        "change_1h":           round(change_1h, 2),
        "change_7d":           round(change_7d, 2),
        "vol_ratio":           round(d15.vol_ratio if d15 else 1.0, 2),
        "avg_taker":           round(avg_taker, 3),
        "ema_bullish":         bool(d1h and d1h.ema9 > d1h.ema21),
        "squeeze_tfs":         [],
        "tfs_confirmed":       list(tf_data.keys()),
        "bb_width_15m":        round(d15.bb_width * 100, 2) if d15 else None,
        "rsi_1h":              round(d1h.rsi, 1) if d1h else None,
        "weight_applied":      1.0,
        "banned_by_learning":  False,
    }


# ── Opportunity scoring ────────────────────────────────────────────────────────

def _score_symbol(
    symbol: str,
    tf_data: dict[str, TFData],
    change_24h: float,
    change_1h: float,
    change_7d: float = 0.0,
) -> Optional[dict]:
    """Score a symbol and return opportunity dict, or None if score < MIN_SCORE."""
    score   = 0.0
    signals: list[str] = []
    alert   = "accumulation"
    # PLAN-SPOT-GAP: koin dengan weekly momentum kuat dapat keringanan di gate
    # RSI(4h) dan penalty change_24h>20% — sebelumnya kedua gate ini membuang
    # SEMUA top-gainer mingguan tanpa pengecualian (lihat RC-1/RC-2/RC-5).
    strong_weekly_momentum = change_7d >= 20.0

    ref = tf_data.get("15m") or tf_data.get("1h")
    if not ref:
        return None
    # Harga live dari candle berjalan (indikator memakai candle selesai — §10.1)
    current_price = ref.live_price or ref.closes[-1]

    # ── GERBANG ARAH (§12.1): LONG-only wajib konfirmasi arah ─────────────────
    # Squeeze itu arah-netral — kompresi meledak ke bawah sama seringnya.
    d1h_dir   = tf_data.get("1h")
    taker_avg = sum(d.taker_ratio for d in tf_data.values()) / len(tf_data)
    direction_confirmed = (
        taker_avg >= DIRECTION_TAKER_MIN
        or bool(d1h_dir and d1h_dir.ema9 > d1h_dir.ema21)
    )

    # 1. BB Squeeze (multi-TF) ─────────────────────────────────────────────────
    squeeze_tfs = []
    for tf, d in tf_data.items():
        thresh = {"15m": 0.035, "1h": 0.05, "4h": 0.07}.get(tf, 0.05)
        if d.bb_width < thresh:
            squeeze_tfs.append(tf)

    if len(squeeze_tfs) >= 2:
        # Tanpa arah, kompresi hanya bernilai kecil (§12.1)
        score += 35 if direction_confirmed else 10
        signals.append(f"🔵 BB Squeeze di {' + '.join(squeeze_tfs)} — ledakan volatilitas mendekat")
        alert = "squeeze"
    elif len(squeeze_tfs) == 1:
        score += 15 if direction_confirmed else 5
        signals.append(f"BB Squeeze {squeeze_tfs[0]}")

    # 2. Smart Money Accumulation ──────────────────────────────────────────────
    d15 = tf_data.get("15m")
    d1h = tf_data.get("1h")
    best = d15 or d1h
    if best:
        if best.vol_slope > 0.25 and abs(best.price_slope) < 0.03:
            score += 25
            signals.append(f"📦 Akumulasi: volume +{best.vol_slope*100:.0f}% saat harga flat")
        elif best.vol_ratio > 2.0 and abs(best.price_slope) < 0.04:
            score += 15
            signals.append(f"Volume {best.vol_ratio:.1f}x rata-rata — konsolidasi kuat")
        elif best.vol_slope > 0.15 and best.price_slope < 0:
            score += 20
            signals.append("💪 Volume naik saat harga turun — hidden strength")

    # 3. RSI Zone + REM OVERBOUGHT timeframe besar (§10.4) ────────────────────
    # Rem dulu: RSI 4h sangat tinggi = parabolic, pola klasik beli di pucuk.
    # PLAN-SPOT-GAP RC-1/RC-2: gate ini dulu membuang TOTAL setiap koin yang
    # sudah naik kuat minggu ini (RSI 4h hampir pasti tinggi setelah weekly pump),
    # padahal itu justru target utama lane ini. Kalau ada weekly momentum kuat,
    # turunkan jadi penalty ringan — jangan buang total.
    d4h_rsi = tf_data["4h"].rsi if "4h" in tf_data else None
    if d4h_rsi is not None and d4h_rsi > 82:
        if not strong_weekly_momentum:
            return None   # skip total — jangan tampil sebagai rekomendasi pun
        score -= 10
        signals.append(f"⚠️ RSI(4h) {d4h_rsi:.0f} sangat overbought, tapi weekly +{change_7d:.1f}% — tetap dipertimbangkan hati-hati")
    elif d4h_rsi is not None and d4h_rsi > 75:
        if strong_weekly_momentum:
            score -= 5
            signals.append(f"RSI(4h) {d4h_rsi:.0f} tinggi, tapi weekly momentum +{change_7d:.1f}% kuat — penalty dikurangi")
        else:
            score -= 15
            signals.append(f"⚠️ RSI(4h) {d4h_rsi:.0f} — overbought berat, risiko pucuk")

    for tf, d in tf_data.items():
        if 35 <= d.rsi <= 55:
            score += 10
            signals.append(f"RSI({tf}) {d.rsi:.0f} — zona energi, belum overbought")
            break
        elif d.rsi < 35:
            score += 12
            signals.append(f"RSI({tf}) {d.rsi:.0f} — oversold, potensi reversal")
            break

    # 4. Buy Pressure Surge ────────────────────────────────────────────────────
    if best and len(best.opens) >= 10:
        n = 5
        def bp(o: list, c: list, v: list) -> float:
            return sum(v[i] for i in range(n) if c[i] >= o[i]) / (sum(v) or 1)
        bp_now  = bp(best.opens[-n:],     best.closes[-n:],     best.volumes[-n:])
        bp_prev = bp(best.opens[-n*2:-n], best.closes[-n*2:-n], best.volumes[-n*2:-n])
        shift   = bp_now - bp_prev
        if shift > 0.20:
            score += 15
            signals.append(f"🟢 Buy pressure meningkat +{shift*100:.0f}%")
        elif shift > 0.10:
            score += 8
            signals.append(f"Buy pressure membaik +{shift*100:.0f}%")

    # 5. EMA Alignment ─────────────────────────────────────────────────────────
    aligned = [tf for tf, d in tf_data.items() if d.ema9 > d.ema21]
    if len(aligned) >= 2:
        score += 10
        signals.append(f"EMA9 > EMA21 di {'+'.join(aligned)} — trend naik")

    # 6. Near Breakout ─────────────────────────────────────────────────────────
    for tf, d in tf_data.items():
        recent_high = max(d.highs[-30:]) if len(d.highs) >= 30 else max(d.highs)
        dist = (recent_high - current_price) / current_price
        if 0 < dist < 0.03:
            score += 15
            signals.append(f"🎯 {dist*100:.1f}% dari breakout level {tf}")
            alert = "breakout"
            break

    # 7. Momentum 24h ──────────────────────────────────────────────────────────
    # PLAN-SPOT-GAP RC-5: kalau >20% itu adalah BAGIAN dari weekly top-gainer
    # move (bukan parabolic dadakan hari ini), penalty diringankan jauh —
    # "sudah naik" itu justru tujuan lane ini, bukan alasan untuk membuang.
    if 3 <= change_24h <= 20:
        score += 8
        signals.append(f"Momentum +{change_24h:.1f}% (24h) — mulai bergerak")
    elif change_24h > 20:
        if strong_weekly_momentum:
            score -= 3
            signals.append(f"🚀 Sudah naik {change_24h:.1f}% (24h) + {change_7d:.1f}% (7d) — top gainer momentum, bukan FOMO dadakan")
        else:
            score -= 10
            signals.append(f"⚠️ Sudah naik {change_24h:.1f}% (entry terlambat?)")

    # 8. Short-term momentum ───────────────────────────────────────────────────
    if 1 <= change_1h <= 5:
        score += 5

    # 9. Taker buy ratio (institutional flow proxy) ────────────────────────────
    taker_vals = [d.taker_ratio for d in tf_data.values()]
    avg_taker  = sum(taker_vals) / len(taker_vals) if taker_vals else 0.5
    if avg_taker >= 0.62:
        score += 15
        signals.append(f"🟢 Taker buy {avg_taker:.0%} — institusi akumulasi diam-diam")
    elif avg_taker >= 0.58:
        score += 10
        signals.append(f"Taker buy {avg_taker:.0%} — tekanan beli dominan")
    elif avg_taker >= 0.55:
        score += 5

    # 10. Volume Spike (>5x normal = extraordinary interest) ──────────────────
    if best and best.vol_ratio >= 5.0:
        score += 10
        signals.append(f"🔥 Volume spike {best.vol_ratio:.0f}x normal — extraordinary interest")
    elif best and best.vol_ratio >= 3.0:
        score += 5

    # 11. Multi-TF EMA bullish alignment (all 3 TFs) ──────────────────────────
    all_bullish = all(d.ema9 > d.ema21 for d in tf_data.values())
    if all_bullish and len(tf_data) >= 3:
        score += 5   # bonus on top of base EMA score
        signals.append("⚡ EMA bullish alignment semua TF — momentum sangat kuat")

    # 12. R8 Momentum Chase — coin sudah naik ≥ 10%, pullback sehat, siap second leg
    # PLAN-SPOT-GAP S3/RC-6: gate lama cuma lihat change_24h — koin yang pump-nya
    # terjadi hari ke-2/3 minggu ini lalu flat 2 hari terakhir (change_24h kecil)
    # tidak pernah ke-trigger, padahal itu setup continuation paling sehat yang
    # ingin dicari lane ini. Trigger sekarang JUGA via change_7d.
    entry_mode = "fresh_setup"
    if change_24h >= MOMENTUM_CHASE_MIN_24H or strong_weekly_momentum:
        d1h = tf_data.get("1h")
        if d1h:
            # Band RSI sedikit dilebarkan (40-65, dari 45-65) untuk weekly mover
            # yang baru mulai cooling tapi belum sepenuhnya turun ke zona "fresh".
            rsi_cooling  = 40 <= d1h.rsi <= 65
            ema_holding  = d1h.ema9 > d1h.ema21 * 0.99   # EMA9 di atas EMA21 (buffer 1%)
            # Volume declining selama pullback = konsolidasi sehat (bukan distribusi)
            vol_healthy  = True
            if len(d1h.volumes) >= 8:
                recent_vol = sum(d1h.volumes[-3:]) / 3
                prior_vol  = sum(d1h.volumes[-8:-3]) / 5
                vol_healthy = recent_vol < prior_vol * 1.1   # tidak ada lonjakan volume saat turun
            if rsi_cooling and ema_holding:
                score += 15
                entry_mode = "momentum_chase"
                signals.append(
                    f"🚀 Momentum pullback: +{change_24h:.1f}% 24h / +{change_7d:.1f}% 7d, "
                    f"RSI {d1h.rsi:.0f} cooling, EMA holding"
                )
                if vol_healthy:
                    score += 8
                    signals.append("📉 Volume turun saat pullback — konsolidasi sehat, bukan distribusi")

    # ── Filter & finalize ─────────────────────────────────────────────────────
    clean_signals = [s for s in signals if not s.startswith("⚠️")]
    if score < MIN_SCORE or len(clean_signals) < 2:
        return None

    # Dominant alert type
    if len(squeeze_tfs) >= 2:
        alert = "squeeze"
    elif any("📦" in s for s in signals):
        alert = "accumulation"
    elif any("🎯" in s for s in signals):
        alert = "breakout"

    # §10.2: raw_score TANPA cap untuk ranking + conviction sizing;
    # cap 99 hanya untuk tampilan UI (legacy display contract)
    raw_score     = round(score, 1)
    display_score = round(min(score, 99), 1)
    # §12.1: auto-open WAJIB gerbang arah; tanpa itu hanya rekomendasi manual
    # R4: fast-track untuk coin yang sudah bergerak kuat (change_24h ≥ 8%)
    momentum_fasttrack = change_24h >= FASTTRACK_24H_PCT and raw_score >= FASTTRACK_MIN_SCORE
    auto_open = (raw_score >= AUTO_OPEN_SCORE or momentum_fasttrack) and direction_confirmed

    # EMA bullish at entry time — stored in meta so monitor can detect REAL reversals
    d1h_ref = tf_data.get("1h")
    ema_bullish_at_entry = bool(d1h_ref and d1h_ref.ema9 > d1h_ref.ema21) if d1h_ref else True

    return {
        "symbol":              symbol,
        "current_price":       round(current_price, 8),
        "opportunity_score":   display_score,
        "raw_score":           raw_score,
        "direction_confirmed": direction_confirmed,
        "auto_open":           auto_open,
        "momentum_fasttrack":  momentum_fasttrack,
        "entry_mode":          entry_mode,
        "signals":             clean_signals[:5],
        "alert_type":          alert,
        "change_24h":          round(change_24h, 2),
        "change_1h":           round(change_1h, 2),
        "change_7d":           round(change_7d, 2),
        "vol_ratio":           round(best.vol_ratio if best else 1.0, 2),
        "avg_taker":           round(avg_taker, 3),
        "bb_width_15m":        round(tf_data["15m"].bb_width * 100, 2) if "15m" in tf_data else None,
        "rsi_1h":              round(tf_data["1h"].rsi, 1) if "1h" in tf_data else None,
        "tfs_confirmed":       list(tf_data.keys()),
        "squeeze_tfs":         squeeze_tfs,
        "ema_bullish":         ema_bullish_at_entry,  # for monitor trend_reversal detection
    }


# ── HTTP helpers ───────────────────────────────────────────────────────────────

async def _fetch_klines(client: httpx.AsyncClient, symbol: str, tf: str) -> list:
    """Fetch OHLCV klines from Binance Spot API."""
    try:
        r = await client.get(
            spot(f"/api/v3/klines?symbol={symbol}&interval={tf}&limit={CANDLE_LIMIT}")
        )
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list) and len(d) >= 30:
                return d
    except Exception:
        pass
    return []


# ── Main scan ──────────────────────────────────────────────────────────────────

async def _load_alert_weights() -> tuple[dict[str, float], set[str]]:
    """
    Load per-alert-type adaptive weights from DB.
    Returns (weights, banned_types). banned (§14.7): weight < 0.8 dengan n ≥ 10
    → tipe itu DILARANG auto-open sampai win rate pulih — learning yang punya gigi.
    """
    try:
        from app.database import AsyncSessionLocal, is_db_available
        from app.models.signal_weight import AgentSignalWeight
        from sqlalchemy import select as _select

        if not is_db_available():
            return {}, set()

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                _select(AgentSignalWeight).where(
                    AgentSignalWeight.agent      == "opportunity_spot",
                    AgentSignalWeight.signal_key.like("alert:%"),
                    AgentSignalWeight.total_count >= 3,
                )
            )
            rows    = list(result.scalars().all())
            weights = {r.signal_key.replace("alert:", ""): r.weight for r in rows}
            banned  = {
                r.signal_key.replace("alert:", "")
                for r in rows
                if r.weight < 0.8 and r.total_count >= 10
            }
            return weights, banned
    except Exception:
        return {}, set()


def _ev_per_risk(result: dict) -> float:
    """
    Expected value per unit risk (§11.4) — SATU sumber ranking untuk
    scheduler DAN UI. p_win dari RAW pre-weight score (§7.4), reward = TP2 NET.
    """
    p      = min(result.get("raw_score", result.get("opportunity_score", 0)), 99) / 100
    reward = result.get("tp2_net_pct", 0) or 0
    risk   = result.get("risk_pct", 0) or 2.0
    ev     = p * reward - (1 - p) * risk
    return round(ev / risk, 3)


def _btc_regime(tf_data_btc: Optional[dict], btc_change_24h: float) -> tuple[str, str]:
    """
    Phase 3 G3-regime: graceful 3-state degradation (was binary open/closed).

    Returns (label, status) where status ∈ {"OPEN", "REDUCED", "CLOSED"}.

    - CLOSED:  btc_change_24h ≤ −5%                          → no auto-open
    - REDUCED: btc_change_24h ≤ −3%                          → 1 open/cycle, not 3
    - REDUCED: BTC 4h EMA bearish AND btc_change_24h < −1%   → double-confirm
    - OPEN:    everything else (incl. mildly red days)       → normal full quota
    """
    if btc_change_24h <= BTC_REGIME_CLOSED_24H:
        return "bearish_24h_severe", "CLOSED"
    if btc_change_24h <= BTC_REGIME_REDUCED_24H:
        return "bearish_24h", "REDUCED"

    if tf_data_btc:
        d4h = tf_data_btc.get("4h")
        if (d4h and d4h.ema9 < d4h.ema21
                and btc_change_24h < BTC_REGIME_DOUBLE_CONFIRM_24H):
            return "bearish_4h_double_confirm", "REDUCED"
        d1h = tf_data_btc.get("1h")
        if d1h and d1h.ema9 > d1h.ema21:
            return "bull", "OPEN"
    return "flat", "OPEN"


async def run_opportunity_scan() -> dict:
    """
    Scan top-100 USDT SPOT pairs.
    Returns coins with valid Entry/SL/TP recommendations (R:R ≥ 2.0).
    """
    start = time.time()
    logger.info("opportunity_scan_start")

    # Load adaptive weights (non-blocking — uses default 1.0 if DB unavailable)
    alert_weights, banned_types = await _load_alert_weights()

    # 1. Get top-100 by quote volume (Spot)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(spot("/api/v3/ticker/24hr"))
        if r.status_code != 200:
            # §10.6: jangan diam — UI harus bisa bedakan "scan gagal" vs "kosong"
            logger.warning("scan_ticker_failed", status=r.status_code)
            return {"results": [], "scanned": 0, "found": 0,
                    "generated_at": int(time.time()), "elapsed_sec": 0,
                    "error": f"ticker_24hr gagal (HTTP {r.status_code})"}
        tickers = [t for t in r.json() if str(t.get("symbol", "")).endswith("USDT")]

    tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)

    # Filter 1: name-based blacklist
    def _is_stablecoin(sym: str) -> bool:
        # Strip USDT suffix correctly (handle edge cases like "USDTUSDT")
        base = sym.upper()
        if base.endswith("USDT"):
            base = base[:-4]           # remove last 4 chars "USDT"
        return base in STABLECOIN_BLACKLIST

    tickers = [t for t in tickers if not _is_stablecoin(t["symbol"])]

    # PLAN-SPOT-GAP S6: exclude commodity/TradFi tokens (XAUT, PAXG, dst) — sinyal
    # TA crypto (BB Squeeze, taker ratio, dst) tidak relevan untuk instrumen ini.
    def _is_commodity(sym: str) -> bool:
        base = sym.upper()
        if base.endswith("USDT"):
            base = base[:-4]
        return base in COMMODITY_BLACKLIST

    tickers = [t for t in tickers if not _is_commodity(t["symbol"])]

    # Filter 2: price-range guard — if price ≈ $1 and barely moving, skip
    # Catches new stablecoins not yet in the blacklist
    def _is_pegged(t: dict) -> bool:
        try:
            price  = float(t.get("lastPrice", 0))
            chg24h = abs(float(t.get("priceChangePercent", 0)))
            # Pegged instrument: price $0.96–$1.05 and 24h change < 1%
            return 0.96 < price < 1.05 and chg24h < 1.0
        except Exception:
            return False

    tickers = [t for t in tickers if not _is_pegged(t)]

    # Simpan semua tickers setelah name-filter (sebelum liquidity filter).
    # Breakout Hunter lane pakai threshold lebih rendah ($500K), bukan $5M,
    # sehingga harus baca dari sini — bukan dari `tickers` post-liquidity.
    tickers_all = tickers[:]

    # Filter 3 (§11.7): likuiditas minimum — rekomendasi harus eksekutable
    def _liquid(t: dict) -> bool:
        try:
            return float(t.get("quoteVolume", 0)) >= MIN_QUOTE_VOLUME
        except (TypeError, ValueError):
            return False

    tickers    = [t for t in tickers if _liquid(t)]
    candidates = tickers[:100]

    # R7: Momentum priority supplement — tambahkan coin di luar top-100 volume
    # yang sedang bergerak kuat (change_24h ≥ 5%). Coin ini sering tidak masuk
    # top-100 karena volume normalnya kecil, tapi saat pump volume melonjak.
    momentum_supplement = sorted(
        [t for t in tickers[100:] if float(t.get("priceChangePercent", 0)) >= MOMENTUM_SCAN_MIN_PCT],
        key=lambda t: float(t.get("priceChangePercent", 0)),
        reverse=True,
    )[:MOMENTUM_SCAN_EXTRA]
    if momentum_supplement:
        logger.info("momentum_scan_supplement", extra=len(momentum_supplement),
                    top_mover=momentum_supplement[0]["symbol"] if momentum_supplement else None)
        candidates = candidates + momentum_supplement

    # PLAN-SPOT-GAP S4: weekly-momentum supplement — pool lebih luas (rank 100-250
    # by volume), cek change_7d via klines 4h SAJA (murah, 1 TF bukan 3) sebelum
    # diputuskan masuk candidates penuh. Skip simbol yang sudah ada di candidates.
    existing_syms = {c["symbol"] for c in candidates}
    weekly_pool   = [
        t for t in tickers[100:100 + WEEKLY_SCAN_POOL]
        if t["symbol"] not in existing_syms
        and float(t.get("quoteVolume", 0)) >= WEEKLY_SCAN_MIN_VOLUME
    ]
    if weekly_pool:
        _wsem = asyncio.Semaphore(15)

        async def _fetch_4h_only(client: httpx.AsyncClient, sym: str) -> tuple[str, list]:
            async with _wsem:
                return sym, await _fetch_klines(client, sym, "4h")

        async with httpx.AsyncClient(timeout=20) as wclient:
            wtasks = [asyncio.create_task(_fetch_4h_only(wclient, t["symbol"])) for t in weekly_pool]
            weekly_klines: dict[str, list] = {}
            for task in wtasks:
                sym, kl = await task
                weekly_klines[sym] = kl

        weekly_movers = []
        for t in weekly_pool:
            kl = weekly_klines.get(t["symbol"], [])
            if len(kl) < 43:   # butuh 42 candle selesai + 1 candle berjalan
                continue
            closes = [float(k[4]) for k in kl[:-1]]   # buang candle berjalan (§10.1)
            if len(closes) < 42 or closes[-42] <= 0:
                continue
            chg7d = (closes[-1] - closes[-42]) / closes[-42] * 100
            if chg7d >= WEEKLY_CHANGE_MIN_PCT:
                weekly_movers.append((chg7d, t))

        weekly_movers.sort(key=lambda x: x[0], reverse=True)
        weekly_supplement = [t for _, t in weekly_movers[:WEEKLY_SCAN_EXTRA]]
        if weekly_supplement:
            logger.info("weekly_momentum_supplement", extra=len(weekly_supplement),
                        top_mover=weekly_supplement[0]["symbol"],
                        top_change_7d=round(weekly_movers[0][0], 1))
            candidates = candidates + weekly_supplement

    # BTC 24h change untuk regime gate (§12.5)
    btc_change_24h = 0.0
    for t in candidates:
        if t["symbol"] == "BTCUSDT":
            try:
                btc_change_24h = float(t.get("priceChangePercent", 0))
            except (TypeError, ValueError):
                pass
            break

    # 2. Fetch klines concurrently — semaphore caps at 15 simultaneous requests
    # (100 coins × 3 TF = 300 total; weight=2 each → max 30 weight at a time)
    _sem = asyncio.Semaphore(15)

    async def _fetch_limited(client: httpx.AsyncClient, sym: str, tf: str) -> list:
        async with _sem:
            return await _fetch_klines(client, sym, tf)

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = {
            (t["symbol"], tf): asyncio.create_task(_fetch_limited(client, t["symbol"], tf))
            for t in candidates
            for tf in TIMEFRAMES
        }
        klines_map: dict = {}
        for (sym, tf), task in tasks.items():
            klines_map[(sym, tf)] = await task

    # 3. Score + calculate trade levels
    results = []
    btc_tf_data: Optional[dict] = None
    for ticker in candidates:
        symbol     = ticker["symbol"]
        change_24h = float(ticker.get("priceChangePercent", 0))

        tf_data: dict[str, TFData] = {}
        for tf in TIMEFRAMES:
            d = _analyze_tf(tf, klines_map.get((symbol, tf), []))
            if d:
                tf_data[tf] = d

        if not tf_data:
            continue
        if symbol == "BTCUSDT":
            btc_tf_data = tf_data

        d1h       = tf_data.get("1h")
        change_1h = 0.0
        if d1h and len(d1h.closes) >= 2:
            change_1h = (d1h.closes[-1] - d1h.closes[-2]) / (d1h.closes[-2] + 1e-10) * 100

        # PLAN-SPOT-GAP S1: change_7d dari klines 4h yang sudah ditarik (42 candle
        # 4h ≈ 7 hari). Data ini sudah ada di memory (CANDLE_LIMIT=100), cuma
        # sebelumnya tidak pernah dipakai untuk mengukur performa mingguan.
        d4h       = tf_data.get("4h")
        change_7d = 0.0
        if d4h and len(d4h.closes) >= 42 and d4h.closes[-42] > 0:
            change_7d = (d4h.closes[-1] - d4h.closes[-42]) / d4h.closes[-42] * 100

        # P1: store 24h quote volume so scheduler + auto_open can compute slippage
        quote_vol = float(ticker.get("quoteVolume", 0) or 0)

        result = _score_symbol(symbol, tf_data, change_24h, change_1h, change_7d)
        if result is None:
            continue

        # Bobot learning: HANYA mengubah skor display & ranking — keputusan
        # auto_open dan conviction sizing tetap dari raw pre-weight score (§7.4)
        alert_weight = alert_weights.get(result["alert_type"], 1.0)
        if alert_weight != 1.0:
            result["opportunity_score"] = round(
                min(result["opportunity_score"] * alert_weight, 99), 1
            )
        result["weight_applied"] = alert_weight

        # §14.7: tipe dengan track record busuk (weight<0.8, n≥10) dilarang auto-open
        if result["alert_type"] in banned_types:
            result["auto_open"]      = False
            result["banned_by_learning"] = True

        if result["opportunity_score"] < MIN_SCORE:
            continue  # penalti bobot boleh menggugurkan kandidat marjinal

        levels = _calc_trade_levels(tf_data, result["current_price"])
        if levels is None:
            continue  # skip coins without valid Entry/SL/TP

        result.update(levels)
        result["quote_vol_24h"] = quote_vol
        result["ev_per_risk"]   = _ev_per_risk(result)

        # P2: MIN_NET_EV gate — TP2 net profit must be ≥ 1.5% after fees + dynamic slippage
        from app.services.slippage_sim import calculate_entry_slippage as _cslip
        _SPOT_FIXED_COST = 0.26   # 0.10%×2 taker + 0.06% spread
        _net_tp2 = result.get("tp2_pct", 0) - _SPOT_FIXED_COST - _cslip(quote_vol)
        if _net_tp2 < 1.5:
            continue

        results.append(result)

    # ── PLAN-SPOT-BREAKOUT B4: Breakout Hunter pass ───────────────────────────
    # Scan ALL movers (change_24h >= 3%, vol >= $500K) for sudden volume explosion.
    # Separate from accumulation lane — different SL, scoring, entry_mode.
    # BUG-FIX: use tickers_all (pre-liquidity-filter) so low-vol coins like CREAM
    # ($276K) and PNT ($262K) can enter — that's the whole point of BREAKOUT_MIN_VOLUME.
    _accum_syms     = {c["symbol"] for c in candidates}
    _all_ticker_map = {t["symbol"]: t for t in tickers_all}
    _breakout_done  = {r["symbol"] for r in results}

    # Pool: all movers not in main candidates (rank 101+) + main candidates as re-score
    _extra_movers = sorted(
        [
            t for t in tickers_all
            if float(t.get("priceChangePercent", 0)) >= BREAKOUT_CHANGE_24H_GATE
            and float(t.get("quoteVolume", 0)) >= BREAKOUT_MIN_VOLUME
            and t["symbol"] not in _accum_syms   # not already fetched in main scan
        ],
        key=lambda t: float(t.get("priceChangePercent", 0)),
        reverse=True,
    )[:BREAKOUT_SCAN_POOL]

    # Fetch klines for extra movers not in main scan
    if _extra_movers:
        _bsem = asyncio.Semaphore(10)

        async def _fetch_b(sym: str, tf: str) -> list:
            async with _bsem:
                return await _fetch_klines(_bclient, sym, tf)

        async with httpx.AsyncClient(timeout=25) as _bclient:
            _btasks = {
                (t["symbol"], tf): asyncio.create_task(_fetch_b(t["symbol"], tf))
                for t in _extra_movers
                for tf in TIMEFRAMES
            }
            for (bsym, btf), btask in _btasks.items():
                try:
                    klines_map[(bsym, btf)] = await btask
                except Exception:
                    klines_map[(bsym, btf)] = []

    # Score breakout candidates: main candidates + extra movers
    _breakout_pool = (
        [c["symbol"] for c in candidates]        # already have klines
        + [t["symbol"] for t in _extra_movers]   # just fetched
    )
    breakout_results: list[dict] = []

    for bsym in _breakout_pool:
        if bsym in _breakout_done:
            continue   # already in accumulation results, skip duplicate
        bticker = _all_ticker_map.get(bsym)
        if not bticker:
            continue
        bchange_24h = float(bticker.get("priceChangePercent", 0))
        if bchange_24h < BREAKOUT_CHANGE_24H_GATE:
            continue

        btf_data: dict[str, TFData] = {}
        for tf in TIMEFRAMES:
            bd = _analyze_tf(tf, klines_map.get((bsym, tf), []))
            if bd:
                btf_data[tf] = bd
        if not btf_data:
            continue

        bd1h      = btf_data.get("1h")
        bchange_1h = 0.0
        if bd1h and len(bd1h.closes) >= 2 and bd1h.closes[-2] > 0:
            bchange_1h = (bd1h.closes[-1] - bd1h.closes[-2]) / bd1h.closes[-2] * 100

        bres = _score_breakout(bsym, btf_data, bchange_24h, bchange_1h)
        if bres is None:
            continue

        blevels = _calc_trade_levels_breakout(
            klines_map.get((bsym, "15m"), []), bres["current_price"]
        )
        if blevels is None:
            continue

        bres.update(blevels)
        bres["quote_vol_24h"] = float((_all_ticker_map.get(bsym) or {}).get("quoteVolume", 0) or 0)
        bres["ev_per_risk"]   = _ev_per_risk(bres)
        # P2: MIN_NET_EV gate
        from app.services.slippage_sim import calculate_entry_slippage as _cslip
        if bres.get("tp2_pct", 0) - 0.26 - _cslip(bres["quote_vol_24h"]) < 1.5:
            continue
        breakout_results.append(bres)
        _breakout_done.add(bsym)

    logger.info("breakout_scan_done", found=len(breakout_results),
                pool=len(_breakout_pool))

    # ── PLAN-BIG-MOVERS Phase 2 BM2: Big Mover Chase pass ─────────────────────
    # LONG-only. Pool: change_24h ≥ 20% OR change_7d ≥ 30%. Min vol $1M.
    # B2.4: dedup via _breakout_done (shared across accumulation + breakout + bigmover).
    bigmover_results: list[dict] = []
    bm_extra_movers = [
        t for t in tickers_all
        if (
            float(t.get("priceChangePercent", 0)) >= BIGMOVER_MIN_CHANGE_24H
            and float(t.get("quoteVolume", 0)) >= BIGMOVER_MIN_VOLUME
            and t["symbol"] not in _breakout_done
            and t["symbol"] not in _accum_syms
        )
    ][:30]

    if bm_extra_movers:
        # Fetch klines for extras not already pulled
        _bm_sem = asyncio.Semaphore(10)

        async def _fetch_bm(client: httpx.AsyncClient, sym: str, tf: str) -> list:
            async with _bm_sem:
                return await _fetch_klines(client, sym, tf)

        async with httpx.AsyncClient(timeout=25) as _bm_client:
            _bm_tasks = {
                (t["symbol"], tf): asyncio.create_task(_fetch_bm(_bm_client, t["symbol"], tf))
                for t in bm_extra_movers
                for tf in TIMEFRAMES
            }
            for (bsym, btf), btask in _bm_tasks.items():
                try:
                    klines_map[(bsym, btf)] = await btask
                except Exception:
                    klines_map[(bsym, btf)] = []

    # Score: main candidates already in candidates list + extras
    _bm_pool = (
        [c["symbol"] for c in candidates]
        + [t["symbol"] for t in bm_extra_movers]
    )
    for bsym in _bm_pool:
        if bsym in _breakout_done:
            continue
        bticker = _all_ticker_map.get(bsym)
        if not bticker:
            continue
        try:
            bm_change_24h = float(bticker.get("priceChangePercent", 0))
        except (TypeError, ValueError):
            continue
        if bm_change_24h < BIGMOVER_MIN_CHANGE_24H:
            continue

        bm_tf: dict[str, TFData] = {}
        for tf in TIMEFRAMES:
            bd = _analyze_tf(tf, klines_map.get((bsym, tf), []))
            if bd:
                bm_tf[tf] = bd
        if not bm_tf:
            continue

        bm_d1h = bm_tf.get("1h")
        bm_change_1h = 0.0
        if bm_d1h and len(bm_d1h.closes) >= 2 and bm_d1h.closes[-2] > 0:
            bm_change_1h = (bm_d1h.closes[-1] - bm_d1h.closes[-2]) / bm_d1h.closes[-2] * 100

        bm_d4h = bm_tf.get("4h")
        bm_change_7d = 0.0
        if bm_d4h and len(bm_d4h.closes) >= 42 and bm_d4h.closes[-42] > 0:
            bm_change_7d = (bm_d4h.closes[-1] - bm_d4h.closes[-42]) / bm_d4h.closes[-42] * 100

        # Qualify: ≥20% 24h OR ≥30% 7d
        if bm_change_24h < BIGMOVER_MIN_CHANGE_24H and bm_change_7d < BIGMOVER_MIN_CHANGE_7D:
            continue

        bm_res = _score_bigmover_chase(
            bsym, bm_tf, bm_change_24h, bm_change_1h, bm_change_7d,
        )
        if bm_res is None:
            continue

        bm_levels = _calc_trade_levels_bigmover(
            klines_map.get((bsym, "15m"), []), bm_res["current_price"],
        )
        if bm_levels is None:
            continue

        bm_res.update(bm_levels)
        bm_res["quote_vol_24h"] = float((_all_ticker_map.get(bsym) or {}).get("quoteVolume", 0) or 0)
        bm_res["ev_per_risk"]   = _ev_per_risk(bm_res)
        # P2: MIN_NET_EV gate
        from app.services.slippage_sim import calculate_entry_slippage as _cslip
        if bm_res.get("tp2_pct", 0) - 0.26 - _cslip(bm_res["quote_vol_24h"]) < 1.5:
            continue
        bigmover_results.append(bm_res)
        _breakout_done.add(bsym)   # B2.4: shared dedup across all passes

    bigmover_results.sort(key=lambda x: x.get("raw_score", 0), reverse=True)
    bigmover_results = bigmover_results[:10]
    logger.info("bigmover_chase_scan_done", found=len(bigmover_results),
                pool=len(_bm_pool), extras=len(bm_extra_movers))

    # §12.5 + Phase 3 G3-regime: 3-state — CLOSED kills auto-open, REDUCED keeps
    # auto_open flag (scheduler enforces lower quota), OPEN normal.
    regime, regime_status = _btc_regime(btc_tf_data, btc_change_24h)
    if regime_status == "CLOSED":
        for r_ in results:
            r_["auto_open"] = False
        for r_ in breakout_results:
            r_["auto_open"] = False
        for r_ in bigmover_results:
            r_["auto_open"] = False
        logger.info("scan_regime_gate_closed", regime=regime, btc_24h=btc_change_24h)
    elif regime_status == "REDUCED":
        logger.info("scan_regime_gate_reduced", regime=regime, btc_24h=btc_change_24h)

    # §11.4: ranking & TOP_N — accumulation lane sorted by EV per risk
    results.sort(key=lambda x: x.get("ev_per_risk", 0), reverse=True)
    results = results[:TOP_N]

    # Breakout lane: sort by raw_score, cap at 10 results
    breakout_results.sort(key=lambda x: x.get("raw_score", 0), reverse=True)
    breakout_results = breakout_results[:10]

    all_results = results + breakout_results + bigmover_results

    elapsed = round(time.time() - start, 1)
    logger.info("opportunity_scan_done",
                found=len(all_results), scanned=len(candidates),
                breakout_found=len(breakout_results),
                bigmover_found=len(bigmover_results),
                regime=regime, elapsed_sec=elapsed)

    return {
        "results":            all_results,
        "scanned":            len(candidates),
        "found":              len(all_results),
        "found_accumulation": len(results),
        "found_breakout":     len(breakout_results),
        "found_bigmover":     len(bigmover_results),
        "btc_regime":         regime,
        "regime_status":      regime_status,    # Phase 3 G3-regime: OPEN | REDUCED | CLOSED
        "btc_change_24h":     round(btc_change_24h, 2),
        "generated_at":       int(time.time()),
        "elapsed_sec":        elapsed,
    }
