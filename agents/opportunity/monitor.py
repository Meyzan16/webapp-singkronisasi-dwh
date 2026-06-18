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

  Layer 2 — Risk-adjusted closes (only after MIN_HOLD_MINUTES):
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

logger = structlog.get_logger(__name__)

INTERVAL_SEC       = 60
STARTUP_DELAY      = 45
MIN_HOLD_MINUTES   = 30
# BM7: per entry_mode — accumulation needs more time, failed momentum exits faster
MAX_AGE_DAYS_FRESH_SETUP    = 10   # akumulasi butuh waktu lebih lama untuk resolve
MAX_AGE_DAYS_MOMENTUM_CHASE = 5    # momentum yang gagal bergerak = capital idle, exit lebih cepat
WICK_LOOKBACK_MIN  = 3            # 1m candles checked per cycle (covers restarts)
WEIGHT_UPDATE_SEC  = 30 * 60      # time-based (§1.12), not cycle-based

# Stagnant rotation — free capital from idle positions when better momentum exists
STAGNANT_CHECK_DAYS = 3     # start checking from day 3 (give position initial runway)
STAGNANT_DRIFT_PCT  = 3.0   # ±3% from entry = coin is not moving
STAGNANT_SCORE_GAP  = 10    # candidate must score ≥ current_score + 10 AND ≥ 85

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

def _has_better_candidate(current_score: float, exclude_symbol: str) -> bool:
    """
    True if the latest scan cache has an auto-open candidate with materially
    higher score than the stagnant position being considered for rotation.
    Requires: candidate.score >= current_score + STAGNANT_SCORE_GAP AND >= 85.
    """
    from agents.opportunity import store as opp_store
    cached = opp_store.get_result()
    if not cached:
        return False
    for c in cached.get("results", []):
        if c.get("symbol") == exclude_symbol:
            continue
        c_score = c.get("raw_score") or c.get("opportunity_score") or 0
        if c.get("auto_open") and c_score >= 85 and c_score >= current_score + STAGNANT_SCORE_GAP:
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
    if hold_minutes < MIN_HOLD_MINUTES or len(klines) < 15:
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
            recent_range = (max(hist[-3:]) - min(hist[-3:])) / hist[-3] if hist[-3] > 0 else 1
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

    if not entry or entry <= 0 or not sl or sl <= 0 or not tp2 or tp2 <= 0:
        logger.warning("monitor_invalid_levels", id=trade.id, symbol=trade.symbol)
        return 0, 0

    # ── Trailing SL ratchet for momentum_chase trades post-TP1 ──────────────
    # Runs every cycle to ratchet the SL up as price climbs. Only moves UP.
    _entry_mode_early = meta.get("entry_mode", "fresh_setup")
    is_momentum_chase = _entry_mode_early == "momentum_chase"
    is_momentum_entry = _entry_mode_early == "momentum_entry"

    if is_momentum_chase and meta.get("tp1_hit") and len(k4h) >= 22:
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

    # ── Layer 3: max age — BM7: per entry_mode ──────────────────────────────
    _entry_mode = meta.get("entry_mode", "fresh_setup")
    if _entry_mode == "momentum_entry":
        _age_expired = entry_at_valid and hold_minutes > 6 * 60   # B6: 6-hour max
    elif _entry_mode == "momentum_chase":
        _age_expired = entry_at_valid and hold_minutes / (60 * 24) > MAX_AGE_DAYS_MOMENTUM_CHASE
    else:
        _age_expired = entry_at_valid and hold_minutes / (60 * 24) > MAX_AGE_DAYS_FRESH_SETUP
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
        # Trailing mode: skip hard TP2/TP3 targets (let winner run further).
        # Only close on trend structure break: EMA9(4h) crosses below EMA21(4h).
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
    elif tp3 and eff_high >= tp3:
        new_status, close_price, close_reason = "tp", tp3, "tp3_hit"
    elif eff_high >= tp2:
        new_status, close_price, close_reason = "tp", tp2, "tp2_hit"
    elif tp1 and eff_high >= tp1 and not meta.get("tp1_hit"):
        # §15.3 PARTIAL SELL 50% at TP1 — lock profit, let the rest ride
        tp1_net_pct  = (tp1 - entry) / entry * 100 - EXECUTION_COST_PCT
        sell_frac    = 0.5
        partial_dlr  = round((tp1_net_pct / 100) * (trade.position_size or 0.0) * sell_frac, 2)
        # §12.6: post-TP1 SL = entry + 50% of TP1 gain (not bare breakeven)
        new_sl = entry * (1 + ((tp1 - entry) / entry) * 0.5)

        meta["tp1_hit"]            = True
        meta["tp1_hit_price"]      = round(float(eff_high), 8)
        meta["tp1_hit_at"]         = time.time()
        meta["tp1_partial_dollar"] = partial_dlr
        meta["remaining_fraction"] = 1.0 - sell_frac
        meta["current_sl"]         = round(new_sl, 8)

        # BM6: if fresh_setup TP1 hit with volume spike → upgrade to momentum_chase
        # trailing stop so the position can ride a real pump instead of exiting at TP2
        if _entry_mode == "fresh_setup" and not meta.get("upgraded_to_trailing"):
            _vol_spike_now = _vol_ratio([float(k[5]) for k in k1h]) if k1h else 1.0
            if _vol_spike_now >= 5.0:
                meta["entry_mode"]          = "momentum_chase"
                meta["upgraded_to_trailing"] = True
                logger.info("fresh_setup_upgraded_to_trailing",
                            symbol=trade.symbol, vol_spike=round(_vol_spike_now, 1))

        trade.signals_json = json.dumps(meta, ensure_ascii=False)
        trade.stop_loss    = round(new_sl, 8)   # §1.11: keep column in sync
        logger.info("opportunity_tp1_partial", symbol=trade.symbol,
                    tp1=tp1, sold_frac=sell_frac, locked_dollar=partial_dlr,
                    new_sl=round(new_sl, 8))
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

    # ── Layer 2.5: stagnant rotation ─────────────────────────────────────────
    # Day 3+, price stuck ±3%, scanner has a materially better candidate →
    # free this capital so the scheduler can open the live momentum play.
    if new_status is None and entry_at_valid:
        hold_days  = hold_minutes / (60 * 24)
        drift_pct  = abs(price - entry) / entry * 100 if entry > 0 else 99.0
        if hold_days >= STAGNANT_CHECK_DAYS and drift_pct <= STAGNANT_DRIFT_PCT:
            trade_score = meta.get("raw_score") or trade.probability or 0
            # BM1: cap at 80 so high-score positions (e.g. 99) don't require
            # an impossible candidate score of 109+ to trigger rotation
            if _has_better_candidate(min(trade_score, 80), trade.symbol):
                pnl_net      = (price - entry) / entry * 100 - EXECUTION_COST_PCT
                new_status   = "tp" if pnl_net > 0 else "sl"
                close_price  = round(price, 8)
                close_reason = "stagnant_rotation"
                logger.info(
                    "stagnant_rotation_triggered",
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
                max_age_fresh=MAX_AGE_DAYS_FRESH_SETUP,
                max_age_momentum=MAX_AGE_DAYS_MOMENTUM_CHASE,
                execution_cost_pct=EXECUTION_COST_PCT)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
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
