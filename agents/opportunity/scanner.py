"""
Opportunity Scanner (SPOT) — cari koin berpotensi kenaikan berkali lipat.

Tujuan:
  Temukan koin yang sedang dalam fase akumulasi SEBELUM breakout besar.
  Fokus pada sinyal yang menunjukkan potensi kenaikan 2x–10x.

Cara kerja:
  1. Scan top-100 + small-cap candidates dari Binance Spot
  2. Score 0–100+ menggunakan 9 sinyal multi-timeframe
  3. Score ≥ 95 → AUTO-OPEN posisi tanpa persetujuan manual
  4. Score 60–94 → Rekomendasi manual
  5. Score < 60 → Skip

Auto-open trigger (score ≥ 95):
  - BB Squeeze multi-TF + Volume surge + Taker buy dominan + EMA bullish
  - Semua kondisi harus terpenuhi bersamaan (high conviction)

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

logger = structlog.get_logger(__name__)

TIMEFRAMES        = ["15m", "1h", "4h"]
CANDLE_LIMIT      = 100
TOP_N             = 30
MIN_SCORE         = 40    # minimum untuk direkomendasikan
AUTO_OPEN_SCORE   = 95    # minimum untuk auto-open tanpa konfirmasi manual


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


def _analyze_tf(tf: str, klines: list) -> Optional[TFData]:
    if len(klines) < 30:
        return None
    try:
        opens  = [float(k[1]) for k in klines]
        highs  = [float(k[2]) for k in klines]
        lows   = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        vols   = [float(k[5]) for k in klines]

        d             = TFData(tf=tf, closes=closes, volumes=vols, opens=opens, highs=highs, lows=lows)
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
    Calculate SPOT position levels: Entry, SL, TP1, TP2, TP3.

    SL  : di bawah swing low 1h (20 candle) dengan buffer 0.5%
    TP1 : R:R 1:1.5 — profit cepat
    TP2 : R:R 1:3   — target utama (atau resistance 4h jika lebih tinggi)
    TP3 : R:R 1:5   — extended target
    """
    d1h = tf_data.get("1h")
    d4h = tf_data.get("4h")

    if not d1h or len(d1h.lows) < 10:
        return None

    # SL: below recent swing low on 1h
    recent_lows = d1h.lows[-20:] if len(d1h.lows) >= 20 else d1h.lows
    swing_low   = min(recent_lows)
    sl          = swing_low * 0.995  # 0.5% buffer below swing low

    if sl >= entry:
        return None

    risk     = entry - sl
    risk_pct = risk / entry * 100

    # Filter: SL too wide (> 8%) or too tight (< 0.4% — too close to noise)
    if risk_pct > 8.0 or risk_pct < 0.4:
        return None

    # Find resistance for TP2 target
    resistance = None
    if d4h and len(d4h.highs) >= 20:
        highs_4h  = d4h.highs[-30:] if len(d4h.highs) >= 30 else d4h.highs
        r4h       = max(highs_4h)
        rr_to_res = (r4h - entry) / risk if risk > 0 else 0
        if r4h > entry * 1.01 and rr_to_res >= 2.0:
            resistance = r4h
    if resistance is None and d1h and len(d1h.highs) >= 20:
        highs_1h  = d1h.highs[-30:] if len(d1h.highs) >= 30 else d1h.highs
        r1h       = max(highs_1h)
        rr_to_res = (r1h - entry) / risk if risk > 0 else 0
        if r1h > entry * 1.01 and rr_to_res >= 2.0:
            resistance = r1h

    # Calculate TPs
    tp1 = entry + risk * 1.5
    tp2 = resistance if resistance else entry + risk * 3.0
    tp3 = entry + risk * 5.0

    # Final R:R check (must be >= 2.0 to TP2)
    rr = (tp2 - entry) / risk
    if rr < 2.0:
        return None

    rp = _round_price

    return {
        "entry":    rp(entry, entry),
        "sl":       rp(sl, entry),
        "tp1":      rp(tp1, entry),
        "tp2":      rp(tp2, entry),
        "tp3":      rp(tp3, entry),
        "risk_pct": round(risk_pct, 2),
        "tp1_pct":  round((tp1 - entry) / entry * 100, 2),
        "tp2_pct":  round((tp2 - entry) / entry * 100, 2),
        "tp3_pct":  round((tp3 - entry) / entry * 100, 2),
        "rr_ratio": round(rr, 1),
    }


# ── Opportunity scoring ────────────────────────────────────────────────────────

def _score_symbol(
    symbol: str,
    tf_data: dict[str, TFData],
    change_24h: float,
    change_1h: float,
) -> Optional[dict]:
    """Score a symbol and return opportunity dict, or None if score < MIN_SCORE."""
    score   = 0.0
    signals: list[str] = []
    alert   = "accumulation"

    ref = tf_data.get("15m") or tf_data.get("1h")
    if not ref:
        return None
    current_price = ref.closes[-1]

    # 1. BB Squeeze (multi-TF) ─────────────────────────────────────────────────
    squeeze_tfs = []
    for tf, d in tf_data.items():
        thresh = {"15m": 0.035, "1h": 0.05, "4h": 0.07}.get(tf, 0.05)
        if d.bb_width < thresh:
            squeeze_tfs.append(tf)

    if len(squeeze_tfs) >= 2:
        score += 35
        signals.append(f"🔵 BB Squeeze di {' + '.join(squeeze_tfs)} — ledakan volatilitas mendekat")
        alert = "squeeze"
    elif len(squeeze_tfs) == 1:
        score += 15
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

    # 3. RSI Zone ──────────────────────────────────────────────────────────────
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
    if 3 <= change_24h <= 20:
        score += 8
        signals.append(f"Momentum +{change_24h:.1f}% (24h) — mulai bergerak")
    elif change_24h > 20:
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

    final_score = round(min(score, 99), 1)
    auto_open   = final_score >= AUTO_OPEN_SCORE

    return {
        "symbol":            symbol,
        "current_price":     round(current_price, 8),
        "opportunity_score": final_score,
        "auto_open":         auto_open,   # True = posisi dibuka otomatis
        "signals":           clean_signals[:5],
        "alert_type":        alert,
        "change_24h":        round(change_24h, 2),
        "change_1h":         round(change_1h, 2),
        "vol_ratio":         round(best.vol_ratio if best else 1.0, 2),
        "avg_taker":         round(avg_taker, 3),
        "bb_width_15m":      round(tf_data["15m"].bb_width * 100, 2) if "15m" in tf_data else None,
        "rsi_1h":            round(tf_data["1h"].rsi, 1) if "1h" in tf_data else None,
        "tfs_confirmed":     list(tf_data.keys()),
        "squeeze_tfs":       squeeze_tfs,
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

async def run_opportunity_scan() -> dict:
    """
    Scan top-100 USDT SPOT pairs.
    Returns coins with valid Entry/SL/TP recommendations (R:R ≥ 2.0).
    """
    start = time.time()
    logger.info("opportunity_scan_start")

    # 1. Get top-100 by quote volume (Spot)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(spot("/api/v3/ticker/24hr"))
        if r.status_code != 200:
            return {"results": [], "scanned": 0, "found": 0,
                    "generated_at": int(time.time()), "elapsed_sec": 0}
        tickers = [t for t in r.json() if str(t.get("symbol", "")).endswith("USDT")]

    tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    candidates = tickers[:100]

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

        d1h       = tf_data.get("1h")
        change_1h = 0.0
        if d1h and len(d1h.closes) >= 2:
            change_1h = (d1h.closes[-1] - d1h.closes[-2]) / (d1h.closes[-2] + 1e-10) * 100

        result = _score_symbol(symbol, tf_data, change_24h, change_1h)
        if result is None:
            continue

        levels = _calc_trade_levels(tf_data, result["current_price"])
        if levels is None:
            continue  # skip coins without valid Entry/SL/TP

        result.update(levels)
        results.append(result)

    results.sort(key=lambda x: x["opportunity_score"], reverse=True)
    results = results[:TOP_N]

    elapsed = round(time.time() - start, 1)
    logger.info("opportunity_scan_done",
                found=len(results), scanned=len(candidates), elapsed_sec=elapsed)

    return {
        "results":      results,
        "scanned":      len(candidates),
        "found":        len(results),
        "generated_at": int(time.time()),
        "elapsed_sec":  elapsed,
    }
