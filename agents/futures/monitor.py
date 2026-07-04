"""
Futures Risk Monitor — runs every 2 minutes.

For each open futures paper trade:
  1. Auto-close: SL or TP2/TP3/TP4 hit
  2. Trail SL: 50% to TP1 → breakeven; TP1 hit → 75% gain locked; 50% TP1→TP2 → TP1 locked
  3. TP1 partial close: 33% of position closed at TP1
  4. Liquidation guard: adaptive per leverage — close early to protect capital
  5. TP3 extension: score ≥ 70 at TP1 → extend to TP3, lock SL at TP1
  6. TP4 extension (F78): score ≥ 65 at TP3 → extend to TP4, lock SL at TP2
  7. Regime SL: on first check, widen SL in volatile / tighten in ranging
  8. Stagnant 48h: close if no progress (< 20% toward TP1) after 48 hours
  9. Funding degradation (F88/F90): every 10 cycles, tighten SL to breakeven if funding flips
 10. Updates trade record in DB
"""

import asyncio
import json
import time
from decimal import Decimal
from typing import Optional

import httpx
import structlog
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_balance import PaperBalance
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import fapi
from app.services.trading_costs import (
    FUTURES_STARTING_BALANCE,
    FUTURES_BALANCE_STATUSES, futures_notional,   # Phase 9: fallback notional for legacy rows
)
from agents.futures.utils import (
    MAX_LOSS_PCT_OF_MARGIN_BY_LANE, DEFAULT_MAX_LOSS_PCT,
    MAX_SL_MARGIN_PCT_BY_LANE,     DEFAULT_LANE_CAP,
    lane_for_style,
)

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 120   # every 2 minutes
STARTUP_DELAY = 60    # start after main scanner

# Futures taker fee: 0.05% per side = 0.10% round trip
TAKER_FEE     = 0.0005   # 0.05% per side
ROUND_TRIP    = TAKER_FEE * 2  # 0.10% total

# Max position age in days — close stalled futures positions
MAX_AGE_DAYS       = 3   # futures positions should resolve faster than spot
MAX_AGE_EXTENSIONS = 2   # G11: max 2 × 1-day extensions → 5 days total for winners

# G3: rotation constants
FUTURES_ROTATION_MIN_DAYS  = 1.0   # start checking after 1 day
FUTURES_ROTATION_DRIFT_PCT = 3.0   # ≤3% from entry = stagnant
FUTURES_ROTATION_SCORE_GAP = 10    # candidate must outscore by at least 10

# PLAN_v6 P1c: momentum time-stop (scratch exit) — a trade that hasn't reached
# +0.5×risk within N minutes AND never hit TP1 is a failed thesis; close at market
# (small loss/scratch) instead of bleeding to full SL over hours (AMAT held 21.6h → SL).
TIME_STOP_MIN_BY_LANE: dict[str, float] = {
    "momentum":     90.0,
    "bigmover":     90.0,
    "pre_gainer":   360.0,   # 6h
    "pre_move":     360.0,   # legacy alias
    "accumulation": 360.0,   # 6h — needs room to develop
}
TIME_STOP_PROGRESS_FRAC = 0.5   # must reach ≥ 0.5×risk favorable to survive time-stop
# PLAN_v11 B2: "scratch" hanya untuk trade STAGNAN (dekat breakeven). Kalau sudah
# rugi ≥ 0.5×risk, JANGAN scratch — biarkan SL asli yang eksekusi. Bug lama:
# AERGO ditutup −13% berlabel "time_stop_scratch" (realisasi loser besar dini).
TIME_STOP_LOSS_GUARD_FRAC = 0.5   # jika _fav ≤ −0.5×risk → skip scratch, serahkan ke SL

# G4: rugpull detection constants
RUGPULL_CANDLES       = 5     # 5×1m candles = 5-minute window
RUGPULL_BASE_PCT      = 5.0   # minimum adverse-move threshold
RUGPULL_MIN_HOLD_MIN  = 10.0  # PLAN_v11 B3: 5→10 min — hindari panic-exit di noise buka posisi
RUGPULL_CONFIRM_MULT  = 1.2   # PLAN_v11 B3: adverse move harus 1.2× ambang (bukan pas-pasan) → flash asli

# G5b: absolute profit lock — tier thresholds (peak_pnl → lock if drop below fraction)
# PLAN_v11 P3: tier tinggi (100%/300% margin) untuk pump besar — 1000% tak boleh menguap.
# Urut tertinggi dulu supaya lock paling ketat yang berlaku.
_PROFIT_LOCK_TIERS = [
    (300.0, 0.90),  # peak ≥ 300%: beri balik maks 10%
    (100.0, 0.85),  # peak ≥ 100%: beri balik maks 15%
    (40.0, 0.75),   # peak ≥ 40%: lock at 75% of peak
    (25.0, 0.70),   # peak ≥ 25%: lock at 70% of peak
    (15.0, 0.60),   # peak ≥ 15%: lock at 60% of peak
]

# G6: funding cost tracker
FUNDING_WINDOW_SEC     = 8 * 3600   # Binance funds every 8h
COST_TO_PROFIT_GATE    = 0.30       # close if cumulative cost > 30% of unrealized profit
COST_ABS_LOSS_GATE_PCT = 0.003      # B5.3: close losing trade if cost > 0.3% of notional

# BUG-L8: wick detection — 1m candles checked per cycle so TP/SL touches BETWEEN the
# 2-min polls aren't missed (spot monitor already does this; futures did not → a wick that
# hit TP then pulled back was missed and the position later recorded as an SL loss).
# PLAN_v6 P5a: was 3 — but the poll gap is 120s PLUS processing time (scan cycles run
# 30-135s), so a slow cycle left minutes of candles unseen and a TP wick in that gap
# was lost (then the trade bled to SL). 6 covers a full slow cycle; same API cost.
WICK_LOOKBACK_MIN = 6

_running     = False
_cycle_count = 0
_last_check: Optional[float] = None
_last_error: Optional[str]   = None
_closed_today      = 0
_liq_guards        = 0   # positions closed by liquidation guard
_tp_extended       = 0   # positions with TP extended
_max_loss_closes   = 0   # PLAN_v2 P1.1 — positions closed by hard max-loss-per-trade gate
_derisk_partials   = 0   # PLAN_v2 P1.5 — F79 widening triggered partial de-risk
_today: Optional[str] = None  # F61: track date for daily closed_today reset

# P5.4: fast loop — trade IDs identified as high-risk in the last main cycle
_fast_loop_trade_ids: set[int] = set()
FAST_INTERVAL_SEC = 30   # check high-risk positions every 30s (was never checked)

# EC5: server-time drift check
NTP_CHECK_INTERVAL_SEC = 1800   # every 30 min
_last_ntp_check: float = 0.0

_FUTURES_STYLES = (
    "futures_agent1", "futures_agent2", "futures_agent3",
    "futures_agent_bigmover",   # Phase 2 BM1 — monitor BM positions same as others
)


def get_state() -> dict:
    return {
        "running":         _running,
        "cycle_count":     _cycle_count,
        "last_check":      _last_check,
        "last_error":      _last_error,
        "closed_today":    _closed_today,
        "liq_guards":      _liq_guards,
        "tp_extended":     _tp_extended,
        "max_loss_closes": _max_loss_closes,    # PLAN_v2 P1.1
        "derisk_partials": _derisk_partials,    # PLAN_v2 P1.5
    }


# ── PLAN_v2 P1.4 — per-trade event log helper ─────────────────────────────────

_EVENT_LOG_CAP = 30


def _append_trade_event(meta: dict, kind: str, payload: dict | None = None) -> None:
    """Append an event to signals_json.events[] (FIFO-capped). Used by monitor to
    build a per-trade timeline visible from the UI."""
    events = meta.get("events")
    if not isinstance(events, list):
        events = []
    entry = {"ts": time.time(), "kind": kind}
    if payload:
        entry.update(payload)
    events.append(entry)
    if len(events) > _EVENT_LOG_CAP:
        events = events[-_EVENT_LOG_CAP:]
    meta["events"] = events


def _calc_liq_price(
    entry: float,
    leverage: int,
    direction: str,
    position_size: float = 0.0,
    wallet_equity: float = 0.0,
    other_open_loss: float = 0.0,
) -> float:
    """
    BC1: Cross-margin liquidation approximation.
    When wallet_equity is known, uses effective equity to compute how far price
    can move before the portfolio loses its maintenance margin on this position.
    Falls back to the isolated approximation when data is unavailable.

    MMR = 1% for altcoin perpetuals (Binance default).
    Effective equity = wallet_equity + unrealized losses from OTHER open positions.
    The position liq-price is approximately:
      dist = entry × max((effective_equity / notional) − MMR, 0.01)
    """
    MMR      = 0.01   # 1% maintenance margin rate (conservative for alts)
    notional = position_size * max(leverage, 1)
    if notional > 0 and wallet_equity > 0:
        # Cross-margin: wallet equity shared across positions; other losses reduce buffer
        effective_equity = max(wallet_equity + other_open_loss, notional * MMR * 1.5)
        dist_fraction    = max((effective_equity / notional) - MMR, 0.01)
        dist             = entry * dist_fraction
    else:
        # Fallback: isolated approximation (original formula)
        dist = entry * (0.95 / max(leverage, 1))
    return (entry - dist) if direction == "LONG" else (entry + dist)


def _liq_dist_pct(price: float, liq: float, direction: str) -> float:
    """% distance between current price and liquidation price."""
    if direction == "LONG":
        return (price - liq) / price * 100 if price > 0 else 99.0
    return (liq - price) / price * 100 if price > 0 else 99.0


def _liq_guard_pct(leverage: int) -> float:
    """F85: adaptive liquidation guard threshold based on leverage."""
    if leverage <= 5:
        return 8.0
    if leverage <= 10:
        return 6.0
    if leverage <= 20:
        return 4.0
    return 3.0


# ── G4 helper ─────────────────────────────────────────────────────────────────

def _rugpull_threshold(atr_pct: float) -> float:
    """B5.2: adaptive rugpull threshold = max(5%, ATR × 2)."""
    return max(RUGPULL_BASE_PCT, atr_pct * 2.0)


def _flash_adverse_pct(klines_1m: list, direction: str) -> float:
    """
    Compute the maximum adverse move in the last RUGPULL_CANDLES 1m candles.
    LONG: (high of first candle − min low across window) / high of first candle
    SHORT: (max high across window − low of first candle) / low of first candle
    Returns 0.0 if data insufficient.
    """
    if len(klines_1m) < RUGPULL_CANDLES:
        return 0.0
    last5 = klines_1m[-RUGPULL_CANDLES:]
    try:
        if direction == "LONG":
            ref  = float(last5[0][2])   # high of oldest candle in window
            low  = min(float(k[3]) for k in last5)
            return (ref - low) / ref * 100 if ref > 0 else 0.0
        else:  # SHORT
            ref  = float(last5[0][3])   # low of oldest candle in window
            high = max(float(k[2]) for k in last5)
            return (high - ref) / ref * 100 if ref > 0 else 0.0
    except (IndexError, ValueError):
        return 0.0


# ── G3 helper ─────────────────────────────────────────────────────────────────

def _futures_has_better_candidate(
    current_score: float,
    exclude_symbol: str,
    agent_style: str,
) -> bool:
    """
    G3: True if the futures scan cache has a candidate with materially higher score.
    Uses the same agent's cached results so we compare like-for-like setups.
    Cap current_score at 80 to prevent impossibly high required candidate score.
    """
    try:
        from agents.futures import store as futures_store
        cached = futures_store.get_result(agent_style)
        if not cached:
            return False
        capped = min(current_score, 80)
        for c in cached.get("results", []):
            if c.get("symbol") == exclude_symbol:
                continue
            c_score = c.get("score", 0)
            if c_score >= capped + FUTURES_ROTATION_SCORE_GAP:
                return True
    except Exception:
        pass
    return False


# ── Price fetcher ─────────────────────────────────────────────────────────────

async def _fetch_futures_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch futures mark prices — batch endpoint to minimize weight usage."""
    if not symbols:
        return {}
    import json as _json
    prices: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Batch: /fapi/v1/ticker/price?symbols=[...] — weight=2 for all
            syms_param = _json.dumps(symbols, separators=(",", ":"))  # BUG-L25: compact (Binance rejects spaces)
            r = await client.get(
                fapi("/fapi/v1/ticker/price"),
                params={"symbols": syms_param},
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        prices[item["symbol"]] = float(item["price"])
                    return prices
            # Fallback: semaphore-limited individual requests
            _sem = asyncio.Semaphore(10)
            async def _fetch_one(sym: str) -> None:
                async with _sem:
                    try:
                        resp = await client.get(fapi(f"/fapi/v1/ticker/price?symbol={sym}"))
                        if resp.status_code == 200:
                            prices[sym] = float(resp.json()["price"])
                    except Exception:
                        pass
            await asyncio.gather(*[_fetch_one(s) for s in symbols])
    except Exception:
        pass
    return prices


async def _fetch_funding_rates(symbols: list[str]) -> dict[str, float]:
    """F88/F90: fetch current funding rates (%) for degradation check."""
    if not symbols:
        return {}
    import json as _json
    rates: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            syms_param = _json.dumps(symbols, separators=(",", ":"))
            r = await client.get(
                fapi("/fapi/v1/premiumIndex"),
                params={"symbols": syms_param},
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        rates[item["symbol"]] = float(item.get("lastFundingRate", 0)) * 100
                    return rates
    except Exception:
        pass
    return rates


async def _check_server_time_drift() -> None:
    """EC5: Warn if this server's clock drifts >5s from Binance serverTime.

    Funding windows are calculated with server time; a drift of >5s can cause
    the G9 funding-window exit to fire at the wrong moment.  Runs at most every
    30 min so the overhead is negligible.
    """
    global _last_ntp_check
    now = time.time()
    if now - _last_ntp_check < NTP_CHECK_INTERVAL_SEC:
        return
    _last_ntp_check = now
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(fapi("/fapi/v1/time"))
            if r.status_code == 200:
                binance_ms = r.json().get("serverTime", 0)
                drift = abs(time.time() - binance_ms / 1000)
                if drift > 5.0:
                    logger.warning("server_time_drift",
                                   drift_sec=round(drift, 2),
                                   msg="funding window timing may be off — check NTP")
                else:
                    logger.debug("server_time_ok", drift_sec=round(drift, 3))
    except Exception:
        pass  # non-critical — skip silently


async def _fetch_futures_klines_1m(client: "httpx.AsyncClient", symbol: str) -> list:
    """BUG-L8: last few 1m candles — wick detection for TP/SL touches between 2-min polls."""
    try:
        r = await client.get(
            fapi(f"/fapi/v1/klines?symbol={symbol}&interval=1m&limit={WICK_LOOKBACK_MIN}")
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


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


# ── Trail SL logic ─────────────────────────────────────────────────────────────

def _compute_trail(
    direction:    str,
    entry:        float,
    sl:           float,
    tp1:          float,
    tp2:          float,
    price:        float,
    trail_active: bool,
    setup_type:   str = "",
) -> tuple[Optional[float], bool, str]:
    """
    Returns (new_trail_sl, trail_now_active, event_label).
    Returns (None, trail_active, "") if no change needed.

    PLAN_v6 P1d: breakeven arm EARLIER so more trades get protected before a reversal
    (root-cause fix — old 70% arm meant trades that never reached ~+4.5% stayed at full
    SL and bled to −5%). Per setup_type:
      - momentum / pre_gainer / pre_move / default: 40% to TP1 (was 70%)
      - accumulation: 60% to TP1 (was 90% — still patient but not reckless)
      - bigmover: 40% to TP1 (was 60%)

    Stages (LONG) after breakeven:
      2. Price hits TP1     → SL to entry + 75%(TP1-entry)      [F14]
      3. Price 50% TP1→TP2  → SL to TP1 level (lock TP1 profit)  [F77]
    """
    # P5.1 + PLAN_v6 P1d: lane-specific breakeven fraction (armed earlier)
    if setup_type == "accumulation":
        be_frac = 0.60   # patient but protects before deep reversal (was 0.90)
    elif setup_type == "bigmover":
        be_frac = 0.40   # volatile → lock breakeven fast (was 0.60)
    else:
        be_frac = 0.40   # momentum / pre_gainer / pre_move (was 0.70)

    if direction == "LONG":
        halfway_to_tp1   = entry + (tp1 - entry) * be_frac
        sl_after_tp1     = entry + (tp1 - entry) * 0.75

        # F77: after TP1 hit (trail_active), when 50% toward TP2, advance SL to TP1
        if trail_active and tp2 > tp1 and sl < tp1:
            halfway_tp1_tp2 = tp1 + (tp2 - tp1) * 0.50
            if price >= halfway_tp1_tp2:
                return tp1, True, "tp1_lock"

        if price >= tp1 and (not trail_active or sl < sl_after_tp1):
            return sl_after_tp1, True, "tp1_trail"

        if price >= halfway_to_tp1 and not trail_active and sl < entry:
            return entry, True, "breakeven"

    else:  # SHORT
        halfway_to_tp1   = entry - (entry - tp1) * be_frac
        sl_after_tp1     = entry - (entry - tp1) * 0.75

        # F77: after TP1 hit (trail_active), when 50% toward TP2, advance SL to TP1
        if trail_active and tp2 < tp1 and sl > tp1:
            halfway_tp1_tp2 = tp1 - (tp1 - tp2) * 0.50
            if price <= halfway_tp1_tp2:
                return tp1, True, "tp1_lock"

        if price <= tp1 and (not trail_active or sl > sl_after_tp1):
            return sl_after_tp1, True, "tp1_trail"

        if price <= halfway_to_tp1 and not trail_active and sl > entry:
            return entry, True, "breakeven"

    return None, trail_active, ""


# ── Balance sync ──────────────────────────────────────────────────────────────

async def _update_futures_balance() -> None:
    """
    Phase 9: recompute the SINGLE `futures` wallet (both agents share it).
    balance = initial + deposited − withdrawn + Σ pnl_dollar (tp/sl only, F15/F33).
    Mirrors the spot pattern (agents/opportunity/monitor.py::_update_paper_balance) —
    deposits/withdrawals are preserved, so "deposit and the agent works" holds.
    """
    if not is_db_available():
        return

    async with AsyncSessionLocal() as session:
        total = (await session.execute(
            select(func.coalesce(func.sum(PaperTrade.pnl_dollar), 0.0)).where(
                PaperTrade.style.in_(list(_FUTURES_STYLES)),
                PaperTrade.status.in_(list(FUTURES_BALANCE_STATUSES)),   # BUG-L19: include expired
                PaperTrade.pnl_dollar.isnot(None),
            )
        )).scalar() or 0.0

        bal = (await session.execute(
            select(PaperBalance).where(PaperBalance.style == "futures")
        )).scalar_one_or_none()
        now = time.time()
        if bal is None:
            bal = PaperBalance(
                style           = "futures",
                balance         = round(FUTURES_STARTING_BALANCE + total, 2),
                initial_balance = FUTURES_STARTING_BALANCE,
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
        logger.info("futures_balance_synced", balance=bal.balance, realized_pnl=bal.realized_pnl)


# ── Main check ────────────────────────────────────────────────────────────────

async def check_futures_positions() -> tuple[int, int]:
    """
    Check all open futures positions. Returns (closed, updated) counts.  # B3

    Enhanced checks (per cycle):
      1. Auto-close: SL or TP2 hit
      2. Liquidation guard: adaptive per-leverage threshold → close at SL
      3. Trail SL: breakeven + TP1 trail
      4. TP extension: if position is profitable + score stays high → extend to TP3
    """
    global _liq_guards, _tp_extended, _max_loss_closes, _derisk_partials

    if not is_db_available():
        return 0, 0   # B3: tuple — caller unpacks (closed, updated)

    closed  = 0
    updated = 0

    # G10: check if emergency tighten was requested by the risk gate (circuit breaker trip)
    from agents.futures.risk_gate import consume_emergency_tighten
    _do_emergency_tighten = consume_emergency_tighten()
    if _do_emergency_tighten:
        logger.warning("emergency_tighten_cycle_start",
                       msg="Circuit breaker tripped — tightening all open SLs")

    async with AsyncSessionLocal() as session:
        # Monitor all futures-type positions (including legacy styles)
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(list(_FUTURES_STYLES)),
                PaperTrade.status == "open",
            )
        )
        trades = list(result.scalars().all())

        if not trades:
            return 0, 0   # B3: tuple — caller unpacks (closed, updated)

        symbols = list({t.symbol for t in trades})
        # EC2: stale price guard — if fetch takes >30s (network stall / retry loop),
        # the prices could already be stale by the time we use them.  Skip the cycle
        # rather than fire a false SL/TP close on stale data.
        _pf_start = time.time()
        prices    = await _fetch_futures_prices(symbols)
        _pf_age   = time.time() - _pf_start
        if _pf_age > 30.0:
            logger.warning("monitor_stale_price_skipped",
                           age_sec=round(_pf_age, 1),
                           msg="price fetch took >30s — skipping cycle")
            return 0, 0

        # BC1: fetch wallet equity for cross-margin liq calculation
        _wallet_equity = FUTURES_STARTING_BALANCE
        _wallet_peak: float = FUTURES_STARTING_BALANCE  # P6.1: track peak for contagion
        try:
            _wb = (await session.execute(
                select(PaperBalance).where(PaperBalance.style == "futures")
            )).scalar_one_or_none()
            if _wb:
                _wallet_equity = max(_wb.balance, 0.0)
                _wallet_peak   = max(_wb.initial_balance + _wb.deposited_total - _wb.withdrawn_total,
                                     _wallet_equity)
        except Exception:
            pass

        # P6.1: Cross-margin contagion check — if wallet dropped >15% from peak in cycle
        # → force-close 50% of the single worst-loss position to stop bleed.
        _CONTAGION_DROP_PCT = 15.0
        if _wallet_peak > 0:
            _current_drop = (_wallet_peak - _wallet_equity) / _wallet_peak * 100
            if _current_drop > _CONTAGION_DROP_PCT and trades:
                # Find worst unrealized-loss trade (most negative pnl_pct)
                worst_trade = None
                worst_pnl   = 0.0
                for _t in trades:
                    _tp = prices.get(_t.symbol)
                    if _tp and _t.entry_price:
                        _u = (
                            (_tp - _t.entry_price) / _t.entry_price * 100
                            if _t.direction == "LONG"
                            else (_t.entry_price - _tp) / _t.entry_price * 100
                        )
                        if _u < worst_pnl:
                            worst_pnl  = _u
                            worst_trade = _t
                if worst_trade and worst_trade.position_size and worst_trade.position_size > 0:
                    _halved = round(worst_trade.position_size * 0.50, 2)
                    worst_trade.position_size = _halved
                    try:
                        _cmeta = json.loads(worst_trade.signals_json or "{}")
                    except Exception:
                        _cmeta = {}
                    _cmeta["contagion_derisked_at"]  = time.time()
                    _cmeta["contagion_drop_pct"]     = round(_current_drop, 2)
                    worst_trade.signals_json = json.dumps(_cmeta, ensure_ascii=False)
                    logger.warning(
                        "contagion_derisk",
                        symbol=worst_trade.symbol, direction=worst_trade.direction,
                        wallet_drop_pct=round(_current_drop, 2),
                        size_halved_to=_halved,
                    )

        # BC1: pre-compute unrealized PnL per trade (for cross-margin liq — other positions' losses)
        _unrealized: dict[int, float] = {}
        for _t in trades:
            _p = prices.get(_t.symbol)
            if _p and _t.entry_price and _t.position_size:
                if _t.direction == "LONG":
                    _u = (_p - _t.entry_price) / _t.entry_price * _t.position_size
                else:
                    _u = (_t.entry_price - _p) / _t.entry_price * _t.position_size
                _unrealized[_t.id] = _u
            else:
                _unrealized[_t.id] = 0.0

        # BUG-L8: fetch 1m klines so TP/SL touches between 2-min polls aren't missed
        klines_1m: dict[str, list] = {}
        async with httpx.AsyncClient(timeout=15) as _kc:
            _ktasks = {s: asyncio.create_task(_fetch_futures_klines_1m(_kc, s)) for s in symbols}
            for s in symbols:
                try:
                    klines_1m[s] = await _ktasks[s]
                except Exception:
                    klines_1m[s] = []

        # F88/F90: every 10 cycles fetch funding rates for signal degradation check
        funding_rates: dict[str, float] = {}
        if _cycle_count % 10 == 0:
            funding_rates = await _fetch_funding_rates(symbols)

        for trade in trades:
            price = prices.get(trade.symbol)
            if price is None:
                continue

            # BUG-L8: effective extremes since entry (wick low/high) — fall back to mark price
            wick_low, wick_high = _wick_extremes(
                klines_1m.get(trade.symbol, []), trade.entry_at or time.time()
            )
            eff_low  = min(price, wick_low)  if wick_low  is not None else price
            eff_high = max(price, wick_high) if wick_high is not None else price

            # PLAN_v2 P0 — init trade-level vars FIRST so downstream rules (G4 rugpull,
            # G5b profit lock, etc.) can reference them. Previously G4 read `meta` and
            # `direction` before they were assigned → UnboundLocalError on first cycle.
            try:
                meta = json.loads(trade.signals_json or "{}")
            except Exception:
                meta = {}

            entry        = trade.entry_price
            tp2          = trade.take_profit
            tp3          = meta.get("tp3")
            direction    = trade.direction
            leverage     = trade.leverage or meta.get("leverage", 5)
            trail_active = bool(trade.trail_active)

            # PLAN_v2 P1.1/P1.3/P1.5 — lane lookup (denormalised on the trade if
            # available, else derived from style). All per-lane gates read this.
            lane = trade.setup_type or meta.get("setup_type") or lane_for_style(trade.style)

            new_status:   Optional[str]   = None
            close_price:  Optional[float] = None
            close_reason: Optional[str]   = None

            # Unrealised P&L%, used by max-loss gate, profit lock, rotation.
            _pnl_now_pct = (
                (price - entry) / entry * 100 if direction == "LONG"
                else (entry - price) / entry * 100
            ) if entry > 0 else 0.0

            # ── PLAN_v2 P1.1 — Hard max-loss-per-trade gate ───────────────────
            # Caps drawdown on margin regardless of SL/liq guard latency. Runs
            # FIRST so a fast adverse move can't blow through to the slower rules.
            _max_loss_pct = MAX_LOSS_PCT_OF_MARGIN_BY_LANE.get(lane, DEFAULT_MAX_LOSS_PCT)
            if _pnl_now_pct < 0:
                _margin_loss_pct = abs(_pnl_now_pct) * max(leverage, 1)
                if _margin_loss_pct > _max_loss_pct:
                    new_status   = "sl"
                    close_price  = round(price, 8)
                    close_reason = "max_margin_loss"
                    _max_loss_closes += 1
                    _append_trade_event(meta, "max_margin_loss", {
                        "lane":             lane,
                        "leverage":         leverage,
                        "pnl_pct":          round(_pnl_now_pct, 3),
                        "margin_loss_pct":  round(_margin_loss_pct, 2),
                        "lane_cap":         _max_loss_pct,
                    })
                    trade.signals_json = json.dumps(meta, ensure_ascii=False)
                    logger.warning(
                        "max_margin_loss_close",
                        symbol=trade.symbol, lane=lane, leverage=leverage,
                        pnl_pct=round(_pnl_now_pct, 2),
                        margin_loss_pct=round(_margin_loss_pct, 1),
                        cap=_max_loss_pct,
                    )

            # ── G4: Flash dump / pump detection (B5.2: adaptive ATR threshold) ──
            # Detects sudden 5-minute violent moves that SL may not catch in time.
            # Guard: skip if P1.1 max-loss gate already closed this trade.
            _hold_mins_g4 = (time.time() - (trade.entry_at or time.time())) / 60
            if not new_status and _hold_mins_g4 >= RUGPULL_MIN_HOLD_MIN:
                _k1m_g4      = klines_1m.get(trade.symbol, [])
                _atr_pct_g4  = float(meta.get("atr_pct", 0.0) or 0.0)
                _rp_thresh   = _rugpull_threshold(_atr_pct_g4)
                _adverse_pct = _flash_adverse_pct(_k1m_g4, direction)
                if _adverse_pct > _rp_thresh * RUGPULL_CONFIRM_MULT:   # PLAN_v11 B3: butuh konfirmasi jelas
                    new_status   = "sl"
                    close_price  = round(price, 8)
                    close_reason = "flash_dump_exit" if direction == "LONG" else "flash_pump_exit"
                    logger.warning(
                        "rugpull_detected",
                        symbol=trade.symbol, direction=direction,
                        adverse_pct=round(_adverse_pct, 2), threshold=round(_rp_thresh, 2),
                        atr_pct=_atr_pct_g4,
                    )

            # F83: direction-aware tp1 fallback — explicit midpoint per direction
            if meta.get("tp1"):
                tp1 = float(meta["tp1"])
            elif direction == "LONG":
                tp1 = entry + (tp2 - entry) * 0.5
            else:  # SHORT: tp2 < entry
                tp1 = entry - (entry - tp2) * 0.5

            # F79: regime-based SL adjustment on first check (before any SL read)
            if not new_status and not trail_active and not meta.get("regime_sl_adjusted"):
                _did_widen = False
                try:
                    from agents.futures.regime import get_cached_regime
                    _regime  = get_cached_regime()
                    _atr_pct = meta.get("atr_pct") or 0
                    if _atr_pct > 0:
                        _atr_dist = entry * (_atr_pct / 100)
                        if _regime == "volatile":
                            # widen SL away from entry to absorb noise
                            if direction == "LONG":
                                trade.stop_loss = round(trade.stop_loss - _atr_dist * 0.5, 8)
                            else:
                                trade.stop_loss = round(trade.stop_loss + _atr_dist * 0.5, 8)
                            _did_widen = True
                        # ranging: keep SL unchanged — tightening caused premature SL hits from range oscillation
                except Exception:
                    pass
                meta["regime_sl_adjusted"] = True

                # ── PLAN_v2 P1.5 — F79 widening de-risk ───────────────────────
                # If the new SL distance × current leverage exceeds the lane cap,
                # shrink the position by 30% so the sizing assumption still holds
                # after the regime widened our stop.
                if _did_widen and trade.position_size and trade.position_size > 0:
                    _new_sl_dist_pct = abs(entry - trade.stop_loss) / entry * 100 if entry > 0 else 0.0
                    _implied_loss   = _new_sl_dist_pct * max(leverage, 1)
                    _lane_sl_cap    = MAX_SL_MARGIN_PCT_BY_LANE.get(lane, DEFAULT_LANE_CAP)
                    if _implied_loss > _lane_sl_cap:
                        _orig_size = trade.position_size
                        trade.position_size = round(_orig_size * 0.70, 2)
                        _derisk_partials += 1
                        _append_trade_event(meta, "regime_derisk_partial", {
                            "lane":             lane,
                            "leverage":         leverage,
                            "new_sl_dist_pct":  round(_new_sl_dist_pct, 2),
                            "implied_loss_pct": round(_implied_loss, 1),
                            "lane_cap":         _lane_sl_cap,
                            "size_before":      round(_orig_size, 2),
                            "size_after":       round(trade.position_size, 2),
                        })
                        logger.warning(
                            "regime_derisk_partial",
                            symbol=trade.symbol, lane=lane, leverage=leverage,
                            new_sl_dist_pct=round(_new_sl_dist_pct, 2),
                            implied_loss=round(_implied_loss, 1),
                            cap=_lane_sl_cap,
                            size_before=round(_orig_size, 2),
                            size_after=round(trade.position_size, 2),
                        )

                trade.signals_json = json.dumps(meta, ensure_ascii=False)
                updated += 1

            sl = trade.trail_sl or trade.stop_loss   # read AFTER potential F79 adjustment

            # ── G5b: Absolute profit lock — prevent large give-back from peak ──
            # _pnl_now_pct was already computed at the top of the trade loop
            # (PLAN_v2 P1.1 needs it for the max-loss gate).
            _peak_pnl = float(meta.get("peak_pnl_pct", 0.0))
            if _pnl_now_pct > _peak_pnl:
                _peak_pnl = round(_pnl_now_pct, 3)
                meta["peak_pnl_pct"] = _peak_pnl
                trade.signals_json   = json.dumps(meta, ensure_ascii=False)
                updated += 1
            for _peak_thresh, _lock_frac in _PROFIT_LOCK_TIERS:
                if not new_status and _peak_pnl >= _peak_thresh and _pnl_now_pct <= _peak_pnl * _lock_frac:
                    new_status   = "tp"
                    close_price  = round(price, 8)
                    close_reason = "absolute_profit_lock"
                    logger.info(
                        "absolute_profit_lock",
                        symbol=trade.symbol, direction=direction,
                        peak_pnl=round(_peak_pnl, 2), current_pnl=round(_pnl_now_pct, 2),
                        threshold=_peak_thresh, lock_frac=_lock_frac,
                    )
                    break

            # ── 0. Max age check (G11: adaptive — extend for profitable trailing) ──
            age_days = (time.time() - (trade.entry_at or 0)) / 86400
            _age_ext  = int(meta.get("age_extensions", 0))
            _max_age  = MAX_AGE_DAYS + min(_age_ext, MAX_AGE_EXTENSIONS)
            # G11 + B6.3: grant 1-day extension when at boundary, in profit, trailing,
            # and 1h momentum still aligned (proxied by pnl ≥ 5%).
            if (not new_status
                    and trail_active
                    and _pnl_now_pct >= 5.0
                    and _age_ext < MAX_AGE_EXTENSIONS
                    and age_days >= (_max_age - 0.1)):   # within ~2.4 h of expiry
                _last_ext = float(meta.get("age_last_extended_at", 0.0))
                if (time.time() - _last_ext) >= 20 * 3600:   # one extension per day
                    meta["age_extensions"]       = _age_ext + 1
                    meta["age_last_extended_at"] = time.time()
                    trade.signals_json           = json.dumps(meta, ensure_ascii=False)
                    updated    += 1
                    _age_ext   += 1
                    _max_age    = MAX_AGE_DAYS + _age_ext
                    logger.info("age_extended_g11", symbol=trade.symbol,
                                extensions=_age_ext, pnl=round(_pnl_now_pct, 2))
            if not new_status and age_days > _max_age:
                new_status   = "expired"
                close_price  = round(price, 8)
                close_reason = "max_age_expired"

            # ── 0a-. PLAN_v6 P1c: momentum time-stop (scratch exit) ───────────
            # If the trade never hit TP1 (trail inactive) and hasn't moved
            # ≥0.5×risk in our favour within the lane's time budget, the thesis
            # failed — scratch it at market instead of waiting for full SL.
            if not new_status and not trail_active:
                _ts_min = TIME_STOP_MIN_BY_LANE.get(lane)
                if _ts_min:
                    _hold_min = (time.time() - (trade.entry_at or time.time())) / 60
                    if _hold_min >= _ts_min:
                        _risk_dist = abs(entry - (trade.stop_loss or entry))
                        _fav = (price - entry) if direction == "LONG" else (entry - price)
                        # PLAN_v11 B2: scratch HANYA saat stagnan (fav antara −0.5×risk
                        # dan +0.5×risk). Loser lebih dalam → biar SL asli, jangan
                        # realisasi loss besar berlabel "scratch".
                        _stagnant = (_risk_dist > 0
                                     and _fav < TIME_STOP_PROGRESS_FRAC * _risk_dist
                                     and _fav > -TIME_STOP_LOSS_GUARD_FRAC * _risk_dist)
                        if _stagnant:
                            new_status   = "tp" if _pnl_now_pct > (ROUND_TRIP * 100) else "sl"
                            close_price  = round(price, 8)
                            close_reason = "time_stop_scratch"
                            _append_trade_event(meta, "time_stop_scratch", {
                                "lane":         lane,
                                "hold_min":     round(_hold_min, 1),
                                "pnl_pct":      round(_pnl_now_pct, 3),
                                "fav_frac_risk": round(_fav / _risk_dist, 2) if _risk_dist else 0,
                            })
                            trade.signals_json = json.dumps(meta, ensure_ascii=False)
                            logger.info(
                                "time_stop_scratch",
                                symbol=trade.symbol, lane=lane,
                                hold_min=round(_hold_min, 1), pnl_pct=round(_pnl_now_pct, 2),
                            )

            # ── 0a. Stagnant 48h check (F80) ─────────────────────────────────
            if not new_status and age_days > 2.0:
                _progress = 0.0
                if direction == "LONG" and tp1 > entry:
                    _progress = (price - entry) / (tp1 - entry) * 100 if price > entry else 0.0
                elif direction == "SHORT" and tp1 < entry:
                    _progress = (entry - price) / (entry - tp1) * 100 if price < entry else 0.0
                if _progress < 20.0:
                    new_status   = "expired"
                    close_price  = round(price, 8)
                    close_reason = "stagnant_48h"

            # ── 0a1. G8: Stagnant post-TP1 — free capital from stuck trailing pos ──
            # trail_active means TP1 was hit; if price stalls ≥ 24h at trail SL
            # level without advancing → close at trail SL to free the capital.
            if not new_status and trail_active:
                _tp1_done_g8 = float(meta.get("tp1_done_at", 0.0))
                _hold_tp1_h  = (time.time() - _tp1_done_g8) / 3600 if _tp1_done_g8 > 0 else 0.0
                if _hold_tp1_h >= 24.0:
                    _stuck = (
                        (direction == "LONG"  and price <= sl * 1.02) or
                        (direction == "SHORT" and price >= sl * 0.98)
                    )
                    if _stuck:
                        new_status   = "tp"   # TP1 was booked, net profitable
                        close_price  = round(sl, 8)
                        close_reason = "stagnant_post_tp1"
                        logger.info(
                            "stagnant_post_tp1",
                            symbol=trade.symbol, direction=direction,
                            hold_tp1_h=round(_hold_tp1_h, 1),
                            price=round(price, 6), sl=round(sl, 6),
                        )

            # ── 0b. PLAN_v11 P3 — UNBOUNDED dynamic TP ladder (TP4..TP-n) ─────
            # Ride winner tanpa cap: tiap kali harga menembus target sekarang &
            # gate masih kuat (score≥65), geser target +1 step DAN ratchet trail
            # SL ke target sebelumnya. Profit yang lewat terkunci (tak hilang) —
            # winner leverage bisa lari sampai TP-n / 1000%. (Dulu berhenti di TP4.)
            if not new_status and meta.get("tp_extended"):
                _rung_hit = (direction == "LONG" and eff_high >= tp2) or \
                            (direction == "SHORT" and eff_low <= tp2)
                if _rung_hit:
                    _cur_score4 = 0
                    try:
                        from agents.futures import store as futures_store
                        _cur4 = futures_store.get_result(trade.style)
                        if _cur4:
                            for _r4 in _cur4.get("results", []):
                                if _r4.get("symbol") == trade.symbol and \
                                   _r4.get("direction") == direction:
                                    _cur_score4 = _r4.get("score", 0)
                                    break
                    except Exception:
                        pass
                    _score4   = _cur_score4 or (trade.probability or 0)
                    _orig_tp2 = float(meta.get("tp2") or 0)
                    # step ladder konsisten: jarak TP3→TP2 asli (fallback TP2→TP1)
                    _step = float(meta.get("tp_ladder_step", 0.0))
                    if _step <= 0:
                        _step = abs(tp2 - _orig_tp2) if _orig_tp2 > 0 else abs(tp2 - tp1)
                    if _score4 >= 65 and _step > 0:
                        _prev_target = tp2
                        _next = round(_prev_target + _step, 8) if direction == "LONG" \
                                else round(_prev_target - _step, 8)
                        trade.take_profit = _next
                        tp2               = _next   # step 1 lihat target baru
                        # ratchet trail ke target sebelumnya — lock profit (monoton naik)
                        _lock = round(_prev_target, 8)
                        if (not trail_active
                                or (direction == "LONG"  and (trade.trail_sl or 0.0)  < _lock)
                                or (direction == "SHORT" and (trade.trail_sl or 1e18) > _lock)):
                            trade.trail_sl     = _lock
                            trade.trail_active = True
                            trail_active       = True
                            sl                 = _lock
                        _rung = int(meta.get("tp_rung", 3)) + 1
                        meta["tp_rung"]        = _rung
                        meta["tp_ladder_step"] = _step
                        meta["tp4_extended"]   = True   # kompat label tp4_hit di step 1
                        trade.signals_json     = json.dumps(meta, ensure_ascii=False)
                        _tp_extended += 1
                        updated      += 1
                        logger.info(
                            "tp_ladder_extended",
                            symbol=trade.symbol, direction=direction, rung=_rung,
                            new_target=round(_next, 6), sl_locked=round(_lock, 6), score=_score4,
                        )

            # ── 1. Auto-close: SL or TP2 hit (BUG-L8: wick-aware; SL wins if both) ──
            if not new_status:
                if direction == "LONG":
                    if eff_low <= sl:
                        new_status   = "sl"
                        close_price  = sl
                        # F114: SL trail moved above entry → close at profit, label as sl_plus
                        _pnl_chk = (sl - entry) / entry * 100 if entry > 0 else 0
                        # PLAN-SIGNAL-GAP F4: SL sitting exactly at the breakeven trail stage
                        # (entry, before the post-TP1 75% lock) is not a real loss — it's the
                        # trail protecting capital. Distinguish it from a genuine SL hit so the
                        # history table doesn't show it as a full 1.5%+ loss.
                        _is_breakeven = trail_active and entry > 0 and abs(sl - entry) / entry < 0.001
                        if trail_active and _pnl_chk > 0:
                            close_reason = "sl_plus"
                        elif _is_breakeven:
                            close_reason = "breakeven_stop"
                        else:
                            close_reason = "sl_hit"
                    elif eff_high >= tp2:
                        new_status   = "tp"
                        close_price  = tp2
                        # PLAN-SIGNAL-GAP F2: tp2 here is trade.take_profit, which can already
                        # be the extended TP3 level (see TP Extension below) — was hardcoded
                        # "tp2_hit" even when the level actually hit was the extended TP3.
                        if meta.get("tp4_extended"):
                            # PLAN_v12 P3: rung >4 → label ladder (bukan "TP4" untuk semua)
                            close_reason = "tp_ladder_hit" if int(meta.get("tp_rung", 4)) > 4 else "tp4_hit"
                        elif meta.get("tp_extended"):
                            close_reason = "tp3_hit"
                        else:
                            close_reason = "tp2_hit"
                else:  # SHORT
                    if eff_high >= sl:
                        new_status   = "sl"
                        close_price  = sl
                        # F114: SL trail moved below entry → close at profit, label as sl_plus
                        _pnl_chk = (entry - sl) / entry * 100 if entry > 0 else 0
                        # PLAN-SIGNAL-GAP F4: mirror of LONG breakeven detection above.
                        _is_breakeven = trail_active and entry > 0 and abs(sl - entry) / entry < 0.001
                        if trail_active and _pnl_chk > 0:
                            close_reason = "sl_plus"
                        elif _is_breakeven:
                            close_reason = "breakeven_stop"
                        else:
                            close_reason = "sl_hit"
                    elif eff_low <= tp2:
                        new_status   = "tp"
                        close_price  = tp2
                        # PLAN-SIGNAL-GAP F2: mirror of LONG tp3_hit fix above.
                        if meta.get("tp4_extended"):
                            # PLAN_v12 P3: rung >4 → label ladder (bukan "TP4" untuk semua)
                            close_reason = "tp_ladder_hit" if int(meta.get("tp_rung", 4)) > 4 else "tp4_hit"
                        elif meta.get("tp_extended"):
                            close_reason = "tp3_hit"
                        else:
                            close_reason = "tp2_hit"

            # ── 2. Liquidation guard (F85: adaptive threshold per leverage) ───
            if not new_status:
                # BC1: cross-margin liq — other positions' losses reduce effective wallet buffer
                _other_loss = sum(v for k, v in _unrealized.items() if k != trade.id and v < 0)
                liq        = _calc_liq_price(
                    entry, leverage, direction,
                    position_size   = trade.position_size or 0.0,
                    wallet_equity   = _wallet_equity,
                    other_open_loss = _other_loss,
                )
                d_pct      = _liq_dist_pct(price, liq, direction)
                guard_pct  = _liq_guard_pct(leverage)  # F85: was fixed 8.0
                if d_pct < guard_pct:
                    new_status   = "sl"
                    # BUG-L16: close at the current (near-liquidation) price, not the far-away
                    # SL — using sl understated the loss when price had blown past it toward liq.
                    close_price  = round(price, 8)
                    close_reason = "liq_guard"
                    _liq_guards += 1
                    logger.warning(
                        "liq_guard_triggered",
                        symbol=trade.symbol, direction=direction,
                        price=price, liq=round(liq, 6),
                        dist_pct=round(d_pct, 2), guard_pct=guard_pct,
                    )

            if new_status and close_price:
                # BC4: use Decimal for price math to avoid IEEE 754 drift over many trades.
                _entry_d = Decimal(str(entry))
                _close_d = Decimal(str(close_price))
                # Fee-aware P&L: 0.05% entry + 0.05% exit = 0.10% round trip
                pnl_gross = (
                    (_close_d - _entry_d) / _entry_d * 100
                    if direction == "LONG"
                    else (_entry_d - _close_d) / _entry_d * 100
                )
                pnl_net = pnl_gross - Decimal(str(ROUND_TRIP * 100))
                try:
                    meta["close_reason"]  = close_reason
                    meta["pnl_gross_pct"] = float(round(pnl_gross, 2))
                    meta["fee_pct"]       = round(ROUND_TRIP * 100, 2)
                    trade.signals_json    = json.dumps(meta, ensure_ascii=False)
                except Exception:
                    pass
                _risk_pct_meta  = meta.get("risk_pct") or 2.0
                # Phase 9: dollars off the trade's REAL notional (balance-aware at open);
                # fall back to the constant-based notional only for legacy rows.
                _notional_close = trade.position_size or futures_notional(_risk_pct_meta)
                _notional_d     = Decimal(str(_notional_close))
                # F76/BUG-L17: partial sold at TP1 (25% or 33%). New rows shrank position_size
                # to the remaining fraction (tp1_size_reduced) → no extra multiplier needed.
                # Legacy rows kept full size → derive remainder from stored tp1_partial_frac.
                if meta.get("tp1_partial_done"):
                    _partial_pnl  = meta.get("tp1_partial_pnl_dollar", 0.0)
                    _mid_pnl      = meta.get("tp2_partial_pnl_dollar", 0.0)  # P5.2
                    _all_partials = _partial_pnl + _mid_pnl
                    if meta.get("tp1_size_reduced"):
                        _rem = Decimal("1.0")
                    else:
                        # Legacy rows: use stored fraction (default 0.33 if missing)
                        _frac = float(meta.get("tp1_partial_frac", 0.33))
                        _rem  = Decimal(str(round(1.0 - _frac, 4)))
                    _final_pnl   = float(round(pnl_net / 100 * _notional_d * _rem, 2))
                    _total_pnl   = float(round(Decimal(str(_all_partials)) + Decimal(str(_final_pnl)), 2))
                else:
                    _total_pnl = float(round(pnl_net / 100 * _notional_d, 2))
                trade.status      = new_status
                trade.close_price = close_price
                trade.closed_at   = time.time()
                trade.pnl_pct     = float(round(pnl_net, 2))
                trade.pnl_dollar  = _total_pnl
                closed += 1
                logger.info(
                    "futures_position_closed",
                    symbol=trade.symbol, direction=direction,
                    status=new_status, reason=close_reason,
                    entry=entry, close=close_price,
                    pnl_gross=round(pnl_gross, 2),
                    pnl_net=round(pnl_net, 2),
                    pnl_dollar=_total_pnl,
                    agent=trade.style,
                )
                continue

            # ── 3. Trail SL (P5.1: lane-specific breakeven + F77 TP1→TP2 lock) ──
            new_sl, now_active, event = _compute_trail(
                direction, entry, sl, tp1, tp2, price, trail_active, setup_type=lane
            )
            if new_sl is not None:
                trade.trail_sl     = round(new_sl, 8)
                trade.trail_active = now_active
                updated += 1
                logger.info(
                    "futures_sl_trailed",
                    symbol=trade.symbol, direction=direction,
                    sl_event=event, old_sl=round(sl, 8), new_sl=round(new_sl, 8),
                    price=price,
                )

            # ── 3a. TP1 Partial Close (P5.2: accumulation 25% / others 33%) ──────
            if not meta.get("tp1_partial_done"):
                _tp1_hit = (direction == "LONG" and eff_high >= tp1) or \
                           (direction == "SHORT" and eff_low <= tp1)
                if _tp1_hit:
                    # P5.2: accumulation uses 25% partial (saves more for multi-tier runner)
                    _partial_frac = Decimal("0.25") if lane == "accumulation" else Decimal("0.33")
                    # BC4: Decimal for partial TP1 dollar calculation
                    _tp1_d   = Decimal(str(tp1))
                    _entry_p = Decimal(str(entry))
                    _partial_pnl_pct = (
                        (_tp1_d - _entry_p) / _entry_p * 100 if direction == "LONG"
                        else (_entry_p - _tp1_d) / _entry_p * 100
                    )
                    _partial_net     = _partial_pnl_pct - Decimal(str(ROUND_TRIP * 100 * 0.5))
                    _rp              = meta.get("risk_pct") or 2.0
                    # Phase 9: real notional from the trade; fallback for legacy rows
                    _notional_p      = trade.position_size or futures_notional(_rp)
                    _partial_dollar  = float(round(_partial_net / 100 * Decimal(str(_notional_p)) * _partial_frac, 2))
                    meta["tp1_partial_done"]       = True
                    meta["tp1_partial_pnl_dollar"] = _partial_dollar
                    meta["tp1_size_reduced"]       = True   # BUG-L17 marker (see close-apply)
                    meta["tp1_done_at"]            = time.time()  # G3/B5.1: rotation eligibility timestamp
                    meta["tp1_partial_frac"]       = float(_partial_frac)
                    trade.pnl_dollar               = (trade.pnl_dollar or 0.0) + _partial_dollar
                    # BUG-L17: shrink stored notional to the sold remainder
                    _remaining = float(1 - _partial_frac)
                    trade.position_size            = round(_notional_p * _remaining, 2)
                    trade.signals_json             = json.dumps(meta, ensure_ascii=False)
                    updated += 1
                    logger.info(
                        "tp1_partial_close",
                        symbol=trade.symbol, direction=direction,
                        partial_frac=float(_partial_frac),
                        partial_pnl_dollar=_partial_dollar,
                        tp1=round(tp1, 6), price=price, lane=lane,
                    )

            # ── 3b. P5.2: Accumulation second partial at TP1→TP2 midpoint ────────
            if (not meta.get("tp2_partial_done")
                    and meta.get("tp1_partial_done")
                    and lane == "accumulation"
                    and tp2 and tp1):
                _midtp = (tp1 + tp2) / 2
                _tp2_partial_hit = (
                    (direction == "LONG"  and eff_high >= _midtp) or
                    (direction == "SHORT" and eff_low  <= _midtp)
                )
                if _tp2_partial_hit and not new_status:
                    _mid_d      = Decimal(str(_midtp))
                    _entry_p2   = Decimal(str(entry))
                    _mid_pnl    = (
                        (_mid_d - _entry_p2) / _entry_p2 * 100 if direction == "LONG"
                        else (_entry_p2 - _mid_d) / _entry_p2 * 100
                    )
                    _mid_net    = _mid_pnl - Decimal(str(ROUND_TRIP * 100 * 0.5))
                    _notional_p2 = trade.position_size or futures_notional(meta.get("risk_pct") or 2.0)
                    _mid_dollar  = float(round(_mid_net / 100 * Decimal(str(_notional_p2)) * Decimal("0.333"), 2))
                    meta["tp2_partial_done"]        = True
                    meta["tp2_partial_pnl_dollar"]  = _mid_dollar
                    trade.pnl_dollar                = (trade.pnl_dollar or 0.0) + _mid_dollar
                    trade.position_size             = round(_notional_p2 * 0.667, 2)
                    trade.signals_json              = json.dumps(meta, ensure_ascii=False)
                    updated += 1
                    logger.info(
                        "tp2_partial_close_accumulation",
                        symbol=trade.symbol, direction=direction,
                        partial_dollar=_mid_dollar, midtp=round(_midtp, 6),
                    )

            # ── F88/F90: funding rate degradation → tighten SL to breakeven ──────
            if (not new_status
                    and funding_rates
                    and not meta.get("sl_tightened_degradation")):
                _cur_fr = funding_rates.get(trade.symbol, 0.0)
                _entry_fr = float(meta.get("funding_rate") or 0.0)  # % at trade open
                _degraded = False
                if direction == "LONG" and _entry_fr <= 0 and _cur_fr > 0.05:
                    _degraded = True  # funding flipped positive — longs now crowded
                elif direction == "SHORT" and _entry_fr >= 0 and _cur_fr < -0.03:
                    _degraded = True  # funding flipped negative — shorts now crowded
                if _degraded:
                    trade.trail_sl     = round(entry, 8)
                    trade.trail_active = True
                    meta["sl_tightened_degradation"] = True
                    trade.signals_json = json.dumps(meta, ensure_ascii=False)
                    updated += 1
                    logger.info(
                        "sl_tightened_funding_degradation",
                        symbol=trade.symbol, direction=direction,
                        entry_fr=_entry_fr, cur_fr=_cur_fr,
                    )

            # ── G6+G15: Cumulative funding + fee cost tracker (B5.3) ──────────
            # Runs when funding_rates is available (every 10 cycles).
            # Accumulates simulated funding cost per 8h window + round-trip fee.
            if not new_status and funding_rates:
                _cur_fr  = funding_rates.get(trade.symbol, 0.0)
                _notional_g6 = (trade.position_size or 0.0)
                if _notional_g6 > 0:
                    # G15: set cumulative_fee_paid once at first accrual (ROUND_TRIP × notional)
                    if not meta.get("cumulative_fee_paid"):
                        meta["cumulative_fee_paid"] = round(ROUND_TRIP * _notional_g6, 4)

                    # G6: accrue funding cost for elapsed 8h windows since last accrual
                    _now_ts       = int(time.time())
                    _last_fund_at = int(meta.get("last_funding_at", trade.entry_at or _now_ts))
                    _windows      = int((_now_ts - _last_fund_at) / FUNDING_WINDOW_SEC)
                    if _windows > 0:
                        # Cost = funding_rate_pct × windows × notional (BC4: Decimal for precision)
                        _fund_cost_d = (Decimal(str(abs(_cur_fr))) / 100
                                        * Decimal(str(_windows))
                                        * Decimal(str(_notional_g6)))
                        meta["cumulative_funding_paid"] = float(round(
                            Decimal(str(meta.get("cumulative_funding_paid", 0.0))) + _fund_cost_d, 4
                        ))
                        # Align last_funding_at to the most recent 8h window boundary
                        meta["last_funding_at"] = _now_ts - (_now_ts % FUNDING_WINDOW_SEC)
                        trade.signals_json = json.dumps(meta, ensure_ascii=False)
                        updated += 1

                    # B5.3 fix: apply cost gate only in meaningful cases
                    _cum_cost = float(meta.get("cumulative_funding_paid", 0.0)) + \
                                float(meta.get("cumulative_fee_paid", 0.0))
                    _pnl_dollar_now = _pnl_now_pct / 100 * _notional_g6  # uses G5b var
                    if _pnl_dollar_now > 0 and _cum_cost > _pnl_dollar_now * COST_TO_PROFIT_GATE:
                        # Profitable but costs eating >30% of unrealized → exit now
                        new_status   = "tp"
                        close_price  = round(price, 8)
                        close_reason = "cost_exceeds_profit"
                        logger.info(
                            "cost_gate_profit",
                            symbol=trade.symbol, cum_cost=round(_cum_cost, 4),
                            unrealized=round(_pnl_dollar_now, 4),
                        )
                    elif _pnl_dollar_now <= 0 and _cum_cost > _notional_g6 * COST_ABS_LOSS_GATE_PCT:
                        # B5.3: losing AND paying significant funding → too expensive to hold
                        new_status   = "sl"
                        close_price  = round(price, 8)
                        close_reason = "cost_exceeds_loss_threshold"
                        logger.info(
                            "cost_gate_loss",
                            symbol=trade.symbol, cum_cost=round(_cum_cost, 4),
                            unrealized=round(_pnl_dollar_now, 4),
                        )

                    # ── G9 + B6.2: Funding-window exit ────────────────────────
                    # 5 min before 00:00/08:00/16:00 UTC: if expected funding cost
                    # consumes >30% of thin unrealized profit → exit early.
                    if not new_status:
                        _now_ts2       = int(time.time())
                        _next_fund_ts  = (_now_ts2 // FUNDING_WINDOW_SEC + 1) * FUNDING_WINDOW_SEC
                        _mins_to_fund  = (_next_fund_ts - _now_ts2) / 60
                        if 0 < _mins_to_fund <= 5:
                            _exp_fund_cost = abs(_cur_fr) / 100 * _notional_g6
                            _unr_dollar    = _pnl_dollar_now  # reuse B5.3 var
                            _fund_too_costly = (
                                _unr_dollar > 0
                                and _exp_fund_cost > 0
                                and (_exp_fund_cost / _unr_dollar) > 0.30
                            )
                            if _fund_too_costly:
                                if direction == "LONG" and _cur_fr > 0.1:
                                    new_status   = "tp"
                                    close_price  = round(price, 8)
                                    close_reason = "funding_window_exit"
                                    logger.info(
                                        "funding_window_exit",
                                        symbol=trade.symbol, direction=direction,
                                        funding_rate=round(_cur_fr, 4),
                                        exp_cost=round(_exp_fund_cost, 4),
                                        unr_profit=round(_unr_dollar, 4),
                                        mins_to_fund=round(_mins_to_fund, 1),
                                    )
                                elif direction == "SHORT" and _cur_fr < -0.1:
                                    new_status   = "tp"
                                    close_price  = round(price, 8)
                                    close_reason = "funding_window_exit"
                                    logger.info(
                                        "funding_window_exit",
                                        symbol=trade.symbol, direction=direction,
                                        funding_rate=round(_cur_fr, 4),
                                        exp_cost=round(_exp_fund_cost, 4),
                                        unr_profit=round(_unr_dollar, 4),
                                        mins_to_fund=round(_mins_to_fund, 1),
                                    )

            # ── G3: Futures rotation (B5.1: also rotate trail_active stuck post-TP1) ──
            if not new_status:
                _age_g3    = (time.time() - (trade.entry_at or 0)) / 86400
                _drift_pct = abs(price - entry) / entry * 100 if entry > 0 else 99.0
                if _age_g3 >= FUTURES_ROTATION_MIN_DAYS:
                    # B5.1: trail_active stuck since TP1 for 48h+ is also rotate-eligible
                    _tp1_done_at = float(meta.get("tp1_done_at", 0.0))
                    _trail_stagnant_post_tp1 = (
                        trail_active
                        and _tp1_done_at > 0
                        and (time.time() - _tp1_done_at) > 48 * 3600
                        and _drift_pct <= FUTURES_ROTATION_DRIFT_PCT
                    )
                    _plain_stagnant = (not trail_active) and _drift_pct <= FUTURES_ROTATION_DRIFT_PCT
                    if _plain_stagnant or _trail_stagnant_post_tp1:
                        _cur_score_g3 = trade.probability or 60
                        if _futures_has_better_candidate(_cur_score_g3, trade.symbol, trade.style):
                            pnl_rot      = _pnl_now_pct  # reuse G5b var
                            new_status   = "tp" if pnl_rot > 0 else "sl"
                            close_price  = round(price, 8)
                            close_reason = "rotation_stagnant"
                            logger.info(
                                "futures_rotation_triggered",
                                symbol=trade.symbol, direction=direction,
                                drift_pct=round(_drift_pct, 2),
                                age_days=round(_age_g3, 1),
                                trail_stagnant=_trail_stagnant_post_tp1,
                                pnl_pct=round(pnl_rot, 2),
                            )

            # ── G10: Emergency tighten / close on circuit breaker (B5.4) ────────
            if not new_status and _do_emergency_tighten and not meta.get("emergency_sl_tightened"):
                if direction == "LONG":
                    if price > entry:
                        # In profit: tighten SL to entry (protect breakeven)
                        trade.trail_sl     = round(entry, 8)
                        trade.trail_active = True
                        sl = entry
                        meta["emergency_sl_tightened"] = True
                        trade.signals_json = json.dumps(meta, ensure_ascii=False)
                        updated += 1
                        logger.warning("emergency_tighten_sl", symbol=trade.symbol,
                                      direction=direction, new_sl=round(entry, 6))
                    else:
                        # In loss: close at market immediately
                        new_status   = "sl"
                        close_price  = round(price, 8)
                        close_reason = "emergency_close_circuit_breaker"
                        logger.warning("emergency_close_position", symbol=trade.symbol,
                                      direction=direction, entry=entry, price=price)
                else:  # SHORT
                    if price < entry:
                        trade.trail_sl     = round(entry, 8)
                        trade.trail_active = True
                        sl = entry
                        meta["emergency_sl_tightened"] = True
                        trade.signals_json = json.dumps(meta, ensure_ascii=False)
                        updated += 1
                        logger.warning("emergency_tighten_sl", symbol=trade.symbol,
                                      direction=direction, new_sl=round(entry, 6))
                    else:
                        new_status   = "sl"
                        close_price  = round(price, 8)
                        close_reason = "emergency_close_circuit_breaker"
                        logger.warning("emergency_close_position", symbol=trade.symbol,
                                      direction=direction, entry=entry, price=price)

            # ── 4. TP Extension (F81: lock SL at TP1; F84: use current score) ──
            if tp3 and not meta.get("tp_extended"):
                tp1_hit = (direction == "LONG" and eff_high >= tp1) or \
                          (direction == "SHORT" and eff_low <= tp1)
                if tp1_hit:
                    # F84: prefer current score from store over stale entry score
                    _cur_score = 0
                    try:
                        from agents.futures import store as futures_store
                        _cur = futures_store.get_result(trade.style)
                        if _cur:
                            for _r in _cur.get("results", []):
                                if _r.get("symbol") == trade.symbol and \
                                   _r.get("direction") == direction:
                                    _cur_score = _r.get("score", 0)
                                    break
                    except Exception:
                        pass
                    score = _cur_score or (trade.probability or 0)
                    if score >= 65:   # PLAN_v11 P3: 70→65 — biar ladder benar-benar aktif (dulu "TP Extended: 0")
                        trade.take_profit = tp3
                        # F81: lock SL at TP1 when extending to TP3
                        _curr_trail = trade.trail_sl or 0.0
                        if not trail_active or \
                           (direction == "LONG" and _curr_trail < tp1) or \
                           (direction == "SHORT" and _curr_trail > tp1):
                            trade.trail_sl     = round(tp1, 8)
                            trade.trail_active = True
                        meta["tp_extended"] = True
                        trade.signals_json  = json.dumps(meta, ensure_ascii=False)
                        _tp_extended += 1
                        updated += 1
                        logger.info(
                            "tp_extended_to_tp3",
                            symbol=trade.symbol, direction=direction,
                            old_tp2=tp2, new_tp3=tp3, score=score,
                            sl_locked_at=round(tp1, 6),
                        )

            # ── P5.4: flag high-risk trades for fast loop (30s checks) ──────────
            _margin_loss_pct_now = abs(_pnl_now_pct) * max(leverage, 1) if _pnl_now_pct < 0 else 0.0
            _is_high_risk = (
                leverage >= 10 or
                _margin_loss_pct_now >= 30.0 or
                (not new_status and _liq_dist_pct(price, _calc_liq_price(entry, leverage, direction,
                    position_size=trade.position_size or 0.0,
                    wallet_equity=_wallet_equity), direction) < 10.0)
            )
            if _is_high_risk and not new_status:
                _fast_loop_trade_ids.add(trade.id)
            elif trade.id in _fast_loop_trade_ids:
                _fast_loop_trade_ids.discard(trade.id)

            # ── PLAN_v2 P1.4 — per-trade heartbeat ────────────────────────────
            # Always written, even when nothing else changed, so the UI can prove
            # the monitor is alive for THIS position (not just the aggregate state).
            _now_hb = time.time()
            trade.last_tick_at      = _now_hb
            trade.last_tick_price   = round(price, 8)
            trade.last_tick_pnl_pct = round(_pnl_now_pct, 3)
            if close_reason:
                trade.last_tick_event = close_reason
            elif new_status:
                trade.last_tick_event = new_status
            else:
                trade.last_tick_event = "tick"
            # Backfill denormalised setup_type for legacy rows that opened pre-Phase-1.
            if not trade.setup_type:
                trade.setup_type = lane

        if closed > 0 or updated > 0 or trades:
            await session.commit()

    return closed, updated   # B3: return tuple so caller can track closes separately


# ── P5.4: Fast loop for high-risk positions ──────────────────────────────────

async def _run_fast_loop() -> None:
    """
    P5.4: Every 30s, re-check only positions flagged as high-risk (lev≥10, liq_dist<10%,
    margin_loss>30%). Only runs SL/max-loss/liq-guard checks — skips regime, TP extension,
    rotation to keep overhead low. Called concurrently from run_futures_monitor.
    """
    await asyncio.sleep(STARTUP_DELAY + 30)   # stagger to avoid startup race
    while True:
        await asyncio.sleep(FAST_INTERVAL_SEC)
        if not _fast_loop_trade_ids:
            continue
        try:
            trade_ids = list(_fast_loop_trade_ids)
            if not is_db_available():
                continue
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(PaperTrade).where(
                        PaperTrade.id.in_(trade_ids),
                        PaperTrade.status == "open",
                    )
                )
                fast_trades = list(result.scalars().all())
                if not fast_trades:
                    _fast_loop_trade_ids.clear()
                    continue

                syms   = list({t.symbol for t in fast_trades})
                prices = await _fetch_futures_prices(syms)

                changed = False
                for trade in fast_trades:
                    price = prices.get(trade.symbol)
                    if price is None:
                        continue
                    try:
                        meta = json.loads(trade.signals_json or "{}")
                    except Exception:
                        meta = {}
                    entry     = trade.entry_price
                    direction = trade.direction
                    leverage  = trade.leverage or meta.get("leverage", 5)
                    sl        = trade.trail_sl or trade.stop_loss

                    _pnl_pct = (
                        (price - entry) / entry * 100 if direction == "LONG"
                        else (entry - price) / entry * 100
                    ) if entry > 0 else 0.0

                    lane = trade.setup_type or meta.get("setup_type") or lane_for_style(trade.style)

                    def _fast_close(t, cp, reason):
                        """Apply close fields to a trade in the fast loop."""
                        from decimal import Decimal as _D
                        _ep = t.entry_price
                        _d  = t.direction
                        _cp_d = _D(str(cp))
                        _ep_d = _D(str(_ep))
                        pnl_gross = ((_cp_d - _ep_d) / _ep_d * 100 if _d == "LONG"
                                     else (_ep_d - _cp_d) / _ep_d * 100)
                        pnl_net = pnl_gross - _D(str(ROUND_TRIP * 100))
                        _notional = t.position_size or futures_notional(meta.get("risk_pct") or 2.0)
                        t.status      = "tp" if float(pnl_net) > 0 else "sl"
                        t.close_price = round(cp, 8)
                        t.closed_at   = time.time()
                        t.pnl_pct     = float(round(pnl_net, 2))
                        t.pnl_dollar  = float(round(pnl_net / 100 * _D(str(_notional)), 2))
                        meta["close_reason"] = reason
                        t.signals_json = json.dumps(meta, ensure_ascii=False)

                    # Max-loss gate (same as main loop P1.1)
                    _mloss_pct = MAX_LOSS_PCT_OF_MARGIN_BY_LANE.get(lane, DEFAULT_MAX_LOSS_PCT)
                    if _pnl_pct < 0 and abs(_pnl_pct) * leverage > _mloss_pct:
                        _fast_close(trade, price, "max_margin_loss_fast_loop")
                        _fast_loop_trade_ids.discard(trade.id)
                        changed = True
                        logger.warning("fast_loop_max_margin_loss", symbol=trade.symbol,
                                       pnl_pct=round(_pnl_pct, 2), leverage=leverage)
                        continue

                    # SL hit
                    if sl:
                        _sl_hit = (direction == "LONG" and price <= sl) or \
                                  (direction == "SHORT" and price >= sl)
                        if _sl_hit:
                            _fast_close(trade, sl, "sl_hit_fast_loop")
                            _fast_loop_trade_ids.discard(trade.id)
                            changed = True
                            logger.warning("fast_loop_sl_hit", symbol=trade.symbol, sl=sl, price=price)

                if changed:
                    await session.commit()
                    await _update_futures_balance()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("fast_loop_error", error=str(exc)[:80])


# ── Background loop ───────────────────────────────────────────────────────────

async def run_futures_monitor() -> None:
    global _running, _cycle_count, _last_check, _last_error, _closed_today, _today

    _running = True
    logger.info("futures_monitor_started", interval_sec=INTERVAL_SEC)
    await asyncio.sleep(STARTUP_DELAY)

    # Rebuild the single futures wallet on startup so /balance/futures is accurate after restarts
    await _update_futures_balance()

    # P5.4: start the fast-loop for high-risk positions concurrently
    _fast_task = asyncio.create_task(_run_fast_loop())

    while True:
        # F61: reset closed_today counter at midnight
        _today_str = time.strftime("%Y-%m-%d")
        if _today != _today_str:
            _today        = _today_str
            _closed_today = 0

        try:
            # PLAN_v5 Group C: pull DB overrides once per cycle. Lane caps live in
            # utils.py as a shared dict — mutate values IN PLACE (not rebind the
            # name) so `from utils import MAX_SL_MARGIN_PCT_BY_LANE` here and
            # anywhere else that imported it keep pointing at the same object.
            try:
                from agents.shared.config_reader import cfg
                MAX_SL_MARGIN_PCT_BY_LANE["accumulation"] = await cfg.get(
                    "futures", "lane_cap_accumulation", MAX_SL_MARGIN_PCT_BY_LANE["accumulation"])
                MAX_SL_MARGIN_PCT_BY_LANE["pre_gainer"] = await cfg.get(
                    "futures", "lane_cap_pre_gainer", MAX_SL_MARGIN_PCT_BY_LANE["pre_gainer"])
                MAX_SL_MARGIN_PCT_BY_LANE["pre_move"] = MAX_SL_MARGIN_PCT_BY_LANE["pre_gainer"]  # legacy alias
                MAX_SL_MARGIN_PCT_BY_LANE["momentum"] = await cfg.get(
                    "futures", "lane_cap_momentum", MAX_SL_MARGIN_PCT_BY_LANE["momentum"])
                MAX_SL_MARGIN_PCT_BY_LANE["bigmover"] = await cfg.get(
                    "futures", "lane_cap_bigmover", MAX_SL_MARGIN_PCT_BY_LANE["bigmover"])
            except Exception as exc:
                logger.warning("agent_config_pull_failed", scope="futures_monitor", error=str(exc)[:120])

            await _check_server_time_drift()   # EC5: NTP drift warning (no-op if < 30 min since last)
            closed_n, updated_n = await check_futures_positions()  # B3: unpack tuple
            n = closed_n + updated_n
            _cycle_count += 1
            _last_check   = time.time()
            _last_error   = None
            if n:
                _closed_today += closed_n  # B3: count actual closes only, not SL-trail updates
                logger.info("futures_monitor_cycle", closed=closed_n, updated=updated_n,
                            cycle=_cycle_count,
                            liq_guards=_liq_guards, tp_extended=_tp_extended)
            # Refresh the wallet after any close, plus a periodic safety resync
            if closed_n > 0 or _cycle_count % 10 == 0:
                await _update_futures_balance()

        except asyncio.CancelledError:
            logger.info("futures_monitor_stopped")
            _running = False
            _fast_task.cancel()
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.error("futures_monitor_error", error=_last_error)

        await asyncio.sleep(INTERVAL_SEC)
