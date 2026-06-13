"""
Coin Analysis Agent (Layer 2) — deep per-coin analysis on demand.

Triggered when user clicks a coin card. Fetches 200 candles, calculates:
  - ATR-based Stop Loss (precise, using real swing lows + volatility buffer)
  - Resistance-based Take Profits (TP1 = nearest, TP2 = main, TP3 = extended)
  - Taker buy/sell ratio (proxy for institutional flow)
  - Confidence score based on signal confluence

Called from: POST /api/v1/opportunity/analyze/{symbol}
"""

import asyncio
import math
import time
from typing import Optional

import httpx
import structlog

from app.services.binance_urls import spot

logger = structlog.get_logger(__name__)

TIMEFRAMES   = ["15m", "1h", "4h"]
CANDLE_LIMIT = 200


# ── Math helpers ───────────────────────────────────────────────────────────────

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
    """Average True Range — volatility measure."""
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
    """Local maxima — potential resistance levels."""
    pivots = []
    for i in range(lookback, len(highs) - lookback):
        window = highs[i - lookback : i + lookback + 1]
        if highs[i] >= max(window):
            pivots.append(highs[i])
    return sorted(set(pivots))


def _swing_lows(lows: list[float], lookback: int = 5) -> list[float]:
    """Local minima — potential support levels."""
    pivots = []
    for i in range(lookback, len(lows) - lookback):
        window = lows[i - lookback : i + lookback + 1]
        if lows[i] <= min(window):
            pivots.append(lows[i])
    return sorted(set(pivots))


def _taker_ratio(klines: list, last_n: int = 20) -> float:
    """
    Average taker buy ratio over last N candles.
    Binance kline[9] = taker_buy_base_volume, kline[5] = total_volume.
    > 0.55 = bullish (buyers dominating)
    < 0.45 = bearish (sellers dominating)
    """
    ratios = []
    for k in klines[-last_n:]:
        try:
            total = float(k[5])
            buy   = float(k[9])
            if total > 0:
                ratios.append(buy / total)
        except (IndexError, ValueError):
            pass
    return round(sum(ratios) / len(ratios), 3) if ratios else 0.5


def _round_price(price: float, ref: float) -> float:
    if ref >= 1000:  return round(price, 2)
    if ref >= 10:    return round(price, 4)
    if ref >= 0.1:   return round(price, 5)
    if ref >= 0.001: return round(price, 7)
    return round(price, 8)


def _bb_width(closes: list[float], period: int = 20) -> float:
    if len(closes) < period:
        return 0.0
    tail = closes[-period:]
    mean = sum(tail) / period
    std  = math.sqrt(sum((v - mean) ** 2 for v in tail) / period)
    return (std * 4) / mean * 100 if mean > 0 else 0.0


# ── Market depth ──────────────────────────────────────────────────────────────

async def _fetch_depth_ratio(client: httpx.AsyncClient, symbol: str, price: float) -> float | None:
    """
    Order book pressure ratio: bid_vol / (bid_vol + ask_vol) within 1% of price.
    > 0.55 = bid-heavy (buyers pressuring), < 0.45 = ask-heavy (sellers pressuring).
    Returns None if API call fails.
    """
    try:
        r = await client.get(
            spot(f"/api/v3/depth?symbol={symbol}&limit=20"),
            timeout=6,
        )
        if r.status_code != 200:
            return None
        book  = r.json()
        lo, hi = price * 0.99, price * 1.01

        bid_vol = sum(float(q) for p, q in book.get("bids", []) if lo <= float(p) <= hi)
        ask_vol = sum(float(q) for p, q in book.get("asks", []) if lo <= float(p) <= hi)
        total   = bid_vol + ask_vol
        return round(bid_vol / total, 3) if total > 0 else None
    except Exception:
        return None


# ── Core analysis ─────────────────────────────────────────────────────────────

async def _fetch_klines(client: httpx.AsyncClient, symbol: str, tf: str) -> list:
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


async def analyze_coin(symbol: str) -> dict:
    """
    Deep analysis for one coin — called on user click.
    Returns fresh Entry/SL/TP with ATR-based precision + confidence score.
    Takes ~2–4 seconds.
    """
    start = time.time()
    logger.info("analyzer_start", symbol=symbol)

    # Fetch all TFs + order book concurrently
    async with httpx.AsyncClient(timeout=15) as client:
        tf15, tf1h, tf4h, _depth_placeholder = await asyncio.gather(
            _fetch_klines(client, symbol, "15m"),
            _fetch_klines(client, symbol, "1h"),
            _fetch_klines(client, symbol, "4h"),
            asyncio.sleep(0),           # placeholder — depth needs price first
        )

    klines = {"15m": tf15, "1h": tf1h, "4h": tf4h}
    klines = {k: v for k, v in klines.items() if v}

    if not klines:
        return {"error": "Tidak bisa ambil data koin ini"}

    # Use 1h as primary; fallback to 15m
    primary = klines.get("1h") or klines.get("15m") or list(klines.values())[0]

    # §16.3 (≡ §10.1): entry = harga live dari candle berjalan; INDIKATOR
    # dihitung dari candle SELESAI saja supaya tidak flicker
    entry   = float(primary[-1][4])
    primary = primary[:-1]
    klines  = {k: v[:-1] for k, v in klines.items() if len(v) > 1}

    opens  = [float(k[1]) for k in primary]
    highs  = [float(k[2]) for k in primary]
    lows   = [float(k[3]) for k in primary]
    closes = [float(k[4]) for k in primary]
    rp    = _round_price

    # ── Indicators ──────────────────────────────────────────────────────────────
    atr      = _atr(highs, lows, closes, 14)
    rsi      = _rsi(closes, 14)
    ema9     = _ema(closes, 9)
    ema21    = _ema(closes, 21)
    bb_w     = _bb_width(closes)
    taker    = _taker_ratio(primary)

    # Taker ratio on 4h (stronger signal)
    taker_4h = _taker_ratio(klines["4h"]) if "4h" in klines else taker

    # Order book depth ratio (fetch now that we have entry price)
    async with httpx.AsyncClient(timeout=8) as depth_client:
        depth_ratio = await _fetch_depth_ratio(depth_client, symbol, entry)

    # ── SL: nearest swing low + ATR buffer ───────────────────────────────────
    s_lows   = _swing_lows(lows, lookback=5)
    below    = [sl for sl in s_lows if sl < entry * 0.999]  # must be below entry
    nearest_low = max(below) if below else min(lows[-30:])

    # Buffer: 0.3× ATR below the swing low (not too wide, not noise)
    sl      = nearest_low - atr * 0.3
    risk    = entry - sl
    risk_pct = risk / entry * 100

    # §16.1: aturan risk SAMA dengan scanner (1.5–5%) — analyzer bukan pintu
    # belakang yang membypass disiplin. ATR fallback, lalu clamp keras.
    if risk_pct > 5.0 or risk_pct < 1.5:
        sl       = entry - atr * 1.5
        risk     = entry - sl
        risk_pct = risk / entry * 100
    if risk_pct < 1.5:
        sl       = entry * (1 - 0.015)
        risk     = entry - sl
        risk_pct = 1.5
    elif risk_pct > 5.0:
        sl       = entry * (1 - 0.05)
        risk     = entry - sl
        risk_pct = 5.0

    # ── TPs: swing highs (resistance) then R:R fallback ──────────────────────
    s_highs_1h = _swing_highs(highs, lookback=5)
    resistances = sorted([h for h in s_highs_1h if h > entry * 1.003])

    # Augment with 4h swing highs for longer targets
    if "4h" in klines:
        highs_4h   = [float(k[2]) for k in klines["4h"]]
        for h in _swing_highs(highs_4h, lookback=3):
            if h > entry * 1.003 and h not in resistances:
                resistances.append(h)
        resistances = sorted(resistances)

    tp1 = resistances[0] if len(resistances) > 0 else rp(entry + risk * 1.5, entry)
    tp2 = resistances[1] if len(resistances) > 1 else rp(entry + risk * 3.0, entry)
    tp3 = resistances[2] if len(resistances) > 2 else rp(entry + risk * 5.0, entry)

    # Ensure ascending: tp1 < tp2 < tp3, all above entry
    if tp1 <= entry: tp1 = entry + risk * 1.5
    if tp2 <= tp1:   tp2 = tp1 + risk * 1.5
    if tp3 <= tp2:   tp3 = tp2 + risk * 2.0

    rr = (tp2 - entry) / risk if risk > 0 else 0

    # §16.1: ENFORCE R:R minimum yang sama dengan scanner. Resistance terlalu
    # dekat → angkat TP2 ke standar minimum (4×risk / +6%) seperti scanner.
    below_standard = rr < 3.5
    if below_standard:
        tp2 = max(entry + risk * 4.0, entry * 1.06)
        if tp3 <= tp2:
            tp3 = max(entry + risk * 7.0, entry * 1.10)
        rr  = (tp2 - entry) / risk if risk > 0 else 0

    # ── Analysis signals ──────────────────────────────────────────────────────
    signals = []
    if bb_w < 5:
        signals.append(f"🔵 BB Squeeze 1h ({bb_w:.1f}%) — volatilitas terkompresi, ledakan mendekat")
    if taker_4h > 0.56:
        signals.append(f"🟢 Taker buy {taker_4h:.0%} (4h) — institusi akumulasi secara diam-diam")
    elif taker > 0.55:
        signals.append(f"🟢 Taker buy {taker:.0%} (1h) — tekanan beli dominan")
    if depth_ratio is not None and depth_ratio > 0.58:
        signals.append(f"📊 Order book {depth_ratio:.0%} bid — tekanan beli kuat di level ini")
    elif depth_ratio is not None and depth_ratio < 0.42:
        signals.append(f"📊 Order book {depth_ratio:.0%} ask — tekanan jual mendominasi")
    if rsi < 35:
        signals.append(f"RSI {rsi:.0f} — oversold ekstrem, potensi reversal kuat")
    elif rsi < 50:
        signals.append(f"RSI {rsi:.0f} — zona energi, belum overbought")
    if ema9 > ema21:
        signals.append(f"EMA9 > EMA21 — momentum bullish terkonfirmasi")
    if len(resistances) >= 2:
        signals.append(f"🎯 {len(resistances)} level resistance terdeteksi dari price history")
    if not signals:
        signals.append(f"Analisis multi-TF selesai · ATR={rp(atr, entry)}")

    # ── Confidence score ──────────────────────────────────────────────────────
    conf = 40
    if bb_w < 5:                                  conf += 20
    if taker_4h > 0.55:                           conf += 15
    if rsi < 50:                                  conf += 10
    if ema9 > ema21:                              conf += 10
    if rr >= 2.0:                                 conf += 10
    if rr >= 3.0:                                 conf += 10
    if len(resistances) >= 2:                     conf += 5
    if depth_ratio is not None and depth_ratio > 0.55: conf += 5
    conf = min(conf, 99)

    elapsed = round(time.time() - start, 2)
    logger.info("analyzer_done", symbol=symbol, elapsed=elapsed, rr=round(rr, 1))

    return {
        "symbol":       symbol,
        "entry":        rp(entry, entry),
        "sl":           rp(sl, entry),
        "tp1":          rp(tp1, entry),
        "tp2":          rp(tp2, entry),
        "tp3":          rp(tp3, entry),
        "risk_pct":     round(risk_pct, 2),
        "tp1_pct":      round((tp1 - entry) / entry * 100, 2),
        "tp2_pct":      round((tp2 - entry) / entry * 100, 2),
        "tp3_pct":      round((tp3 - entry) / entry * 100, 2),
        "rr_ratio":     round(rr, 1),
        "atr":          rp(atr, entry),
        "taker_ratio":  taker,
        "taker_ratio_4h": taker_4h,
        "rsi_1h":       round(rsi, 1),
        "bb_width_1h":  round(bb_w, 2),
        "ema_bullish":   ema9 > ema21,
        "depth_ratio":   depth_ratio,   # order book bid/(bid+ask) within 1% — None if unavailable
        "signals":       signals,
        "confidence":    conf,
        "below_standard": below_standard,  # §16.1: TP asli < standar R:R, sudah diangkat
        "elapsed_sec":   elapsed,
    }
