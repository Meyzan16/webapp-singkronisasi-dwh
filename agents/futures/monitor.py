"""
Futures Risk Monitor — runs every 2 minutes.

For each open futures paper trade:
  1. Auto-close: SL or TP2 hit
  2. Trail SL:
       50% toward TP1 → move SL to breakeven (entry)
       TP1 hit        → move SL to entry + 50% of (tp1 - entry)
  3. Liquidation guard: if price within 8% of liq price → close early (protect capital)
  4. TP extension: if trade is profitable AND new scan score >= 80, extend TP to TP3
  5. Updates trade record in DB
"""

import asyncio
import json
import time
from typing import Optional

import httpx
import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import fapi

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 120   # every 2 minutes
STARTUP_DELAY = 60    # start after main scanner

_running     = False
_cycle_count = 0
_last_check: Optional[float] = None
_last_error: Optional[str]   = None
_closed_today = 0
_liq_guards   = 0   # positions closed by liquidation guard
_tp_extended  = 0   # positions with TP extended

LIQ_GUARD_DIST_PCT = 8.0   # close if price within 8% of liquidation


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


# ── Price fetcher ─────────────────────────────────────────────────────────────

async def _fetch_futures_prices(symbols: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        tasks = {
            sym: asyncio.create_task(
                client.get(fapi(f"/fapi/v1/ticker/price?symbol={sym}"))
            )
            for sym in symbols
        }
        for sym, task in tasks.items():
            try:
                r = await task
                if r.status_code == 200:
                    prices[sym] = float(r.json()["price"])
            except Exception:
                pass
    return prices


# ── Trail SL logic ─────────────────────────────────────────────────────────────

def _compute_trail(
    direction: str,
    entry:     float,
    sl:        float,
    tp1:       float,
    price:     float,
    trail_active: bool,
) -> tuple[Optional[float], bool, str]:
    """
    Returns (new_trail_sl, trail_now_active, event_label).
    Returns (None, trail_active, "") if no change needed.
    """
    if direction == "LONG":
        halfway_to_tp1 = entry + (tp1 - entry) * 0.50
        sl_after_tp1   = entry + (tp1 - entry) * 0.50

        if price >= tp1 and (not trail_active or sl < sl_after_tp1):
            return sl_after_tp1, True, "tp1_trail"

        if price >= halfway_to_tp1 and not trail_active and sl < entry:
            return entry, True, "breakeven"

    else:  # SHORT
        halfway_to_tp1 = entry - (entry - tp1) * 0.50
        sl_after_tp1   = entry - (entry - tp1) * 0.50

        if price <= tp1 and (not trail_active or sl > sl_after_tp1):
            return sl_after_tp1, True, "tp1_trail"

        if price <= halfway_to_tp1 and not trail_active and sl > entry:
            return entry, True, "breakeven"

    return None, trail_active, ""


# ── Main check ────────────────────────────────────────────────────────────────

async def check_futures_positions() -> int:
    """
    Check all open futures positions. Returns count closed + updated.

    Enhanced checks (per cycle):
      1. Auto-close: SL or TP2 hit
      2. Liquidation guard: if price within LIQ_GUARD_DIST_PCT% of liq → close at SL
      3. Trail SL: breakeven + TP1 trail
      4. TP extension: if position is profitable + score stays high → extend to TP3
    """
    global _liq_guards, _tp_extended

    if not is_db_available():
        return 0

    closed  = 0
    updated = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(["futures_agent1", "futures_agent2"]),
                PaperTrade.status == "open",
            )
        )
        trades = list(result.scalars().all())

        if not trades:
            return 0

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

            tp1   = meta.get("tp1") or (trade.take_profit * 0.5 + trade.entry_price * 0.5)
            tp2   = trade.take_profit
            tp3   = meta.get("tp3")          # extended target
            sl    = trade.trail_sl or trade.stop_loss
            entry = trade.entry_price
            leverage     = trade.leverage or meta.get("leverage", 5)
            direction    = trade.direction
            trail_active = bool(trade.trail_active)

            new_status:  Optional[str]   = None
            close_price: Optional[float] = None

            # ── 1. Auto-close: SL or TP2 hit ────────────────────────────────
            if direction == "LONG":
                if price <= sl:
                    new_status  = "sl"
                    close_price = sl
                elif price >= tp2:
                    new_status  = "tp"
                    close_price = tp2
            else:  # SHORT
                if price >= sl:
                    new_status  = "sl"
                    close_price = sl
                elif price <= tp2:
                    new_status  = "tp"
                    close_price = tp2

            # ── 2. Liquidation guard ─────────────────────────────────────────
            if not new_status:
                liq   = _calc_liq_price(entry, leverage, direction)
                d_pct = _liq_dist_pct(price, liq, direction)
                if d_pct < LIQ_GUARD_DIST_PCT:
                    # Too close to liquidation — exit at SL to protect capital
                    new_status  = "sl"
                    close_price = sl
                    _liq_guards += 1
                    logger.warning(
                        "liq_guard_triggered",
                        symbol=trade.symbol, direction=direction,
                        price=price, liq=round(liq, 6),
                        dist_pct=round(d_pct, 2),
                    )

            if new_status and close_price:
                pnl = (close_price - entry) / entry * 100
                if direction == "SHORT":
                    pnl = (entry - close_price) / entry * 100
                trade.status      = new_status
                trade.close_price = close_price
                trade.closed_at   = time.time()
                trade.pnl_pct     = round(pnl, 2)
                closed += 1
                logger.info(
                    "futures_position_closed",
                    symbol=trade.symbol, direction=direction,
                    status=new_status, entry=entry,
                    close=close_price, pnl_pct=round(pnl, 2),
                    agent=trade.style,
                )
                continue

            # ── 3. Trail SL ──────────────────────────────────────────────────
            new_sl, now_active, event = _compute_trail(
                direction, entry, sl, tp1, price, trail_active
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

            # ── 4. TP Extension: if at TP1 and TP3 exists, extend target ────
            if tp3 and not meta.get("tp_extended"):
                tp1_hit = (direction == "LONG" and price >= tp1) or \
                          (direction == "SHORT" and price <= tp1)
                if tp1_hit:
                    # Extend TP2 to TP3 when score >= 70 (high conviction)
                    score = trade.probability or 0
                    if score >= 70:
                        trade.take_profit = tp3
                        meta["tp_extended"] = True
                        trade.signals_json  = json.dumps(meta)
                        _tp_extended += 1
                        updated += 1
                        logger.info(
                            "tp_extended_to_tp3",
                            symbol=trade.symbol, direction=direction,
                            old_tp2=tp2, new_tp3=tp3, score=score,
                        )

        if closed > 0 or updated > 0:
            await session.commit()

    return closed + updated


# ── Background loop ───────────────────────────────────────────────────────────

async def run_futures_monitor() -> None:
    global _running, _cycle_count, _last_check, _last_error, _closed_today

    _running = True
    logger.info("futures_monitor_started", interval_sec=INTERVAL_SEC,
                liq_guard_pct=LIQ_GUARD_DIST_PCT)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            n = await check_futures_positions()
            _cycle_count += 1
            _last_check   = time.time()
            _last_error   = None
            if n:
                _closed_today += n
                logger.info("futures_monitor_cycle", closed_updated=n, cycle=_cycle_count,
                            liq_guards=_liq_guards, tp_extended=_tp_extended)

        except asyncio.CancelledError:
            logger.info("futures_monitor_stopped")
            _running = False
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.error("futures_monitor_error", error=_last_error)

        await asyncio.sleep(INTERVAL_SEC)
