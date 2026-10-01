"""Riset sinyal futures SHADOW — hipotesis entry alternatif (PLAN-OKT-2026 P1).

Agen tunggal mengejar pump (change_24h 10–15%, RSI 67–74) dan analisis
kronologis 1 Okt 2026 tak menemukan irisan fitur ber-edge. Modul ini merekam
hipotesis lain pada data yang SAMA dengan scanner (tanpa fetch tambahan) dan
menilainya maju. Nol efek keputusan: tak ada yang dibuka, tak ada yang dibaca
auto_trader/learning; tabel `futures_shadow_signals` berdiri sendiri.

Hipotesis ditetapkan SEBELUM melihat hasil (setup klasik, ambang bulat) supaya
penilaian tidak menjadi pencarian parameter atas data yang sama:

  H0 control           LONG, 1 simbol acak per scan — garis dasar drift pasar
  H1 pullback_ema      LONG, tren naik, harga kembali ke EMA20 1j, RSI 40–55, lilin hijau
  H2 squeeze_breakout  LONG/SHORT, Bollinger 1j menyempit (≤ persentil 20) lalu tembus pita + volume
  H3 dip_in_uptrend    LONG, tren 4j naik, RSI 1j < 32, close 1j naik dari sebelumnya

Bracket seragam: SL 1,5×ATR(1j), TP 3×ATR(1j) = 2R, horizon 24 jam. SL dan TP
di lilin 15m yang sama dihitung SL (konservatif). Hasil `bracket_r` sudah net
biaya round-trip `COST_PCT`.
"""

from __future__ import annotations

import json
import random
import statistics
import time

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agents.futures.utils import _atr, _ema, _rsi
from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_shadow_signal import FuturesShadowSignal

logger = structlog.get_logger(__name__)

COST_PCT = 0.30            # median cost_floor_pct ledger agen tunggal (1 Okt 2026)
SL_ATR = 1.5
TP_ATR = 3.0
HORIZON_SEC = 24 * 3600
DEDUP_SEC = 4 * 3600
CONTROL_PER_SCAN = 1      # ±700 baris/hari sebelum dedup — cukup untuk garis dasar

_last_seen: dict[tuple[str, str, str], float] = {}


# ── Deteksi ───────────────────────────────────────────────────────────────────

def _bandwidths(closes: list[float], period: int = 20) -> list[float]:
    """Lebar Bollinger (4·σ / SMA) per bar untuk jendela `period`."""
    out = []
    for i in range(period, len(closes) + 1):
        w = closes[i - period:i]
        m = sum(w) / period
        if m <= 0:
            out.append(0.0)
            continue
        out.append(4 * statistics.pstdev(w) / m)
    return out


def detect(symbol: str, tf_map: dict, change_24h: float) -> list[dict]:
    """Hipotesis yang terpicu untuk satu simbol. Murni, tanpa I/O."""
    h1, h4, m15 = tf_map.get("1h"), tf_map.get("4h"), tf_map.get("15m")
    if not h1 or not h4 or not m15 or len(h1.closes) < 120 or len(h4.closes) < 55:
        return []
    price = m15.closes[-1]
    atr1h = _atr(h1.highs, h1.lows, h1.closes, 14)
    if price <= 0 or atr1h <= 0:
        return []

    c1 = h1.closes
    ema20_1h, ema50_1h = _ema(c1, 20), _ema(c1, 50)
    ema50_4h = _ema(h4.closes, 50)
    rsi1h = _rsi(c1, 14)
    uptrend = h4.closes[-1] > ema50_4h and ema20_1h > ema50_1h
    vol_avg = sum(h1.volumes[-21:-1]) / 20 if len(h1.volumes) >= 21 else 0.0
    vol_ratio = (h1.volumes[-1] / vol_avg) if vol_avg > 0 else 0.0

    feats = {
        "rsi1h": round(rsi1h, 1),
        "atr_pct": round(atr1h / price * 100, 3),
        "change_24h": round(change_24h, 2),
        "ema20_dist_atr": round((price - ema20_1h) / atr1h, 2),
        "vol_ratio": round(vol_ratio, 2),
        "uptrend": uptrend,
    }
    hits: list[tuple[str, str]] = []

    # H1 — pullback ke EMA20 dalam tren naik, bukan entry di pucuk
    if (uptrend and abs(price - ema20_1h) <= 0.5 * atr1h
            and 40 <= rsi1h <= 55 and c1[-1] > h1.opens[-1]):
        hits.append(("pullback_ema", "LONG"))

    # H2 — squeeze lalu tembus pita dengan volume
    bws = _bandwidths(c1[-120:])
    if len(bws) >= 100 and vol_ratio >= 1.5:
        hist = sorted(bws[-100:-1])
        p20 = hist[len(hist) // 5]
        if min(bws[-6:-1]) <= p20:          # menyempit dalam 5 bar terakhir
            w = c1[-20:]
            mid = sum(w) / 20
            sd = statistics.pstdev(w)
            feats["bw_pctile_ok"] = True
            if c1[-1] > mid + 2 * sd:
                hits.append(("squeeze_breakout", "LONG"))
            elif c1[-1] < mid - 2 * sd:
                hits.append(("squeeze_breakout", "SHORT"))

    # H3 — oversold di dalam tren 4j naik
    if h4.closes[-1] > ema50_4h and rsi1h < 32 and c1[-1] > c1[-2]:
        hits.append(("dip_in_uptrend", "LONG"))

    return [_signal(h, d, symbol, price, atr1h, feats) for h, d in hits]


def _signal(hyp: str, direction: str, symbol: str, price: float, atr: float, feats: dict) -> dict:
    sign = 1 if direction == "LONG" else -1
    return {
        "hypothesis": hyp, "symbol": symbol, "direction": direction,
        "price_at_scan": price,
        "sl_price": price - sign * SL_ATR * atr,
        "tp_price": price + sign * TP_ATR * atr,
        "features": feats,
    }


async def record_shadow_signals(tickers: list[dict], tf_maps: dict, scan_ts: float) -> int:
    """Deteksi + tulis satu siklus. Fail-open: dipanggil scheduler setelah fetch."""
    if not is_db_available():
        return 0
    signals: list[dict] = []
    eligible = []
    for t in tickers:
        sym = t.get("symbol", "")
        tf_map = tf_maps.get(sym) or {}
        if not tf_map:
            continue
        try:
            found = detect(sym, tf_map, float(t.get("priceChangePercent", 0) or 0))
        except (ValueError, ZeroDivisionError, statistics.StatisticsError):
            continue
        signals.extend(found)
        h1 = tf_map.get("1h")
        if h1 and len(h1.closes) >= 20 and tf_map.get("15m"):
            eligible.append((sym, tf_map))

    for sym, tf_map in random.sample(eligible, min(CONTROL_PER_SCAN, len(eligible))):
        h1, price = tf_map["1h"], tf_map["15m"].closes[-1]
        atr = _atr(h1.highs, h1.lows, h1.closes, 14)
        if price > 0 and atr > 0:
            signals.append(_signal("control", "LONG", sym, price, atr,
                                   {"atr_pct": round(atr / price * 100, 3)}))

    rows = []
    for s in signals:
        key = (s["hypothesis"], s["symbol"], s["direction"])
        if scan_ts - _last_seen.get(key, 0.0) < DEDUP_SEC:
            continue
        _last_seen[key] = scan_ts
        rows.append({
            "signal_key": f"{s['hypothesis']}:{s['symbol']}:{s['direction']}:{int(scan_ts // DEDUP_SEC)}",
            "hypothesis": s["hypothesis"], "scan_ts": scan_ts, "symbol": s["symbol"],
            "direction": s["direction"], "price_at_scan": s["price_at_scan"],
            "sl_price": s["sl_price"], "tp_price": s["tp_price"], "cost_pct": COST_PCT,
            "features_json": json.dumps(s["features"]), "outcome_status": "pending",
        })
    if not rows:
        return 0
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            pg_insert(FuturesShadowSignal).values(rows).on_conflict_do_nothing(
                index_elements=["signal_key"]))
        await session.commit()
    n = res.rowcount if res.rowcount and res.rowcount > 0 else 0
    if n:
        by: dict[str, int] = {}
        for r in rows:
            by[r["hypothesis"]] = by.get(r["hypothesis"], 0) + 1
        logger.info("futures_shadow_signals_logged", rows=n, by_hypothesis=by)
    return n


# ── Penilaian maju ────────────────────────────────────────────────────────────

def simulate_bracket(direction: str, entry: float, sl: float, tp: float, cost_pct: float,
                     klines: list, scan_ts: float, now: float) -> dict | None:
    """SL/TP pertama yang tersentuh pada lilin 15m SESUDAH scan. None = belum final."""
    risk = abs(entry - sl)
    if entry <= 0 or risk <= 0:
        return None
    long_ = direction == "LONG"
    end_ms = (scan_ts + HORIZON_SEC) * 1000
    last_close = None
    for k in klines:
        open_ms = float(k[0])
        if open_ms < scan_ts * 1000:
            continue                        # lilin yang memuat scan sebagian sebelum entry
        if open_ms >= end_ms:
            break
        hi, lo, cl = float(k[2]), float(k[3]), float(k[4])
        last_close = cl
        hit_sl = lo <= sl if long_ else hi >= sl
        hit_tp = hi >= tp if long_ else lo <= tp
        if hit_sl or hit_tp:
            exit_px, why = (sl, "sl") if hit_sl else (tp, "tp")   # dua-duanya → SL
            return _result(why, exit_px, entry, risk, long_, cost_pct, (open_ms / 1000 - scan_ts) / 60 + 15)
    if scan_ts + HORIZON_SEC > now or last_close is None:
        return None
    return _result("open", last_close, entry, risk, long_, cost_pct, HORIZON_SEC / 60)


def _result(why: str, exit_px: float, entry: float, risk: float, long_: bool,
            cost_pct: float, hold_min: float) -> dict:
    gross = (exit_px - entry) if long_ else (entry - exit_px)
    cost_r = (cost_pct / 100 * entry) / risk
    return {"bracket_exit": why, "bracket_r": round(gross / risk - cost_r, 4),
            "bracket_hold_min": round(hold_min, 1)}


async def update_shadow_outcomes(max_symbols: int = 60) -> int:
    """Isi pnl 1j/4j/24j + hasil bracket untuk baris pending yang sudah bisa dinilai."""
    if not is_db_available():
        return 0
    from agents.futures.outcome_tracker import _fetch_klines_15m, compute_forward_labels
    now = time.time()
    updated = 0
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(FuturesShadowSignal).where(
                FuturesShadowSignal.outcome_status == "pending",
                FuturesShadowSignal.scan_ts <= now - 3600,
            ).order_by(FuturesShadowSignal.scan_ts.asc()).limit(400)
        )).scalars().all())
        by_symbol: dict[str, list[FuturesShadowSignal]] = {}
        for r in rows:
            by_symbol.setdefault(r.symbol, []).append(r)
        async with httpx.AsyncClient(timeout=15) as client:
            for symbol in list(by_symbol)[:max_symbols]:
                sym_rows = by_symbol[symbol]
                klines = await _fetch_klines_15m(client, symbol, min(r.scan_ts for r in sym_rows))
                if not klines:
                    for r in sym_rows:
                        if r.scan_ts < now - 26 * 3600:
                            r.outcome_status, r.outcome_updated_at = "failed", now
                            updated += 1
                    continue
                for r in sym_rows:
                    labels = compute_forward_labels(r.direction, r.price_at_scan, klines, r.scan_ts, now=now)
                    for col in ("pnl_1h_pct", "pnl_4h_pct", "pnl_24h_pct"):
                        if col in labels and getattr(r, col) is None:
                            setattr(r, col, labels[col])
                    if r.bracket_exit is None:
                        res = simulate_bracket(r.direction, r.price_at_scan, r.sl_price, r.tp_price,
                                               r.cost_pct, klines, r.scan_ts, now)
                        if res:
                            for k, v in res.items():
                                setattr(r, k, v)
                    if r.bracket_exit is not None and r.pnl_24h_pct is not None:
                        r.outcome_status = "labelled"
                    r.outcome_updated_at = now
                    updated += 1
        if updated:
            await session.commit()
    if updated:
        logger.info("futures_shadow_outcomes_updated", rows=updated)
    return updated
