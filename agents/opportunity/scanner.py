"""
Opportunity Scanner — finds coins with high potential for price increase.

Multi-timeframe analysis (15m + 1h + 4h) to detect:
  1. BB Squeeze on 2+ timeframes        → explosive move incoming
  2. Volume accumulation (price flat)   → smart money entering quietly
  3. RSI reset from oversold            → energy recharging
  4. Buy pressure surge                 → institutional buying
  5. Near breakout level                → one push needed
  6. Momentum building                  → trend starting

Scoring 0-100:
  ≥ 70 = 🔥 High potential (multiple confirmations)
  50–69 = ⚡ Watch closely
  30–49 = 👀 Early stage signal
  < 30  = ignored
"""

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import structlog

from app.services.binance_urls import fapi

logger = structlog.get_logger(__name__)

TIMEFRAMES   = ["15m", "1h", "4h"]
CANDLE_LIMIT = 100
TOP_N        = 30        # return top 30 opportunities
MIN_SCORE    = 30        # minimum score to include in results


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


# ── Per-symbol analysis ────────────────────────────────────────────────────────

@dataclass
class TFData:
    tf:          str
    closes:      list[float]
    volumes:     list[float]
    opens:       list[float]
    highs:       list[float]
    lows:        list[float]
    bb_width:    float = 0.0
    rsi:         float = 50.0
    vol_ratio:   float = 1.0
    ema9:        float = 0.0
    ema21:       float = 0.0
    price_slope: float = 0.0
    vol_slope:   float = 0.0


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
        return d
    except Exception:
        return None


def _score_symbol(
    symbol: str,
    tf_data: dict[str, TFData],
    change_24h: float,
    change_1h: float,
) -> Optional[dict]:
    """
    Compute opportunity score for a symbol using multi-TF data.
    Returns None if score < MIN_SCORE.
    """
    score   = 0.0
    signals = []
    alert   = "accumulation"

    price      = tf_data.get("15m") or tf_data.get("1h")
    if not price:
        return None
    current_price = price.closes[-1]

    # ── 1. BB Squeeze (multi-TF) ───────────────────────────────────────────────
    squeeze_tfs = []
    for tf, d in tf_data.items():
        squeeze_thresh = {"15m": 0.035, "1h": 0.05, "4h": 0.07}.get(tf, 0.05)
        if d.bb_width < squeeze_thresh:
            squeeze_tfs.append(tf)

    if len(squeeze_tfs) >= 2:
        score += 35
        signals.append(f"🔵 BB Squeeze di {' + '.join(squeeze_tfs)} (multi-TF koil)")
        alert = "squeeze"
    elif len(squeeze_tfs) == 1:
        score += 15
        signals.append(f"BB Squeeze {squeeze_tfs[0]}")

    # ── 2. Smart Money Accumulation ────────────────────────────────────────────
    # Volume naik tapi harga flat = akumulasi diam-diam
    d15 = tf_data.get("15m")
    d1h = tf_data.get("1h")
    best_d = d15 or d1h
    if best_d:
        if best_d.vol_slope > 0.25 and abs(best_d.price_slope) < 0.03:
            score += 25
            signals.append(f"📦 Akumulasi: vol +{best_d.vol_slope*100:.0f}% harga flat")
            alert = "accumulation"
        elif best_d.vol_ratio > 2.0 and abs(best_d.price_slope) < 0.04:
            score += 15
            signals.append(f"Vol {best_d.vol_ratio:.1f}x avg, harga konsolidasi")
        elif best_d.vol_slope > 0.15 and best_d.price_slope < 0:
            score += 20
            signals.append("💪 Volume naik saat harga turun (hidden strength)")

    # ── 3. RSI Reset / Energy Zone ────────────────────────────────────────────
    for tf, d in tf_data.items():
        if 35 <= d.rsi <= 55:
            score += 10
            signals.append(f"RSI({tf}) {d.rsi:.0f} — zona energi")
            break
        elif d.rsi < 35:
            score += 12
            signals.append(f"RSI({tf}) {d.rsi:.0f} — oversold recovery")
            break

    # ── 4. Buy Pressure Surge ─────────────────────────────────────────────────
    if best_d and len(best_d.opens) >= 10:
        n = 5
        def bp(o, c, v): return sum(v[i] for i in range(n) if c[i] >= o[i]) / (sum(v) or 1)
        bp_now  = bp(best_d.opens[-n:],   best_d.closes[-n:],   best_d.volumes[-n:])
        bp_prev = bp(best_d.opens[-n*2:-n], best_d.closes[-n*2:-n], best_d.volumes[-n*2:-n])
        shift = bp_now - bp_prev
        if shift > 0.20:
            score += 15
            signals.append(f"🟢 Buy pressure +{shift*100:.0f}% naik signifikan")
        elif shift > 0.10:
            score += 8
            signals.append(f"Buy pressure membaik +{shift*100:.0f}%")

    # ── 5. EMA Alignment ──────────────────────────────────────────────────────
    aligned_tfs = [tf for tf, d in tf_data.items() if d.ema9 > d.ema21]
    if len(aligned_tfs) >= 2:
        score += 10
        signals.append(f"EMA9>21 di {'+'.join(aligned_tfs)} (trend alignment)")

    # ── 6. Near Breakout ──────────────────────────────────────────────────────
    # Check if approaching recent high on any TF
    for tf, d in tf_data.items():
        recent_high = max(d.highs[-30:]) if len(d.highs) >= 30 else max(d.highs)
        dist = (recent_high - current_price) / current_price
        if 0 < dist < 0.03:
            score += 15
            signals.append(f"🎯 {dist*100:.1f}% dari breakout level ({tf})")
            alert = "breakout"
            break

    # ── 7. Momentum 24h ───────────────────────────────────────────────────────
    if 3 <= change_24h <= 20:
        score += 8
        signals.append(f"Momentum +{change_24h:.1f}% (24h)")
    elif change_24h > 20:
        score -= 10  # already pumped
        signals.append(f"⚠️ Sudah naik {change_24h:.1f}% (entry terlambat?)")

    # ── 8. Recent 1h momentum ─────────────────────────────────────────────────
    if 1 <= change_1h <= 5:
        score += 5
        signals.append(f"+{change_1h:.1f}% (1h) momentum fresh")

    # ── Filter ────────────────────────────────────────────────────────────────
    clean_signals = [s for s in signals if not s.startswith("⚠️")]
    if score < MIN_SCORE or len(clean_signals) < 2:
        return None

    # ── Alert type ────────────────────────────────────────────────────────────
    if len(squeeze_tfs) >= 2:
        alert = "squeeze"
    elif "📦" in " ".join(signals):
        alert = "accumulation"
    elif "🎯" in " ".join(signals):
        alert = "breakout"

    tfs_confirmed = list(tf_data.keys())

    return {
        "symbol":           symbol,
        "current_price":    round(current_price, 8),
        "opportunity_score": round(min(score, 99), 1),
        "signals":          clean_signals[:4],
        "alert_type":       alert,
        "change_24h":       round(change_24h, 2),
        "change_1h":        round(change_1h, 2),
        "vol_ratio":        round(best_d.vol_ratio if best_d else 1.0, 2),
        "bb_width_15m":     round(tf_data["15m"].bb_width * 100, 2) if "15m" in tf_data else None,
        "rsi_1h":           round(tf_data["1h"].rsi, 1) if "1h" in tf_data else None,
        "tfs_confirmed":    tfs_confirmed,
        "squeeze_tfs":      squeeze_tfs,
    }


# ── Main scan function ─────────────────────────────────────────────────────────

async def _fetch_klines(client: httpx.AsyncClient, symbol: str, tf: str) -> list:
    try:
        r = await client.get(fapi(f"/fapi/v1/klines?symbol={symbol}&interval={tf}&limit={CANDLE_LIMIT}"))
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list) and len(d) >= 30:
                return d
    except Exception:
        pass
    return []


async def run_opportunity_scan() -> dict:
    """
    Full opportunity scan across 100 top USDT pairs.
    Returns top-N coins ranked by opportunity score.
    """
    start = time.time()
    logger.info("opportunity_scan_start")

    # Fetch top 100 by volume
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(fapi("/fapi/v1/ticker/24hr"))
        if r.status_code != 200:
            return {"results": [], "scanned": 0, "generated_at": int(time.time())}
        tickers = [t for t in r.json() if str(t.get("symbol", "")).endswith("USDT")]

    tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    candidates = tickers[:100]

    # Fetch klines for all symbols × all timeframes concurrently
    async with httpx.AsyncClient(timeout=30) as client:
        tasks = {
            (t["symbol"], tf): asyncio.create_task(_fetch_klines(client, t["symbol"], tf))
            for t in candidates
            for tf in TIMEFRAMES
        }
        klines_map: dict = {}
        for (sym, tf), task in tasks.items():
            klines_map[(sym, tf)] = await task
            await asyncio.sleep(0)  # yield

    # Score each symbol
    results = []
    for ticker in candidates:
        symbol     = ticker["symbol"]
        change_24h = float(ticker.get("priceChangePercent", 0))

        # Build TF data
        tf_data: dict[str, TFData] = {}
        for tf in TIMEFRAMES:
            kl = klines_map.get((symbol, tf), [])
            d  = _analyze_tf(tf, kl)
            if d:
                tf_data[tf] = d

        if not tf_data:
            continue

        # Estimate 1h change
        d1h = tf_data.get("1h")
        change_1h = 0.0
        if d1h and len(d1h.closes) >= 2:
            change_1h = (d1h.closes[-1] - d1h.closes[-2]) / (d1h.closes[-2] + 1e-10) * 100

        result = _score_symbol(symbol, tf_data, change_24h, change_1h)
        if result:
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
