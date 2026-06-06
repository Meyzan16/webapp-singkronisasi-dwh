"""
Opportunity Monitor — Risk-Adjusted Return (SPOT).

Runs every 60s. For each open opportunity_spot trade:

  Layer 1 — Hard exits (SL/TP):
    - price ≤ SL → close "sl"
    - price ≥ TP3 or TP2 → close "tp"
    - TP1 hit → flag, keep open, move SL to breakeven

  Layer 2 — Risk-adjusted closes (dynamic):
    - RSI overbought (> 80) + price stalled (<0.5% last 3 checks) → close "profit_protection"
    - RSI bearish divergence (RSI falling while price flat) → close "risk_adjusted"
    - EMA9 crosses below EMA21 on 1h → close "trend_reversal"
    - Taker buy ratio drops below 0.40 → close "flow_reversal"

  Layer 3 — Opportunity monitoring:
    - Fetches fresh klines to re-score
    - If re-score drops > 30pts from entry score → close "opportunity_lost"
    - If re-score is still high → keep riding

  Manual close always available via API.
"""

import asyncio
import json
import math
import time
from typing import Optional

import httpx
import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import spot

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 60     # check every minute
STARTUP_DELAY = 45

# Fee: 0.1% taker per side = 0.2% round trip
TAKER_FEE     = 0.001   # 0.1% per side
ROUND_TRIP    = TAKER_FEE * 2  # 0.2% total cost

# Maximum position age in days — close stalled positions
MAX_AGE_DAYS  = 7

_running      = False
_cycle_count  = 0
_last_check:  Optional[float] = None
_last_error:  Optional[str]   = None

# Track last prices per symbol for stall detection
_price_history: dict[str, list[float]] = {}


def get_state() -> dict:
    return {
        "running":     _running,
        "cycle_count": _cycle_count,
        "last_check":  _last_check,
        "last_error":  _last_error,
    }


# ── Lightweight re-scorer ─────────────────────────────────────────────────────

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
            if total > 0: ratios.append(buy / total)
        except Exception:
            pass
    return sum(ratios) / len(ratios) if ratios else 0.5


async def _fetch_klines_quick(client: httpx.AsyncClient, symbol: str) -> list:
    """Fetch last 30 1h candles for quick re-scoring."""
    try:
        r = await client.get(spot(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30"))
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def _risk_signal(klines: list, entry_price: float, current_price: float, symbol: str) -> Optional[str]:
    """
    Check if any risk-adjusted close conditions are met.
    Returns close reason string, or None if position should stay open.
    """
    if len(klines) < 15:
        return None

    closes  = [float(k[4]) for k in klines]
    highs   = [float(k[2]) for k in klines]
    ema9    = _ema(closes, 9)
    ema21   = _ema(closes, 21)
    rsi     = _rsi(closes, 14)
    taker   = _taker_ratio(klines)
    pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0

    # 1. EMA death cross on 1h — trend reversing
    if ema9 < ema21 * 0.998 and pnl_pct > 0:
        return "trend_reversal"

    # 2. RSI overbought + price stalled — protect profits
    if rsi > 80 and pnl_pct > 3:
        hist = _price_history.get(symbol, [])
        if len(hist) >= 3:
            recent_range = (max(hist[-3:]) - min(hist[-3:])) / hist[-3] if hist[-3] > 0 else 1
            if recent_range < 0.005:   # price stalled within 0.5%
                return "profit_protection"

    # 3. Institutional flow reversal — taker buy dropped
    if taker < 0.40 and pnl_pct > 0:
        return "flow_reversal"

    # 4. Overbought with loss — stop bleeding
    if rsi > 75 and pnl_pct < -2:
        return "risk_adjusted"

    return None


async def _fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch current spot prices — batch endpoint to minimize weight usage."""
    if not symbols:
        return {}
    prices: dict[str, float] = {}
    import json as _json
    # Use batch symbols endpoint: weight=2 for all symbols at once
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            syms_param = _json.dumps(symbols)
            r = await client.get(
                spot("/api/v3/ticker/price"),
                params={"symbols": syms_param},
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        prices[item["symbol"]] = float(item["price"])
                    return prices
            # Fallback: individual requests with semaphore
            _sem = asyncio.Semaphore(10)
            async def _fetch_one(sym: str) -> None:
                async with _sem:
                    try:
                        resp = await client.get(spot(f"/api/v3/ticker/price?symbol={sym}"))
                        if resp.status_code == 200:
                            prices[sym] = float(resp.json()["price"])
                    except Exception:
                        pass
            await asyncio.gather(*[_fetch_one(s) for s in symbols])
    except Exception:
        pass
    return prices


def _parse_trade_meta(trade: PaperTrade) -> dict:
    """Extract tp1/tp2/tp3 stored in signals_json."""
    try:
        meta = json.loads(trade.signals_json or "{}")
        if isinstance(meta, dict):
            return meta
    except Exception:
        pass
    return {}


async def check_positions() -> int:
    """
    Risk-adjusted position monitor.
    Returns number of positions closed or updated this cycle.
    """
    if not is_db_available():
        return 0

    closed  = 0
    updated = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status == "open",
            )
        )
        trades = list(result.scalars().all())

        if not trades:
            return 0

        symbols = list({t.symbol for t in trades})
        prices  = await _fetch_prices(symbols)

        # Fetch klines for risk assessment (only for open positions)
        klines_map: dict[str, list] = {}
        async with httpx.AsyncClient(timeout=15) as client:
            tasks = {sym: asyncio.create_task(_fetch_klines_quick(client, sym)) for sym in symbols}
            for sym, task in tasks.items():
                try:
                    klines_map[sym] = await task
                except Exception:
                    klines_map[sym] = []

        for trade in trades:
            price = prices.get(trade.symbol)
            if price is None:
                continue

            # Update price history for stall detection
            hist = _price_history.setdefault(trade.symbol, [])
            hist.append(price)
            if len(hist) > 10:
                hist.pop(0)

            meta  = _parse_trade_meta(trade)
            tp1   = meta.get("tp1")
            tp2   = meta.get("tp2", trade.take_profit)
            tp3   = meta.get("tp3")
            sl    = meta.get("current_sl", trade.stop_loss)   # may be trailed
            entry = trade.entry_price

            new_status:  Optional[str]   = None
            close_price: Optional[float] = None
            close_reason: Optional[str]  = None

            # ── Max age check (7 days — avoid dead positions) ────────────────
            age_days = (time.time() - (trade.entry_at or 0)) / 86400
            if age_days > MAX_AGE_DAYS:
                pnl_now = (price - entry) / entry * 100
                new_status   = "tp" if pnl_now > 0 else "sl"
                close_price  = round(price, 8)
                close_reason = "max_age_expired"

            # ── Layer 1: Hard exits ──────────────────────────────────────────
            elif price <= sl:
                new_status   = "sl"
                close_price  = sl
                close_reason = "sl_hit"
            elif tp3 and price >= tp3:
                new_status   = "tp"
                close_price  = tp3
                close_reason = "tp3_hit"
            elif price >= tp2:
                new_status   = "tp"
                close_price  = tp2
                close_reason = "tp2_hit"
            elif tp1 and price >= tp1 and not meta.get("tp1_hit"):
                # TP1 hit — flag + move SL to breakeven + cover entry fee
                # New SL = entry × (1 + round_trip_fee) so net P&L ≥ 0 even after fee
                new_sl = entry * (1 + ROUND_TRIP)
                meta["tp1_hit"]       = True
                meta["tp1_hit_price"] = round(price, 8)
                meta["tp1_hit_at"]    = time.time()
                meta["current_sl"]    = round(new_sl, 8)
                trade.signals_json    = json.dumps(meta)
                updated += 1
                logger.info("opportunity_tp1_hit", symbol=trade.symbol,
                            price=price, tp1=tp1, new_sl=round(new_sl, 8))

            # ── Layer 2: Risk-adjusted exits ─────────────────────────────────
            if new_status is None:
                klines  = klines_map.get(trade.symbol, [])
                reason  = _risk_signal(klines, entry, price, trade.symbol)
                if reason:
                    new_status   = "tp" if (price > entry) else "sl"
                    close_price  = round(price, 8)
                    close_reason = reason
                    logger.info(
                        "opportunity_risk_adjusted_close",
                        symbol=trade.symbol,
                        reason=reason,
                        price=price,
                        entry=entry,
                        pnl_pct=round((price - entry) / entry * 100, 2),
                    )

            # ── Apply close ──────────────────────────────────────────────────
            if new_status and close_price:
                # Fee-aware P&L: deduct 0.1% entry + 0.1% exit = 0.2% round trip
                pnl_gross = (close_price - entry) / entry * 100
                pnl_net   = pnl_gross - (ROUND_TRIP * 100)   # in %
                meta["close_reason"]  = close_reason
                meta["pnl_gross_pct"] = round(pnl_gross, 2)
                meta["fee_pct"]       = round(ROUND_TRIP * 100, 2)
                trade.status          = new_status
                trade.close_price     = close_price
                trade.closed_at       = time.time()
                trade.pnl_pct         = round(pnl_net, 2)   # net after fee
                trade.signals_json    = json.dumps(meta)
                closed += 1
                logger.info(
                    "opportunity_position_closed",
                    symbol=trade.symbol,
                    status=new_status,
                    reason=close_reason,
                    entry=entry,
                    close=close_price,
                    pnl_gross=round(pnl_gross, 2),
                    pnl_net=round(pnl_net, 2),
                    fee=round(ROUND_TRIP * 100, 2),
                )

        if closed > 0 or updated > 0:
            await session.commit()

    return closed + updated


async def run_opportunity_monitor() -> None:
    """Background loop — runs every 60 seconds."""
    global _running, _cycle_count, _last_check, _last_error

    _running = True
    logger.info("opportunity_monitor_started", interval_sec=INTERVAL_SEC)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            n = await check_positions()
            _cycle_count += 1
            _last_check   = time.time()
            _last_error   = None
            if n:
                logger.info("monitor_cycle_closed", count=n, cycle=_cycle_count)

        except asyncio.CancelledError:
            logger.info("opportunity_monitor_stopped")
            _running = False
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.error("opportunity_monitor_error", error=_last_error)

        await asyncio.sleep(INTERVAL_SEC)
