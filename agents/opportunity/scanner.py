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
BTC_REGIME_24H_MIN  = -3.0   # BTC 24h di bawah ini → auto-open OFF

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


def _btc_regime(tf_data_btc: Optional[dict], btc_change_24h: float) -> tuple[str, bool]:
    """
    Regime BTC (§12.5): saat BTC turun tajam, hampir semua alt LONG gagal serentak.
    Returns (label, auto_open_allowed).
    """
    if btc_change_24h < BTC_REGIME_24H_MIN:
        return "bearish_24h", False
    if tf_data_btc:
        d4h = tf_data_btc.get("4h")
        if d4h and d4h.ema9 < d4h.ema21:
            return "bearish_4h", False
        d1h = tf_data_btc.get("1h")
        if d1h and d1h.ema9 > d1h.ema21:
            return "bull", True
    return "flat", True


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
        result["ev_per_risk"] = _ev_per_risk(result)
        results.append(result)

    # §12.5: regime gate BTC — auto-open OFF saat market memusuhi LONG
    regime, auto_allowed = _btc_regime(btc_tf_data, btc_change_24h)
    if not auto_allowed:
        for r_ in results:
            r_["auto_open"] = False
        logger.info("scan_regime_gate_active", regime=regime,
                    btc_24h=btc_change_24h)

    # §11.4: ranking & TOP_N berdasarkan EV per unit risk — bukan score
    results.sort(key=lambda x: x.get("ev_per_risk", 0), reverse=True)
    results = results[:TOP_N]

    elapsed = round(time.time() - start, 1)
    logger.info("opportunity_scan_done",
                found=len(results), scanned=len(candidates),
                regime=regime, elapsed_sec=elapsed)

    return {
        "results":      results,
        "scanned":      len(candidates),
        "found":        len(results),
        "btc_regime":   regime,
        "generated_at": int(time.time()),
        "elapsed_sec":  elapsed,
    }
