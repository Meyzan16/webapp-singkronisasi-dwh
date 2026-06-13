"""
Futures Risk Monitor — runs every 2 minutes.

For each open futures paper trade:
  1. Auto-close: SL or TP2 hit
  2. Trail SL: 50% to TP1 → breakeven; TP1 hit → 75% gain locked; 50% TP1→TP2 → TP1 locked
  3. TP1 partial close: 33% of position closed at TP1
  4. Liquidation guard: adaptive per leverage — close early to protect capital
  5. TP extension: if at TP1 and current score >= 70, extend TP to TP3 + lock SL at TP1
  6. Regime SL: on first check, widen SL in volatile / tighten in ranging
  7. Stagnant 48h: close if no progress (< 20% toward TP1) after 48 hours
  8. Updates trade record in DB
"""

import asyncio
import json
import time
from typing import Optional

import httpx
import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_balance import PaperBalance
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import fapi
from app.services.trading_costs import (
    FUTURES_STARTING_BALANCE, FUTURES_RISK_PCT,
    FUTURES_CLOSED_STATUSES, futures_pnl_dollar,   # F33: single source of truth
)

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 120   # every 2 minutes
STARTUP_DELAY = 60    # start after main scanner

# Futures taker fee: 0.05% per side = 0.10% round trip
TAKER_FEE     = 0.0005   # 0.05% per side
ROUND_TRIP    = TAKER_FEE * 2  # 0.10% total

# Max position age in days — close stalled futures positions
MAX_AGE_DAYS  = 3   # futures positions should resolve faster than spot

_running     = False
_cycle_count = 0
_last_check: Optional[float] = None
_last_error: Optional[str]   = None
_closed_today = 0
_liq_guards   = 0   # positions closed by liquidation guard
_tp_extended  = 0   # positions with TP extended
_today: Optional[str] = None  # F61: track date for daily closed_today reset

_FUTURES_STYLES = ("futures_agent1", "futures_agent2")


def get_state() -> dict:
    return {
        "running":      _running,
        "cycle_count":  _cycle_count,
        "last_check":   _last_check,
        "last_error":   _last_error,
        "closed_today": _closed_today,
        "liq_guards":   _liq_guards,
        "tp_extended":  _tp_extended,
    }


def _calc_liq_price(entry: float, leverage: int, direction: str) -> float:
    """Cross margin liquidation: ~95% of margin consumed."""
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
            syms_param = _json.dumps(symbols)
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


# ── Trail SL logic ─────────────────────────────────────────────────────────────

def _compute_trail(
    direction:    str,
    entry:        float,
    sl:           float,
    tp1:          float,
    tp2:          float,
    price:        float,
    trail_active: bool,
) -> tuple[Optional[float], bool, str]:
    """
    Returns (new_trail_sl, trail_now_active, event_label).
    Returns (None, trail_active, "") if no change needed.
    Stages (LONG):
      1. Price 50% to TP1        → SL to breakeven (entry)
      2. Price hits TP1          → SL to entry + 75%(TP1-entry)   [F14]
      3. Price 50% TP1 → TP2    → SL to TP1 level (lock TP1 profit)  [F77]
    """
    if direction == "LONG":
        halfway_to_tp1   = entry + (tp1 - entry) * 0.50
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
        halfway_to_tp1   = entry - (entry - tp1) * 0.50
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

async def _rebuild_futures_paper_balance(style_key: str) -> None:
    """
    Recompute PaperBalance for a futures style from all closed trades.
    Matches the formula in futures_learning.py so balance API equals learning stats.
    """
    if not is_db_available():
        return

    async with AsyncSessionLocal() as session:
        # F33: tp+sl only — expired excluded from balance (F15), consistent with
        # learning stats and risk dashboard which use the same status policy.
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style == style_key,
                PaperTrade.status.in_(list(FUTURES_CLOSED_STATUSES)),
                PaperTrade.pnl_pct.isnot(None),
            )
        )
        closed = list(result.scalars().all())

    total_pnl = 0.0
    for t in closed:
        try:
            meta = json.loads(t.signals_json or "{}")
        except Exception:
            meta = {}
        # F33: shared formula — identical to learning/risk dashboard
        total_pnl += futures_pnl_dollar(t.pnl_pct, meta.get("risk_pct"))

    new_balance = FUTURES_STARTING_BALANCE + total_pnl
    now = time.time()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperBalance).where(PaperBalance.style == style_key)
        )
        bal = result.scalar_one_or_none()
        if bal is None:
            bal = PaperBalance(
                style           = style_key,
                balance         = new_balance,
                initial_balance = FUTURES_STARTING_BALANCE,
                deposited_total = 0.0,
                withdrawn_total = 0.0,
                realized_pnl    = total_pnl,
                updated_at      = now,
                created_at      = now,
            )
            session.add(bal)
        else:
            bal.balance      = new_balance
            bal.realized_pnl = total_pnl
            bal.updated_at   = now
        await session.commit()

    logger.info("futures_balance_synced",
                style=style_key,
                balance=round(new_balance, 2),
                realized_pnl=round(total_pnl, 2),
                closed_count=len(closed))


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
    global _liq_guards, _tp_extended

    if not is_db_available():
        return 0, 0   # B3: tuple — caller unpacks (closed, updated)

    closed  = 0
    updated = 0

    async with AsyncSessionLocal() as session:
        # Monitor all futures-type positions (including legacy styles)
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(["futures_agent1", "futures_agent2"]),
                PaperTrade.status == "open",
            )
        )
        trades = list(result.scalars().all())

        if not trades:
            return 0, 0   # B3: tuple — caller unpacks (closed, updated)

        symbols = list({t.symbol for t in trades})
        prices  = await _fetch_futures_prices(symbols)

        for trade in trades:
            price = prices.get(trade.symbol)
            if price is None:
                continue

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

            # F83: direction-aware tp1 fallback — explicit midpoint per direction
            if meta.get("tp1"):
                tp1 = float(meta["tp1"])
            elif direction == "LONG":
                tp1 = entry + (tp2 - entry) * 0.5
            else:  # SHORT: tp2 < entry
                tp1 = entry - (entry - tp2) * 0.5

            # F79: regime-based SL adjustment on first check (before any SL read)
            if not trail_active and not meta.get("regime_sl_adjusted"):
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
                        elif _regime == "ranging":
                            # tighten SL toward entry, but never past it
                            if direction == "LONG":
                                _cand = trade.stop_loss + _atr_dist * 0.3
                                if _cand < entry:
                                    trade.stop_loss = round(_cand, 8)
                            else:
                                _cand = trade.stop_loss - _atr_dist * 0.3
                                if _cand > entry:
                                    trade.stop_loss = round(_cand, 8)
                except Exception:
                    pass
                meta["regime_sl_adjusted"] = True
                trade.signals_json = json.dumps(meta, ensure_ascii=False)
                updated += 1

            sl = trade.trail_sl or trade.stop_loss   # read AFTER potential F79 adjustment

            new_status:   Optional[str]   = None
            close_price:  Optional[float] = None
            close_reason: Optional[str]   = None

            # ── 0. Max age check (3 days — futures should resolve quickly) ────
            age_days = (time.time() - (trade.entry_at or 0)) / 86400
            if age_days > MAX_AGE_DAYS:
                # Always "expired" — position didn't resolve via TP/SL (F15)
                new_status   = "expired"
                close_price  = round(price, 8)
                close_reason = "max_age_expired"

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

            # ── 1. Auto-close: SL or TP2 hit ─────────────────────────────────
            if not new_status:
                if direction == "LONG":
                    if price <= sl:
                        new_status   = "sl"
                        close_price  = sl
                        close_reason = "sl_hit"
                    elif price >= tp2:
                        new_status   = "tp"
                        close_price  = tp2
                        close_reason = "tp2_hit"
                else:  # SHORT
                    if price >= sl:
                        new_status   = "sl"
                        close_price  = sl
                        close_reason = "sl_hit"
                    elif price <= tp2:
                        new_status   = "tp"
                        close_price  = tp2
                        close_reason = "tp2_hit"

            # ── 2. Liquidation guard (F85: adaptive threshold per leverage) ───
            if not new_status:
                liq        = _calc_liq_price(entry, leverage, direction)
                d_pct      = _liq_dist_pct(price, liq, direction)
                guard_pct  = _liq_guard_pct(leverage)  # F85: was fixed 8.0
                if d_pct < guard_pct:
                    new_status   = "sl"
                    close_price  = sl
                    close_reason = "liq_guard"
                    _liq_guards += 1
                    logger.warning(
                        "liq_guard_triggered",
                        symbol=trade.symbol, direction=direction,
                        price=price, liq=round(liq, 6),
                        dist_pct=round(d_pct, 2), guard_pct=guard_pct,
                    )

            if new_status and close_price:
                # Fee-aware P&L: 0.05% entry + 0.05% exit = 0.10% round trip
                pnl_gross = (close_price - entry) / entry * 100 if direction == "LONG" \
                            else (entry - close_price) / entry * 100
                pnl_net   = pnl_gross - (ROUND_TRIP * 100)
                try:
                    meta["close_reason"]  = close_reason
                    meta["pnl_gross_pct"] = round(pnl_gross, 2)
                    meta["fee_pct"]       = round(ROUND_TRIP * 100, 2)
                    trade.signals_json    = json.dumps(meta, ensure_ascii=False)
                except Exception:
                    pass
                _risk_pct_meta  = meta.get("risk_pct") or 2.0
                _notional_close = FUTURES_STARTING_BALANCE * FUTURES_RISK_PCT / (_risk_pct_meta / 100)
                # F76: if partial close already done at TP1, final close covers 67% remaining
                if meta.get("tp1_partial_done"):
                    _partial_pnl = meta.get("tp1_partial_pnl_dollar", 0.0)
                    _final_pnl   = round((pnl_net / 100) * _notional_close * 0.67, 2)
                    _total_pnl   = round(_partial_pnl + _final_pnl, 2)
                else:
                    _total_pnl = round((pnl_net / 100) * _notional_close, 2)
                trade.status      = new_status
                trade.close_price = close_price
                trade.closed_at   = time.time()
                trade.pnl_pct     = round(pnl_net, 2)
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

            # ── 3. Trail SL (F77: also advance SL to TP1 when 50% TP1→TP2) ──
            new_sl, now_active, event = _compute_trail(
                direction, entry, sl, tp1, tp2, price, trail_active
            )
            if new_sl is not None:
                trade.trail_sl     = round(new_sl, 8)
                trade.trail_active = now_active
                updated += 1
                logger.info(
                    "futures_sl_trailed",
                    symbol=trade.symbol, direction=direction,
                    event=event, old_sl=round(sl, 8), new_sl=round(new_sl, 8),
                    price=price,
                )

            # ── 3a. TP1 Partial Close: lock 33% profit when TP1 first reached (F76) ──
            if not meta.get("tp1_partial_done"):
                _tp1_hit = (direction == "LONG" and price >= tp1) or \
                           (direction == "SHORT" and price <= tp1)
                if _tp1_hit:
                    _partial_pnl_pct = ((tp1 - entry) / entry * 100 if direction == "LONG"
                                        else (entry - tp1) / entry * 100)
                    _partial_net     = _partial_pnl_pct - (ROUND_TRIP * 100 * 0.5)
                    _rp              = meta.get("risk_pct") or 2.0
                    _notional_p      = FUTURES_STARTING_BALANCE * FUTURES_RISK_PCT / (_rp / 100)
                    _partial_dollar  = round((_partial_net / 100) * _notional_p * 0.33, 2)
                    meta["tp1_partial_done"]       = True
                    meta["tp1_partial_pnl_dollar"] = _partial_dollar
                    trade.pnl_dollar               = (trade.pnl_dollar or 0.0) + _partial_dollar
                    trade.signals_json             = json.dumps(meta, ensure_ascii=False)
                    updated += 1
                    logger.info(
                        "tp1_partial_close",
                        symbol=trade.symbol, direction=direction,
                        partial_pnl_dollar=_partial_dollar,
                        tp1=round(tp1, 6), price=price,
                    )

            # ── 4. TP Extension (F81: lock SL at TP1; F84: use current score) ──
            if tp3 and not meta.get("tp_extended"):
                tp1_hit = (direction == "LONG" and price >= tp1) or \
                          (direction == "SHORT" and price <= tp1)
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
                    if score >= 70:
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

        if closed > 0 or updated > 0:
            await session.commit()

    return closed, updated   # B3: return tuple so caller can track closes separately


# ── Background loop ───────────────────────────────────────────────────────────

async def run_futures_monitor() -> None:
    global _running, _cycle_count, _last_check, _last_error, _closed_today, _today

    _running = True
    logger.info("futures_monitor_started", interval_sec=INTERVAL_SEC)
    await asyncio.sleep(STARTUP_DELAY)

    # Rebuild balance on startup so /balance/futures is accurate after restarts
    for style_key in _FUTURES_STYLES:
        await _rebuild_futures_paper_balance(style_key)

    while True:
        # F61: reset closed_today counter at midnight
        _today_str = time.strftime("%Y-%m-%d")
        if _today != _today_str:
            _today        = _today_str
            _closed_today = 0

        try:
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
            # F62: rebuild balance only every 10 cycles to reduce DB load
            if _cycle_count % 10 == 0:
                for style_key in _FUTURES_STYLES:
                    await _rebuild_futures_paper_balance(style_key)

        except asyncio.CancelledError:
            logger.info("futures_monitor_stopped")
            _running = False
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.error("futures_monitor_error", error=_last_error)

        await asyncio.sleep(INTERVAL_SEC)
