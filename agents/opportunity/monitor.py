"""
Opportunity Monitor — Risk-Adjusted Return (SPOT).

Runs every 60s. For each open opportunity_spot trade:

  Layer 0 — Wick detection (1m klines since last check):
    - 1m low  ≤ SL → SL touched (real limit/stop WOULD have filled)
    - 1m high ≥ TP → TP touched
    - Both touched in same window → SL wins (conservative)

  Layer 1 — Hard exits:
    - SL touched → close "sl" (with slippage; "tp1_breakeven" label if TP1 was hit)
    - TP3/TP2 touched → close "tp"
    - TP1 touched → PARTIAL SELL 50% (profit locked), SL → entry + 50% of TP1 gain

  Layer 2 — Risk-adjusted closes (only after scfg.MIN_HOLD_MINUTES):
    - Profit-protecting exits (trend_reversal / profit_protection / flow_reversal)
      only fire when pnl_net ≥ 50% of the distance to TP2 — never clip small
      winners (§12.2: scanner demands 1:3.5 asymmetry, monitor must not destroy it)
    - "risk_adjusted" loss-cutter (RSI>75 + loss>2%) still fires — cutting losses
      early is good for expectancy

  Layer 3 — Max age: fresh_setup=10d, momentum_chase=5d → close at market, label "max_age_expired"
            (excluded from learning)

All P&L is net of EXECUTION_COST_PCT (fee+spread+slippage, §15.1).
Known/intended limitations: 60s polling (wick layer compensates);
pnl_pct stored is NET of execution costs.
"""

import asyncio
import json
import time
from typing import Optional

import httpx
import structlog
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_balance import PaperBalance
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import spot
from app.services.trading_costs import EXECUTION_COST_PCT, SL_SLIPPAGE_PCT
#: SEMUA ambang keputusan keluar dibaca lewat `scfg.X` — bukan disalin ke
#: konstanta lokal. Sebelum 8 Agu 2026 monitor ini punya NOL titik baca config,
#: sehingga hasil belajar sisi keluar SPOT tak punya jalan untuk sampai ke sini.
from agents.opportunity import monitor_config as scfg

logger = structlog.get_logger(__name__)

INTERVAL_SEC       = 60
STARTUP_DELAY      = 45

# G5b: absolute profit lock tiers — same as futures monitor
# PLAN_v10 P3 — tiers ordered HIGHEST peak first so the tightest applicable
# lock wins (loop returns on first match). Big runners (100%+, 300%+) give back
# very little before locking, so a 1000% move can't evaporate.
_PROFIT_LOCK_TIERS_SPOT = [
    (300.0, 0.90),
    (100.0, 0.85),
    (40.0, 0.75),
    (25.0, 0.70),
    (15.0, 0.60),
]

# G5: dynamic TP extension thresholds
G5_MIN_SCORE      = 75
G5_MIN_VOL_RATIO  = 1.5

# ── PLAN_v10 — dynamic profit ladder + ratcheting trail ──────────────────────
# Scale out a small slice at each rung (banked = permanent), keep a runner that
# rides while the "still-strong" gate (flow + TA) stays green. Rungs TP4..TP-n
# are born dynamically as price climbs — no cap, ride the whole move.
LADDER_FRAC_TP1     = 0.30    # jual 30% di TP1 (dulu 50%) — sisakan runner besar
LADDER_FRAC_TP2     = 0.20    # jual 20% di TP2 (dulu tutup 100% — INI cap lama)
LADDER_FRAC_TP3     = 0.15    # jual 15% di TP3, sisanya jadi runner trailing
DYN_RUNG_FRAC       = 0.05    # jual 5% tiap rung dinamis TP4..n
RUNNER_MIN_FRACTION = 0.15    # jangan pernah jual runner di bawah ini via rung dinamis
# BM7: per entry_mode — accumulation needs more time, failed momentum exits faster
# PLAN_SPOT_LANES B-Fix 3: BigMover mengejar gelombang yang sedang berjalan — kalau
# 3 hari belum resolve, gelombangnya sudah lewat. Sebelumnya lane ini diam-diam
# mewarisi 10 hari milik akumulasi karena monitor tidak mengenal entry_mode-nya.
WICK_LOOKBACK_MIN  = 3            # 1m candles checked per cycle (covers restarts)
WEIGHT_UPDATE_SEC  = 30 * 60      # time-based (§1.12), not cycle-based

# Stagnant rotation — free capital from idle positions when better momentum exists
# PLAN_SPOT_LANES B-Fix 4: lantai P&L bersih agar rotasi (stagnant MAUPUN urgent)
# tidak membukukan kerugian hanya karena ada kandidat lebih menarik.

_running      = False
_cycle_count  = 0
_last_check:  Optional[float] = None
_last_error:  Optional[str]   = None
_last_weight_run: float       = 0.0

# Short price history per symbol for stall detection (pruned to open symbols)
_price_history: dict[str, list[float]] = {}


def get_state() -> dict:
    return {
        "running":     _running,
        "cycle_count": _cycle_count,
        "last_check":  _last_check,
        "last_error":  _last_error,
    }


# ── Stagnant rotation helper ─────────────────────────────────────────────────

# PLAN_v8 P4: rotation must not fire on a STALE scan. If the last scan is older
# than this (scan failed / agent stalled / Binance down), rotating a position based
# on ghost candidates would force-close a live trade on outdated evidence.
ROTATION_MAX_STALE_SEC = 10 * 60   # scan cache older than 10 min → do not rotate


def lane_of(meta: dict, alert_type: str | None) -> str:
    """
    Lane trade ini — identitas TETAP, berbeda dari `entry_mode` yang dimutasi
    monitor jadi "momentum_chase" begitu TP2/TP3 tersentuh.

    Sumber utama: `meta["lane"]` yang ditulis scheduler saat auto-open. Untuk
    trade lama (dan open manual) turunkan dari `alert_type`, yang tidak pernah
    diubah siapa pun — pemetaannya sama persis dengan `laneForSpot` di frontend.
    """
    lane = str(meta.get("lane") or "").strip().lower()
    if lane:
        return lane
    a = (alert_type or "").lower()
    if "bigmover" in a:
        return "bigmover"
    if "early" in a:
        return "early_radar"
    if "breakout" in a:
        return "breakout"
    return "accumulation"


def _has_better_candidate(
    current_score: float,
    exclude_symbol: str,
    # JANGAN memakai `scfg.X` sebagai nilai default argumen: Python mengevaluasi
    # default SEKALI saat impor, jadi nilainya membeku dan tak pernah ikut
    # `refresh()` — menala dari DB akan terlihat tak berpengaruh, persis penyakit
    # yang lapisan ini dibuat untuk menyembuhkan. `None` = pakai nilai saat DIPANGGIL.
    min_gap: float | None = None,
    min_score: float = 85,
) -> bool:
    """
    True if the latest scan cache has an auto-open candidate with materially
    higher score than the stagnant position being considered for rotation.
    Requires: candidate.score >= current_score + min_gap AND >= min_score.
    PLAN_v8 P4: refuses to signal on a stale scan cache (fail-safe = no rotation).
    """
    if min_gap is None:
        min_gap = scfg.STAGNANT_SCORE_GAP
    from agents.opportunity import store as opp_store
    cached = opp_store.get_result()
    if not cached:
        return False
    # P4: staleness guard — never rotate based on an outdated scan.
    gen_at = cached.get("generated_at") or 0
    if gen_at and (time.time() - gen_at) > ROTATION_MAX_STALE_SEC:
        logger.debug("rotation_skip_stale_scan",
                     age_sec=round(time.time() - gen_at), exclude=exclude_symbol)
        return False
    for c in cached.get("results", []):
        if c.get("symbol") == exclude_symbol:
            continue
        c_score = c.get("raw_score") or c.get("opportunity_score") or 0
        if c.get("auto_open") and c_score >= min_score and c_score >= current_score + min_gap:
            return True
    return False


# ── Math helpers ─────────────────────────────────────────────────────────────

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


def _taker_ratio(klines: list, last_n: int = 10) -> float:
    ratios = []
    for k in klines[-last_n:]:
        try:
            total = float(k[5]); buy = float(k[9])
            if total > 0:
                ratios.append(buy / total)
        except (IndexError, ValueError):
            pass
    return sum(ratios) / len(ratios) if ratios else 0.5


# ── Network fetchers (no DB session held — §1.10) ────────────────────────────

async def _fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Batch ticker fetch. Compact JSON separators — Binance rejects spaces (§1.8)."""
    if not symbols:
        return {}
    prices: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            syms_param = json.dumps(symbols, separators=(",", ":"))
            r = await client.get(spot("/api/v3/ticker/price"), params={"symbols": syms_param})
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        prices[item["symbol"]] = float(item["price"])
                    return prices
            logger.warning("monitor_batch_ticker_failed", status=r.status_code)
            # Fallback: per-symbol (should be rare now)
            sem = asyncio.Semaphore(10)

            async def _one(sym: str) -> None:
                async with sem:
                    try:
                        resp = await client.get(spot(f"/api/v3/ticker/price?symbol={sym}"))
                        if resp.status_code == 200:
                            prices[sym] = float(resp.json()["price"])
                    except Exception:
                        pass

            await asyncio.gather(*[_one(s) for s in symbols])
    except Exception as exc:
        logger.warning("monitor_price_fetch_error", error=str(exc)[:80])
    return prices


async def _fetch_klines_1h(client: httpx.AsyncClient, symbol: str) -> list:
    try:
        r = await client.get(spot(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30"))
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


async def _fetch_klines_1m(client: httpx.AsyncClient, symbol: str) -> list:
    """Last few 1m candles — wick detection for TP/SL touches between polls (§12.3)."""
    try:
        r = await client.get(
            spot(f"/api/v3/klines?symbol={symbol}&interval=1m&limit={WICK_LOOKBACK_MIN}")
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


async def _fetch_klines_4h(client: httpx.AsyncClient, symbol: str, limit: int = 60) -> list:
    """4h candles — used for trailing-structure-stop in momentum_chase trades."""
    try:
        r = await client.get(
            spot(f"/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}")
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def _compute_trailing_sl(klines_4h: list, current_sl: float) -> float:
    """
    Ratchet trailing stop for momentum_chase trades post-TP1.
    Candidate = max(EMA21(4h)*0.99, swing_low_10_candles(4h)*0.99).
    Only ever moves UP — never returns below current_sl.
    """
    if len(klines_4h) < 22:
        return current_sl
    closes    = [float(k[4]) for k in klines_4h]
    lows      = [float(k[3]) for k in klines_4h]
    ema21     = _ema(closes, 21)
    swing_low = min(lows[-10:])
    candidate = max(ema21 * 0.99, swing_low * 0.99)
    return max(current_sl, candidate)


def describe_monitor_state(
    entry:         float,
    meta:          dict,
    stop_loss:     float,
    take_profit:   float,
    entry_at:      float | None,
    current_price: float | None,
    alert_type:    str | None = None,
) -> dict:
    """
    Read-only snapshot of what THIS monitor will do to an open trade right now.

    Pure display helper (no I/O, no mutation) so the API can show the same
    numbers the monitor acts on: live SL after trailing/breakeven/ladder floor,
    the next rung it is hunting, the profit-lock give-back level, and the age
    budget. Everything here mirrors `_check_trade` above — keep them in sync.
    """
    sl   = meta.get("current_sl") or stop_loss or 0.0
    tp1  = meta.get("tp1") or None
    tp2  = meta.get("tp2") or take_profit or None
    tp3  = meta.get("tp3") or None
    mode = meta.get("entry_mode", "fresh_setup")
    lane = lane_of(meta, alert_type)

    def _pct(level: float | None) -> float | None:
        if not level or not entry or entry <= 0:
            return None
        return round((level - entry) / entry * 100, 2)

    # ── live SL + why it sits where it sits ─────────────────────────────────
    risk_pct    = float(meta.get("risk_pct", 0) or 0)
    sl_original = entry * (1 - risk_pct / 100) if (entry and risk_pct > 0) else stop_loss
    sl_moved    = bool(sl and sl_original and sl > sl_original * 1.0001)
    if not sl_moved:
        sl_source = "awal"
    elif meta.get("breakeven_set"):
        sl_source = "breakeven"
    elif (mode == "momentum_chase" or lane == "bigmover") and meta.get("tp1_hit"):
        sl_source = "trailing 4h"
    elif meta.get("ladder"):
        sl_source = "lantai ladder"
    else:
        sl_source = "dinaikkan"

    # ── phase: what the monitor is currently doing ──────────────────────────
    tp1_hit  = bool(meta.get("tp1_hit"))
    is_runner = mode == "momentum_chase" and tp1_hit
    if is_runner:
        phase = "Runner — trailing struktur 4h"
    elif tp1_hit and lane == "bigmover":
        # B-Fix 3: sisa posisi BigMover kini dijaga trailing 4h sambil menuju TP2.
        phase = "TP1 kena — sisa dijaga trailing 4h"
    elif tp1_hit:
        phase = "TP1 kena — sisa posisi jalan ke TP2"
    elif meta.get("breakeven_set"):
        phase = "SL sudah di breakeven — menunggu TP1"
    else:
        phase = "Menunggu TP1"

    # ── next rung the monitor hunts ─────────────────────────────────────────
    ladder_done = {r.get("rung") for r in (meta.get("ladder") or [])}
    next_target: dict | None = None
    for name, price, frac in (
        ("TP1", tp1, LADDER_FRAC_TP1),
        ("TP2", tp2, LADDER_FRAC_TP2),
        ("TP3", tp3, LADDER_FRAC_TP3),
    ):
        if price and name.lower() not in ladder_done and not (name == "TP1" and tp1_hit):
            next_target = {"name": name, "price": price, "pct": _pct(price),
                           "sell_fraction": frac}
            break
    if next_target is None and is_runner:
        last_rung = meta.get("last_rung_price") or tp3 or tp2
        next_target = {"name": "rung dinamis", "price": last_rung, "pct": _pct(last_rung),
                       "sell_fraction": DYN_RUNG_FRAC}

    # ── absolute profit lock: at what P&L does the monitor bank the runner? ─
    peak_pnl     = float(meta.get("peak_pnl_pct", 0.0) or 0.0)
    lock_at_pct  = None
    for tier_peak, keep in _PROFIT_LOCK_TIERS_SPOT:
        if peak_pnl >= tier_peak:
            lock_at_pct = round(peak_pnl * keep, 2)
            break

    # ── age budget ─────────────────────────────────────────────────────────
    max_age = (
        0.25 if mode == "momentum_entry"
        else scfg.MAX_AGE_DAYS_BIGMOVER if lane == "bigmover"
        else scfg.MAX_AGE_DAYS_MOMENTUM_CHASE if mode == "momentum_chase"
        else scfg.MAX_AGE_DAYS_FRESH_SETUP
    )
    age_days = (
        round((time.time() - entry_at) / 86400, 2)
        if entry_at and entry_at > 1_000_000_000 else None
    )

    # distance from live price to the two things that can close the trade now
    to_sl_pct = (
        round((sl - current_price) / current_price * 100, 2)
        if current_price and sl else None
    )
    to_target_pct = (
        round((next_target["price"] - current_price) / current_price * 100, 2)
        if current_price and next_target and next_target.get("price") else None
    )

    return {
        "lane":           lane,
        "phase":          phase,
        "sl_live":        sl,
        "sl_pct":         _pct(sl),
        "sl_source":      sl_source,
        "sl_moved":       sl_moved,
        "to_sl_pct":      to_sl_pct,
        "next_target":    next_target,
        "to_target_pct":  to_target_pct,
        "peak_pnl_pct":   round(peak_pnl, 2),
        "lock_at_pct":    lock_at_pct,
        "age_days":       age_days,
        "max_age_days":   max_age,
        "check_every_sec": INTERVAL_SEC,
    }


def _atr(klines: list, n: int = 14) -> float:
    """PLAN_v10 — Average True Range over last n candles (0.0 if insufficient)."""
    if len(klines) < n + 1:
        return 0.0
    trs = []
    for i in range(len(klines) - n, len(klines)):
        high = float(klines[i][2]); low = float(klines[i][3])
        prev_close = float(klines[i - 1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def _still_strong_gate(symbol: str, klines_1h: list) -> tuple[bool, str]:
    """
    PLAN_v10 — "masih kuat?" gate untuk memutuskan runner terus ride & rung baru
    lahir. Pakai flow (taker ratio, volume) + TA (skor live). Hijau = lanjut,
    merah = berhenti buat rung baru, biar trailing SL yang urus exit.
    """
    score = _get_current_spot_score(symbol)
    if score < scfg.GATE_MIN_SCORE:
        return False, f"score {score:.0f}<{scfg.GATE_MIN_SCORE}"
    if klines_1h:
        taker = _taker_ratio(klines_1h)
        if taker < scfg.GATE_MIN_TAKER:
            return False, f"taker {taker:.2f}"
        vr = _vol_ratio([float(k[5]) for k in klines_1h])
        if vr < scfg.GATE_MIN_VOL_RATIO:
            return False, f"vol {vr:.2f}"
    return True, "strong"


def _wick_extremes(klines_1m: list, entry_at: float) -> tuple[Optional[float], Optional[float]]:
    """(low, high) across 1m candles that closed after entry. None if no data."""
    lows, highs = [], []
    for k in klines_1m:
        try:
            open_ms = float(k[0])
            if open_ms / 1000 < entry_at - 60:
                continue  # candle predates the position
            lows.append(float(k[3]))
            highs.append(float(k[2]))
        except (IndexError, ValueError):
            continue
    if not lows:
        return None, None
    return min(lows), max(highs)


def _vol_ratio(volumes: list[float]) -> float:
    """Current vol / avg of prior candles. Returns 1.0 if insufficient data."""
    if len(volumes) < 2:
        return 1.0
    avg = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    return volumes[-1] / avg if avg > 0 else 1.0


def _get_current_spot_score(symbol: str) -> float:
    """G5: lookup latest scanner score from opportunity cache."""
    try:
        from agents.opportunity import store as opp_store
        cached = opp_store.get_result()
        if cached:
            for c in cached.get("results", []):
                if c.get("symbol") == symbol:
                    return float(c.get("raw_score") or c.get("opportunity_score") or 0)
    except Exception:
        pass
    return 0.0


# ── Risk-adjusted exit signals ───────────────────────────────────────────────

def _risk_signal(
    klines:            list,
    entry_price:       float,
    current_price:     float,
    symbol:            str,
    entry_ema_bullish: bool,
    hold_minutes:      float,
    tp2_net_pct:       float,
) -> Optional[str]:
    """
    Risk-adjusted close conditions.
    BM2: trend_reversal (EMA cross) fires without profit floor — it's a structure
    signal, not a profit-protection exit. Guard: ≥60 min hold to avoid noise.
    profit_protection and flow_reversal still require pnl_net ≥ 50% of TP2 (§12.2).
    Loss-cutting "risk_adjusted" keeps firing early.
    """
    if hold_minutes < scfg.MIN_HOLD_MINUTES or len(klines) < 15:
        return None

    closes = [float(k[4]) for k in klines]
    ema9   = _ema(closes, 9)
    ema21  = _ema(closes, 21)
    rsi    = _rsi(closes, 14)
    taker  = _taker_ratio(klines)
    pnl_gross = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
    pnl_net   = pnl_gross - EXECUTION_COST_PCT

    profit_floor = max(0.5 * tp2_net_pct, EXECUTION_COST_PCT * 2)

    # BM2: trend_reversal is a STRUCTURE signal — EMA cross bearish means the
    # setup that justified the entry is broken. No profit floor: we don't wait
    # for the position to be profitable before exiting a broken structure.
    # Guard: only fire after ≥60 min hold (not on normal open-candle noise).
    if entry_ema_bullish and ema9 < ema21 * 0.998 and hold_minutes >= 60:
        return "trend_reversal"

    if rsi > 80 and pnl_net >= profit_floor:
        hist = _price_history.get(symbol, [])
        if len(hist) >= 3:
            base = min(hist[-3:])
            recent_range = (max(hist[-3:]) - min(hist[-3:])) / base if base > 0 else 1
            if recent_range < 0.005:
                return "profit_protection"

    if taker < 0.38 and pnl_net >= profit_floor:
        return "flow_reversal"

    # Loss cutter — overbought reading while deep red = structure broken
    if rsi > 75 and pnl_gross < -2:
        return "risk_adjusted"

    return None


def _parse_trade_meta(trade: PaperTrade) -> dict:
    try:
        meta = json.loads(trade.signals_json or "{}")
        if isinstance(meta, dict):
            return meta
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _final_pnl(
    entry: float, close_price: float, position_size: float, meta: dict,
) -> tuple[float, float]:
    """
    (pnl_pct_net_blended, pnl_dollar_total) honoring TP1 partial sell (§15.3).
    Remaining fraction rides to close; partial profit was locked at TP1.
    """
    pnl_net_pct = (close_price - entry) / entry * 100 - EXECUTION_COST_PCT
    remaining   = meta.get("remaining_fraction", 1.0)
    # PLAN_v10 — banked_dollar akumulasi SEMUA rung scale-out (permanen).
    # Fallback ke tp1_partial_dollar untuk trade lama sebelum ladder multi-partial.
    partial_dlr = meta.get("banked_dollar")
    if partial_dlr is None:
        partial_dlr = meta.get("tp1_partial_dollar", 0.0)
    final_dlr   = (pnl_net_pct / 100) * position_size * remaining + partial_dlr
    blended_pct = (final_dlr / position_size * 100) if position_size > 0 else pnl_net_pct
    return round(blended_pct, 2), round(final_dlr, 2)


# ── Core loop ────────────────────────────────────────────────────────────────

async def check_positions() -> int:
    """Monitor all open spot positions. Returns count of closes + updates."""
    if not is_db_available():
        return 0

    # Session 1: read open trades, release connection before network I/O (§1.10)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style  == "opportunity_spot",
                PaperTrade.status == "open",
            )
        )
        trades = list(result.scalars().all())
        for t in trades:
            session.expunge(t)

    if not trades:
        _price_history.clear()
        return 0

    symbols = list({t.symbol for t in trades})

    # Network phase — no DB session held
    prices = await _fetch_prices(symbols)
    klines_1h: dict[str, list] = {}
    klines_1m: dict[str, list] = {}
    klines_4h: dict[str, list] = {}
    async with httpx.AsyncClient(timeout=15) as client:
        tasks_1h = {s: asyncio.create_task(_fetch_klines_1h(client, s)) for s in symbols}
        tasks_1m = {s: asyncio.create_task(_fetch_klines_1m(client, s)) for s in symbols}
        tasks_4h = {s: asyncio.create_task(_fetch_klines_4h(client, s)) for s in symbols}
        for s in symbols:
            try:
                klines_1h[s] = await tasks_1h[s]
            except Exception:
                klines_1h[s] = []
            try:
                klines_1m[s] = await tasks_1m[s]
            except Exception:
                klines_1m[s] = []
            try:
                klines_4h[s] = await tasks_4h[s]
            except Exception:
                klines_4h[s] = []

    # Prune price history to open symbols only (§1.6)
    for stale in [s for s in _price_history if s not in symbols]:
        _price_history.pop(stale, None)

    closed = 0
    updated = 0

    # Session 2: apply decisions, per-trade isolation (§1.7), race-safe (§1.14)
    async with AsyncSessionLocal() as session:
        for snapshot in trades:
            try:
                n_closed, n_updated = await _process_trade(
                    session, snapshot,
                    prices.get(snapshot.symbol),
                    klines_1h.get(snapshot.symbol, []),
                    klines_1m.get(snapshot.symbol, []),
                    klines_4h.get(snapshot.symbol, []),
                )
                closed  += n_closed
                updated += n_updated
            except Exception as exc:
                logger.error("monitor_trade_error",
                             symbol=snapshot.symbol, id=snapshot.id,
                             error=str(exc)[:100])
        if closed > 0 or updated > 0:
            await session.commit()

    if closed > 0:
        await _update_paper_balance()

    return closed + updated


async def _process_trade(
    session,
    snapshot: PaperTrade,
    price: Optional[float],
    k1h: list,
    k1m: list,
    k4h: list,
) -> tuple[int, int]:
    """Evaluate one position. Returns (closed, updated) as 0/1 each."""
    if price is None:
        return 0, 0

    # Race guard (§1.14): re-fetch fresh row, skip if no longer open
    result = await session.execute(
        select(PaperTrade).where(
            PaperTrade.id     == snapshot.id,
            PaperTrade.status == "open",
        )
    )
    trade = result.scalar_one_or_none()
    if trade is None:
        return 0, 0

    hist = _price_history.setdefault(trade.symbol, [])
    hist.append(price)
    if len(hist) > 10:
        hist.pop(0)

    meta  = _parse_trade_meta(trade)
    tp1   = meta.get("tp1") or None
    tp2   = meta.get("tp2") or trade.take_profit          # §1.3: `or`, not default
    tp3   = meta.get("tp3") or None
    sl    = meta.get("current_sl") or trade.stop_loss
    entry = trade.entry_price

    # Batas TP hasil belajar per lane. Kompresi HANYA mendekatkan target — tak
    # pernah menjauhkannya — dan default MATI, jadi tanpa saklar + angka per-lane
    # perilakunya identik seperti sebelumnya.
    #
    # Panggilan ini WAJIB ada di sini: nilai canary sempat sampai ke
    # `tp_atr_limit()` tapi tak seorang pun memanggil kompresinya, sehingga
    # angka hasil belajar tersimpan rapi dan berefek NOL — persis penyakit yang
    # di sisi futures butuh M2 untuk ditutup.
    try:
        _lane_tp = lane_of(meta, trade.alert_type)
        _atr_now = float(meta.get("atr_pct") or 0.0)
        _tp2_eff, _tp2_kompres = scfg.effective_take_profit(
            float(entry or 0.0), float(tp2 or 0.0), _atr_now, lane=_lane_tp)
        if _tp2_kompres:
            tp2 = _tp2_eff
            meta["tp_compressed"] = True
            # TP3 di atas TP2 jadi tak masuk akal setelah TP2 didekatkan.
            if tp3 and tp3 > tp2:
                tp3 = None
    except Exception as exc:      # pencatatan opsional — jangan ganggu monitor
        logger.warning("spot_tp_compress_failed", symbol=trade.symbol,
                       error=str(exc)[:100])

    if not entry or entry <= 0 or not sl or sl <= 0 or not tp2 or tp2 <= 0:
        logger.warning("monitor_invalid_levels", id=trade.id, symbol=trade.symbol)
        return 0, 0

    # ── Trailing SL ratchet post-TP1 ────────────────────────────────────────
    # Runs every cycle to ratchet the SL up as price climbs. Only moves UP.
    # B-Fix 3: gate-nya kini lane + entry_mode. Sebelumnya HANYA entry_mode ==
    # "momentum_chase", sehingga lane BigMover — yang seluruh tesisnya "ride the
    # wave" — tak pernah trailing di TP1 dan sisa 70% posisinya jatuh kembali ke
    # SL awal. Itu penyebab avg loss (−$11.33) > avg win (+$10.11) di lane itu.
    _lane             = lane_of(meta, trade.alert_type)
    _entry_mode_early = meta.get("entry_mode", "fresh_setup")
    is_momentum_chase = _entry_mode_early == "momentum_chase"
    is_momentum_entry = _entry_mode_early == "momentum_entry"
    trails_after_tp1  = is_momentum_chase or _lane == "bigmover"

    if trails_after_tp1 and meta.get("tp1_hit") and len(k4h) >= 22:
        new_trail = _compute_trailing_sl(k4h, sl)
        if new_trail > sl:
            sl = new_trail
            meta["current_sl"] = round(sl, 8)
            trade.stop_loss    = round(sl, 8)
            trade.signals_json = json.dumps(meta, ensure_ascii=False)

    # B6: momentum_entry — move SL to breakeven after +3% gain
    if is_momentum_entry and not meta.get("breakeven_set") and entry > 0:
        pnl_now_pct = (price - entry) / entry * 100
        if pnl_now_pct >= 3.0:
            new_sl_be = entry * 1.001   # 0.1% buffer above entry
            if new_sl_be > sl:
                sl = new_sl_be
                meta["current_sl"] = round(sl, 8)
                meta["breakeven_set"] = True
                trade.stop_loss    = round(sl, 8)
                trade.signals_json = json.dumps(meta, ensure_ascii=False)
                logger.info("momentum_entry_breakeven_set", symbol=trade.symbol,
                            pnl_pct=round(pnl_now_pct, 2), new_sl=round(sl, 8))

    # Wick extremes since entry (§12.3) — fall back to spot price only
    wick_low, wick_high = _wick_extremes(k1m, trade.entry_at or time.time())
    eff_low  = min(price, wick_low)  if wick_low  is not None else price
    eff_high = max(price, wick_high) if wick_high is not None else price

    # Hold time — guard missing entry_at (§1.9)
    entry_at_valid = bool(trade.entry_at and trade.entry_at > 1_000_000_000)
    hold_minutes = (time.time() - trade.entry_at) / 60 if entry_at_valid else 0.0

    new_status:   Optional[str]   = None
    close_price:  Optional[float] = None
    close_reason: Optional[str]   = None

    # ── G5b: Absolute profit lock — prevent large give-back from peak ────────
    _pnl_now_spot = (price - entry) / entry * 100 - EXECUTION_COST_PCT if entry > 0 else 0.0
    _peak_pnl_spot = float(meta.get("peak_pnl_pct", 0.0))
    if _pnl_now_spot > _peak_pnl_spot:
        _peak_pnl_spot = round(_pnl_now_spot, 3)
        meta["peak_pnl_pct"] = _peak_pnl_spot
        trade.signals_json   = json.dumps(meta, ensure_ascii=False)
    # M4b: gerak MERUGIKAN terjauh (MAE) — pasangan dari peak di atas. Tanpa ini
    # tak ada cara tahu berapa banyak jarak SL yang benar-benar terpakai.
    _trough_pnl_spot = float(meta.get("trough_pnl_pct", 0.0))
    if _pnl_now_spot < _trough_pnl_spot:
        meta["trough_pnl_pct"] = round(_pnl_now_spot, 3)
        trade.signals_json     = json.dumps(meta, ensure_ascii=False)
    for _pt, _lf in _PROFIT_LOCK_TIERS_SPOT:
        if _peak_pnl_spot >= _pt and _pnl_now_spot <= _peak_pnl_spot * _lf:
            pnl_pct, pnl_dollar = _final_pnl(entry, price, trade.position_size or 0.0, meta)
            meta["close_reason"]  = "absolute_profit_lock"
            meta["peak_pnl_pct"]  = _peak_pnl_spot
            trade.status       = "tp"
            trade.close_price  = round(price, 8)
            trade.closed_at    = time.time()
            trade.pnl_pct      = pnl_pct
            trade.pnl_dollar   = pnl_dollar
            trade.signals_json = json.dumps(meta, ensure_ascii=False)
            logger.info("absolute_profit_lock_spot", symbol=trade.symbol,
                        peak_pnl=round(_peak_pnl_spot, 2), current_pnl=round(_pnl_now_spot, 2))
            return 1, 0

    # ── PLAN_v10 — scale-out helper: jual `frac` posisi asli di `rung_price`,
    # bank realized $ (permanen), kecilkan runner, catat ladder, ratchet floor.
    def _scale_out(frac: float, rung_name: str, rung_price: float, floor_price: float) -> None:
        rung_net_pct = (rung_price - entry) / entry * 100 - EXECUTION_COST_PCT
        slice_dlr    = round((rung_net_pct / 100) * (trade.position_size or 0.0) * frac, 2)
        meta["banked_dollar"]      = round(meta.get("banked_dollar", 0.0) + slice_dlr, 2)
        meta["remaining_fraction"] = round(max(0.0, meta.get("remaining_fraction", 1.0) - frac), 4)
        _ladder = meta.get("ladder", [])
        _ladder.append({"rung": rung_name, "price": round(rung_price, 8),
                        "frac": frac, "pnl_dollar": slice_dlr})
        meta["ladder"] = _ladder
        # ratchet floor — hanya boleh NAIK, & jangan di atas harga sekarang (anti wick-stop)
        _new_floor = min(max(sl, floor_price), price * 0.999)
        if _new_floor > sl:
            meta["current_sl"] = round(_new_floor, 8)
            trade.stop_loss    = round(_new_floor, 8)

    # ── Layer 3: max age — BM7 per entry_mode, B-Fix 3 per lane ─────────────
    _entry_mode = meta.get("entry_mode", "fresh_setup")
    if _entry_mode == "momentum_entry":
        _age_expired = entry_at_valid and hold_minutes > 6 * 60   # B6: 6-hour max
    elif _lane == "bigmover":
        # B-Fix 3: budget umur sendiri — dulu lane ini jatuh ke cabang `else`
        # dan mewarisi 10 hari milik akumulasi (ADAUSDT tertahan 4.9 hari lalu SL).
        _age_expired = entry_at_valid and hold_minutes / (60 * 24) > scfg.MAX_AGE_DAYS_BIGMOVER
    elif _entry_mode == "momentum_chase":
        _age_expired = entry_at_valid and hold_minutes / (60 * 24) > scfg.MAX_AGE_DAYS_MOMENTUM_CHASE
    else:
        _age_expired = entry_at_valid and hold_minutes / (60 * 24) > scfg.MAX_AGE_DAYS_FRESH_SETUP
    if _age_expired:
        pnl_now = (price - entry) / entry * 100
        new_status   = "tp" if pnl_now > EXECUTION_COST_PCT else "sl"
        close_price  = round(price, 8)
        close_reason = "max_age_expired"

    # ── Layer 1: hard exits — SL first when both touched (conservative) ─────
    elif eff_low <= sl:
        # §1.2/§14.6: market stop triggers AT sl, fills sl − slippage —
        # bounded below by the actual wick low (can't fill below the real low,
        # and a deep wick that recovered does NOT fill at its extreme).
        trigger_fill = sl * (1 - SL_SLIPPAGE_PCT / 100)
        fill = max(eff_low, trigger_fill) if wick_low is not None else min(sl, price)
        close_price  = round(min(fill, sl), 8)
        # §1.1: breakeven stop after TP1 is NOT a real loss
        if meta.get("tp1_hit"):
            close_reason = "tp1_breakeven"
        else:
            close_reason = "sl_hit"
        pnl_probe  = (close_price - entry) / entry * 100 - EXECUTION_COST_PCT
        new_status = "tp" if (meta.get("tp1_hit") and pnl_probe > 0) else "sl"
    elif is_momentum_chase and meta.get("tp1_hit"):
        # ── PLAN_v10 RUNNER: ride winner tanpa cap.
        # Sengaja TETAP `is_momentum_chase`, bukan `trails_after_tp1`: kalau lane
        # BigMover masuk ke sini sejak TP1, ia akan melewati rung TP2 (20%) dan
        # TP3 (15%) dan langsung ke rung dinamis — mengurangi profit yang dikunci.
        # BigMover tetap menaiki tangga ladder-nya, lalu berubah jadi runner
        # sendirinya di TP2 (baris di bawah menulis entry_mode="momentum_chase"). Lahirkan rung dinamis
        # TP4..TP-n selama gate (flow+TA) hijau; kalau tidak, keluar hanya saat
        # struktur 4h patah. Trailing SL (di atas) sudah ratchet floor tiap cycle.
        _atr1h     = _atr(k1h)
        _remaining = meta.get("remaining_fraction", 1.0)
        _last_rung = meta.get("last_rung_price") or tp3 or tp2 or tp1 or entry
        _rung_gap  = max(_atr1h * scfg.DYN_RUNG_ATR_MULT, scfg.DYN_RUNG_STEP_PCT / 100 * entry)
        _next_rung = _last_rung + _rung_gap
        _gate_ok, _gate_why = _still_strong_gate(trade.symbol, k1h)
        if (eff_high >= _next_rung and _gate_ok
                and _remaining - DYN_RUNG_FRAC >= RUNNER_MIN_FRACTION):
            _floor = (_next_rung - _atr1h) if _atr1h > 0 else _next_rung * 0.98
            _scale_out(DYN_RUNG_FRAC, "tp_dyn", _next_rung, _floor)
            meta["last_rung_price"] = round(_next_rung, 8)
            trade.signals_json = json.dumps(meta, ensure_ascii=False)
            logger.info("v10_dynamic_rung", symbol=trade.symbol,
                        rung=round(_next_rung, 8), banked=meta["banked_dollar"],
                        remaining=meta["remaining_fraction"])
            return 0, 1
        # tidak ada rung baru → cek struktur patah (ambil sisa runner sekaligus)
        if len(k4h) >= 21:
            closes4h = [float(k[4]) for k in k4h]
            ema9_4h  = _ema(closes4h, 9)
            ema21_4h = _ema(closes4h, 21)
            if ema9_4h < ema21_4h * 0.995:
                pnl_probe = (price - entry) / entry * 100 - EXECUTION_COST_PCT
                new_status   = "tp" if pnl_probe > 0 else "sl"
                close_price  = round(price, 8)
                close_reason = "trend_structure_broken"
                logger.info("momentum_chase_structure_break",
                            symbol=trade.symbol,
                            ema9=round(ema9_4h, 6), ema21=round(ema21_4h, 6),
                            pnl_net=round(pnl_probe, 2))
    elif tp3 and eff_high >= tp3 and not meta.get("tp3_hit"):
        # PLAN_v10 — TP3 tidak lagi tutup 100%: scale-out 15% lalu jadi runner.
        meta["tp3_hit"]    = True
        meta["tp3_hit_at"] = time.time()
        _scale_out(LADDER_FRAC_TP3, "tp3", tp3, max(sl, tp2 or tp1 or entry))
        meta["entry_mode"]      = "momentum_chase"
        meta["tp_extended"]     = True
        meta["tp1_hit"]         = True
        meta["last_rung_price"] = round(tp3, 8)
        trade.signals_json      = json.dumps(meta, ensure_ascii=False)
        logger.info("v10_tp3_scaleout_runner", symbol=trade.symbol, tp3=tp3,
                    banked=meta["banked_dollar"], remaining=meta["remaining_fraction"])
        return 0, 1
    elif eff_high >= tp2 and not meta.get("tp2_hit"):
        # PLAN_v10 — CAP LAMA ADA DI SINI (dulu tutup 100% di TP2). Sekarang:
        # scale-out 20%, kunci floor ≥ TP1, konversi jadi runner → ikut pump besar.
        meta["tp2_hit"]    = True
        meta["tp2_hit_at"] = time.time()
        _scale_out(LADDER_FRAC_TP2, "tp2", tp2, max(sl, tp1 or entry))
        meta["entry_mode"]      = "momentum_chase"
        meta["tp_extended"]     = True
        meta["tp1_hit"]         = True      # pastikan runner path aktif cycle berikut
        meta["last_rung_price"] = round(tp2, 8)
        trade.signals_json      = json.dumps(meta, ensure_ascii=False)
        logger.info("v10_tp2_scaleout_runner", symbol=trade.symbol, tp2=tp2,
                    banked=meta["banked_dollar"], remaining=meta["remaining_fraction"])
        return 0, 1
    elif tp1 and eff_high >= tp1 and not meta.get("tp1_hit"):
        # PLAN_v10 — scale-out 30% di TP1 (dulu 50%), floor = entry + 50% gain TP1.
        sell_frac = LADDER_FRAC_TP1
        new_sl    = entry * (1 + ((tp1 - entry) / entry) * 0.5)   # §12.6
        meta["tp1_hit"]         = True
        meta["tp1_hit_price"]   = round(float(eff_high), 8)
        meta["tp1_hit_at"]      = time.time()
        meta["last_rung_price"] = round(tp1, 8)
        _scale_out(sell_frac, "tp1", tp1, new_sl)
        # kompat lama: tp1_partial_dollar = slice pertama ladder
        meta["tp1_partial_dollar"] = meta.get("ladder", [{}])[-1].get("pnl_dollar", 0.0)

        # BM6: fresh_setup + volume spike → langsung mode runner trailing
        if _entry_mode == "fresh_setup" and not meta.get("upgraded_to_trailing"):
            _vol_spike_now = _vol_ratio([float(k[5]) for k in k1h]) if k1h else 1.0
            if _vol_spike_now >= 5.0:
                meta["entry_mode"]           = "momentum_chase"
                meta["upgraded_to_trailing"] = True
                logger.info("fresh_setup_upgraded_to_trailing",
                            symbol=trade.symbol, vol_spike=round(_vol_spike_now, 1))

        trade.signals_json = json.dumps(meta, ensure_ascii=False)
        logger.info("opportunity_tp1_partial", symbol=trade.symbol,
                    tp1=tp1, sold_frac=sell_frac,
                    locked_dollar=meta.get("tp1_partial_dollar", 0.0),
                    new_sl=meta.get("current_sl"))
        return 0, 1

    # ── Layer 2: risk-adjusted exits ─────────────────────────────────────────
    if new_status is None:
        tp2_net = (tp2 - entry) / entry * 100 - EXECUTION_COST_PCT
        reason = _risk_signal(
            k1h, entry, price, trade.symbol,
            entry_ema_bullish=meta.get("entry_ema_bullish", True),
            hold_minutes=hold_minutes,
            tp2_net_pct=tp2_net,
        )
        if reason:
            pnl_net      = (price - entry) / entry * 100 - EXECUTION_COST_PCT
            new_status   = "tp" if pnl_net > 0 else "sl"
            close_price  = round(price, 8)
            close_reason = reason
            logger.info("opportunity_risk_adjusted_close",
                        symbol=trade.symbol, reason=reason,
                        pnl_net=round(pnl_net, 2), hold_min=round(hold_minutes, 1))

    # ── Layer 2.5: stagnant / urgent rotation ────────────────────────────────
    # Normal: day 2+, price stuck ±3%, scanner has a materially better candidate.
    # Urgent: day 1+, candidate outscores by 25+ regardless of drift — clear
    #         opportunity cost from holding a position while a much better one waits.
    if new_status is None and entry_at_valid:
        hold_days   = hold_minutes / (60 * 24)
        drift_pct   = abs(price - entry) / entry * 100 if entry > 0 else 99.0
        trade_score = meta.get("raw_score") or trade.probability or 0
        # BM1: cap at 80 so high-score positions (e.g. 99) don't require
        # an impossible candidate score of 109+ to trigger rotation
        capped_score = min(trade_score, 80)

        _rotate     = False
        _rotate_why = "stagnant_rotation"
        if hold_days >= scfg.STAGNANT_CHECK_DAYS and drift_pct <= scfg.STAGNANT_DRIFT_PCT:
            if _has_better_candidate(capped_score, trade.symbol):
                _rotate = True
        elif hold_days >= scfg.URGENT_ROTATION_DAYS:
            if _has_better_candidate(capped_score, trade.symbol,
                                     min_gap=scfg.URGENT_SCORE_GAP, min_score=scfg.URGENT_SCORE_MIN):
                _rotate     = True
                _rotate_why = "urgent_rotation"

        # PLAN_SPOT_LANES B-Fix 4: rotasi tidak boleh MEMBUKUKAN kerugian.
        # Rotasi adalah keputusan biaya-peluang ("modal ini lebih baik di tempat
        # lain"), bukan sinyal bahwa setup-nya patah. Forensik 21 Jul: 7 dari 17
        # rotasi tutup rugi. Kalau posisi sedang merah lebih dari ambang ini,
        # biarkan SL/TP-nya sendiri yang memutuskan — struktur yang benar-benar
        # patah sudah punya jalan keluarnya sendiri lewat `trend_reversal`.
        _rotate_pnl_net = (price - entry) / entry * 100 - EXECUTION_COST_PCT
        if _rotate and _rotate_pnl_net < scfg.ROTATION_MIN_PNL_PCT:
            logger.info("rotation_skipped_in_drawdown",
                        symbol=trade.symbol, why=_rotate_why,
                        pnl_net=round(_rotate_pnl_net, 2),
                        floor=scfg.ROTATION_MIN_PNL_PCT)
            _rotate = False

        if _rotate:
            pnl_net      = _rotate_pnl_net
            new_status   = "tp" if pnl_net > 0 else "sl"
            close_price  = round(price, 8)
            close_reason = _rotate_why
            logger.info(
                _rotate_why,
                symbol=trade.symbol,
                hold_days=round(hold_days, 1),
                drift_pct=round(drift_pct, 2),
                pnl_net=round(pnl_net, 2),
            )

    # ── Apply close ───────────────────────────────────────────────────────────
    if new_status and close_price is not None and close_price > 0:
        pnl_pct, pnl_dollar = _final_pnl(entry, close_price, trade.position_size or 0.0, meta)

        meta["close_reason"]  = close_reason
        meta["fee_pct"]       = EXECUTION_COST_PCT
        meta["pnl_gross_pct"] = round((close_price - entry) / entry * 100, 2)
        trade.status       = new_status
        trade.close_price  = close_price
        trade.closed_at    = time.time()
        trade.pnl_pct      = pnl_pct
        trade.pnl_dollar   = pnl_dollar
        trade.signals_json = json.dumps(meta, ensure_ascii=False)

        # M7: catat keputusan keluar ke ledger bersama. Sisi futures sudah punya
        # ini sejak M0; SPOT selama ini menutup 65 posisi tanpa satu pun tercatat
        # dalam bentuk yang bisa di-query, sehingga Adaptive Engine tak punya
        # bahan belajar untuk keputusan keluar spot.
        from agents.shared.exit_ledger import log_exit
        await log_exit(
            session, trade, meta, market="spot",
            # `lane_of()` — fungsi yang SAMA yang dipakai untuk keputusan. Menulis
            # `alert_type` mentah di sini membuat ledger memakai kosakata berbeda
            # (`squeeze`) dari config (`accumulation`), sehingga hasil belajar
            # mendarat di kunci yang tak pernah dibaca monitor mana pun.
            lane=lane_of(meta, trade.alert_type),
            close_reason=close_reason or "", status=new_status,
            pnl_net=pnl_pct, pnl_dollar=pnl_dollar,
        )

        logger.info("opportunity_position_closed",
                    symbol=trade.symbol, status=new_status, reason=close_reason,
                    entry=entry, close=close_price,
                    pnl_net=pnl_pct, pnl_dollar=pnl_dollar,
                    hold_min=round(hold_minutes, 1))
        return 1, 0

    return 0, 0


# ── Balance bookkeeping ──────────────────────────────────────────────────────

async def _update_paper_balance() -> None:
    """
    Recompute paper balance with a SQL aggregate (§9.1 — no row scan).
    balance = initial + deposits − withdrawals + Σ pnl_dollar  (§1.4)
    """
    from app.api.v1.balance import DEFAULT_BALANCE

    async with AsyncSessionLocal() as session:
        total = (await session.execute(
            select(func.coalesce(func.sum(PaperTrade.pnl_dollar), 0.0)).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status.in_(["tp", "sl", "manual"]),
                PaperTrade.pnl_dollar.isnot(None),
            )
        )).scalar() or 0.0

        bal_result = await session.execute(
            select(PaperBalance).where(PaperBalance.style == "opportunity_spot")
        )
        bal = bal_result.scalar_one_or_none()
        now = time.time()
        if bal is None:
            bal = PaperBalance(
                style           = "opportunity_spot",
                balance         = round(DEFAULT_BALANCE + total, 2),
                initial_balance = DEFAULT_BALANCE,
                deposited_total = 0.0,
                withdrawn_total = 0.0,
                realized_pnl    = round(total, 2),
                updated_at      = now,
                created_at      = now,
            )
            session.add(bal)
        else:
            bal.balance = round(
                bal.initial_balance + bal.deposited_total - bal.withdrawn_total + total, 2
            )
            bal.realized_pnl = round(total, 2)
            bal.updated_at   = now

        await session.commit()
        logger.info("paper_balance_updated", balance=bal.balance, realized_pnl=bal.realized_pnl)


async def run_opportunity_monitor() -> None:
    global _running, _cycle_count, _last_check, _last_error, _last_weight_run

    _running = True
    logger.info("opportunity_monitor_started",
                interval_sec=INTERVAL_SEC,
                max_age_fresh=scfg.MAX_AGE_DAYS_FRESH_SETUP,
                max_age_momentum=scfg.MAX_AGE_DAYS_MOMENTUM_CHASE,
                execution_cost_pct=EXECUTION_COST_PCT)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            # Ambang keputusan keluar ditarik SEBELUM posisi dievaluasi, supaya
            # satu siklus memakai satu set nilai — bukan campuran lama dan baru.
            # Gagal baca = diam & pakai nilai terakhir; monitor tak boleh berhenti
            # hanya karena config tak terbaca.
            await scfg.refresh()
            n = await check_positions()
            _last_check = time.time()
            _last_error = None
            if n:
                logger.info("monitor_cycle_closed", count=n, cycle=_cycle_count)

            # Adaptive learning — time-based schedule (§1.12)
            if time.time() - _last_weight_run >= WEIGHT_UPDATE_SEC:
                _last_weight_run = time.time()
                try:
                    from agents.opportunity.weight_updater import update_spot_weights
                    upd = await update_spot_weights()
                    if upd:
                        logger.info("spot_weights_auto_updated", keys=upd)
                except Exception as we:
                    logger.warning("spot_weight_update_failed", error=str(we)[:80])

        except asyncio.CancelledError:
            logger.info("opportunity_monitor_stopped")
            _running = False
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.error("opportunity_monitor_error", error=_last_error)
        finally:
            _cycle_count += 1   # §1.12: count even on errors

        await asyncio.sleep(INTERVAL_SEC)
