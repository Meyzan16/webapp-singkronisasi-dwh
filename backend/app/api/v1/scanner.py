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
CACHE_TTL = 300  # 5 min


# ── Style configs ──────────────────────────────────────────────────────────────

@dataclass
class StyleConfig:
    timeframe: str
    candle_limit: int
    rsi_period: int
    bb_period: int
    lookback: int       # recent high/low window
    squeeze_threshold: float   # BB width % trigger
    vol_slope_min: float       # vol accumulation min slope
    atr_sl_mult: float         # SL = ATR × this
    atr_tp_mult: float         # TP = ATR × this
    min_score: float
    pump_penalty_pct: float    # penalize if already moved this much %
    # Signal weights multipliers
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
        squeeze_threshold=0.03,   # tighter squeeze trigger
        vol_slope_min=0.20,
        atr_sl_mult=1.0, atr_tp_mult=2.5,
        min_score=25,
        pump_penalty_pct=5,        # penalize already +5% on 15m
        w_squeeze=1.0, w_accumulation=0.7, w_breakout=1.5,
        w_rsi=2.0,     w_ema=1.2,  w_pressure=1.8, w_candle=1.5,
    ),
    "daytrading": StyleConfig(
        timeframe="1h", candle_limit=100,
        rsi_period=14, bb_period=20, lookback=15,
        squeeze_threshold=0.045,
        vol_slope_min=0.25,
        atr_sl_mult=1.2, atr_tp_mult=3.0,
        min_score=28,
        pump_penalty_pct=8,
        w_squeeze=1.2, w_accumulation=1.2, w_breakout=1.3,
        w_rsi=1.5,     w_ema=1.3,  w_pressure=1.5, w_candle=1.2,
    ),
    "swing": StyleConfig(
        timeframe="4h", candle_limit=100,
        rsi_period=14, bb_period=20, lookback=20,
        squeeze_threshold=0.06,
        vol_slope_min=0.30,
        atr_sl_mult=1.5, atr_tp_mult=4.5,
        min_score=30,
        pump_penalty_pct=12,
        w_squeeze=1.8, w_accumulation=2.0, w_breakout=1.5,
        w_rsi=1.0,     w_ema=1.0,  w_pressure=1.2, w_candle=0.8,
    ),
    "position": StyleConfig(
        timeframe="1d", candle_limit=120,
        rsi_period=21, bb_period=30, lookback=50,
        squeeze_threshold=0.08,
        vol_slope_min=0.40,
        atr_sl_mult=2.0, atr_tp_mult=7.0,
        min_score=35,
        pump_penalty_pct=20,
        w_squeeze=2.0, w_accumulation=2.5, w_breakout=1.8,
        w_rsi=0.8,     w_ema=1.5,  w_pressure=1.0, w_candle=0.5,
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
    change_24h: float
    volume_ratio: float
    signals: list[str]
    key_level: float | None
    stop_loss: float
    take_profit: float
    risk_reward: str
    alert_type: str
    style_note: str      # e.g. "Swing setup | 4H candle | SL×1.5 ATR"


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

    # ── SL / TP ────────────────────────────────────────────────────────────────
    atr = _atr(highs, lows, closes)
    if direction == "LONG":
        sl = price - atr * cfg.atr_sl_mult
        tp = price + atr * cfg.atr_tp_mult
        key_level = recent_high
    else:
        sl = price + atr * cfg.atr_sl_mult
        tp = price - atr * cfg.atr_tp_mult
        key_level = recent_low

    risk = abs(price - sl)
    reward = abs(tp - price)
    rr = f"1:{reward/risk:.1f}" if risk > 0 else "1:3.0"

    info = STYLE_LABELS[style]
    style_note = f"{info['label']} | {info['tf']} candle | SL ×{cfg.atr_sl_mult} ATR"

    return ScanSignal(
        symbol=symbol,
        direction=direction,
        probability=round(min(score, 99), 1),
        current_price=round(price, 8),
        change_24h=round(change_24h, 2),
        volume_ratio=round(vol_ratio, 2),
        signals=[s for s in signals if not s.startswith("⚠️")][:4],
        key_level=round(key_level, 8),
        stop_loss=round(sl, 8),
        take_profit=round(tp, 8),
        risk_reward=rr,
        alert_type=alert_type,
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


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/scanner/scan", response_model=ScannerResponse)
async def scan_market(
    style: str = Query(default="swing", description="scalping | daytrading | swing | position"),
) -> ScannerResponse:
    """
    Scan 100 most-active USDT futures for early breakout setups.
    Each trading style uses different timeframe, scoring weights, and SL/TP sizing.
    """
    style = style.lower()
    if style not in STYLE_CONFIGS:
        style = "swing"

    cache_key = style
    now = int(time.time())
    if cache_key in _cache and now - _cache[cache_key].get("ts", 0) < CACHE_TTL:
        return _cache[cache_key]["data"]

    cfg = STYLE_CONFIGS[style]
    info = STYLE_LABELS[style]

    # Fetch all tickers
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(fapi("/fapi/v1/ticker/24hr"))
        if r.status_code != 200:
            return ScannerResponse(results=[], scanned=0, style=style,
                                   style_label=info["label"], timeframe=info["tf"], generated_at=now)
        tickers = [t for t in r.json() if str(t.get("symbol", "")).endswith("USDT")]

    tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    candidates = tickers[:100]

    # Fetch klines concurrently
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

            sig = _analyze(ticker["symbol"], opens, highs, lows, closes, vols, change, cfg, style)
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
    _cache[cache_key] = {"data": response, "ts": now}
    logger.info("scanner_done", style=style, tf=cfg.timeframe, found=len(results))
    return response
