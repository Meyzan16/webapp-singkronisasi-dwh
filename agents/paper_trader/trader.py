"""
Paper Trading Agent — PostgreSQL-backed.

Purpose: measure win rate per trading style by simulating scanner signals.

Trade lifecycle:
  pending  → scanner signal recorded, waiting for entry price to be hit
              (only for limit orders: wait_pullback / wait_rally)
  open     → entry price reached, position is "active"
              (market/at_zone entries start here directly)
  tp       → take profit hit ✅
  sl       → stop loss hit 🛑

This mirrors real trading:
  - Market entry (at_zone): your order fills immediately → open
  - Limit entry (wait_pullback/wait_rally): order placed, waiting for
    price to pull back/rally to entry zone → pending first, then open

Rules:
  1. R:R >= MIN_RR (1:3) — only quality setups
  2. Dedup per coin+style: skip if coin already has pending OR open trade
     in this style (mirrors "you can only have one order per instrument")
  3. After close (tp/sl): slot is free for next signal
"""

import json
import time
from typing import Optional

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import fapi

logger = structlog.get_logger(__name__)

_last_check_ts: float = 0.0
_CHECK_INTERVAL = 60   # price check at most once per minute
MIN_RR          = 3.0  # minimum R:R to log (1:3)

# Limit orders: entry types that require waiting for fill
LIMIT_ENTRY_TYPES = {"wait_pullback", "wait_rally"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_db() -> None:
    if not is_db_available():
        raise HTTPException(status_code=503,
            detail="Database unavailable — paper trading requires PostgreSQL.")


def _parse_rr(rr_str: str) -> float:
    try:
        return float(str(rr_str).split(":")[1])
    except (IndexError, ValueError):
        return 0.0


def _initial_status(entry_type: str) -> str:
    """
    Market/at_zone → "open" immediately (entry filled at scan time).
    Limit (wait_pullback/wait_rally) → "pending" (waiting for fill).
    """
    return "pending" if entry_type in LIMIT_ENTRY_TYPES else "open"


# ── Write operations ───────────────────────────────────────────────────────────

async def log_signal(signal: dict, style: str) -> bool:
    return bool(await log_signals_batch([signal], style))


async def log_signals_batch(signals: list[dict], style: str) -> int:
    """
    Batch-insert scanner signals.

    • R:R >= MIN_RR filter (cheap, no DB)
    • Dedup: skip coin if it already has pending OR open trade in this style
    • Market entry  → status = "open"   (position is live immediately)
    • Limit entry   → status = "pending" (waiting for entry zone to be hit)
    """
    if not is_db_available() or not signals:
        return 0

    # 1. R:R filter
    qualifying = [s for s in signals if _parse_rr(s.get("risk_reward", "1:0")) >= MIN_RR]
    skipped_rr = len(signals) - len(qualifying)
    if not qualifying:
        if skipped_rr:
            logger.info("paper_trades_rr_filtered", style=style, total=len(signals))
        return 0

    try:
        symbols = [s["symbol"] for s in qualifying]
        now     = time.time()

        async with AsyncSessionLocal() as session:
            # 2. Dedup: one active slot per coin+style (pending or open)
            existing = await session.execute(
                select(PaperTrade.symbol).where(
                    PaperTrade.symbol.in_(symbols),
                    PaperTrade.style.in_([style]),
                    PaperTrade.status.in_(["pending", "open"]),
                )
            )
            active_symbols = {row[0] for row in existing.fetchall()}

            new_trades = []
            for sig in qualifying:
                if sig["symbol"] in active_symbols:
                    continue
                entry_type = sig.get("entry_type", "market")
                new_trades.append(PaperTrade(
                    symbol       = sig["symbol"],
                    direction    = sig["direction"],
                    style        = style,
                    entry_price  = float(sig["entry"]),
                    stop_loss    = float(sig["stop_loss"]),
                    take_profit  = float(sig["take_profit"]),
                    risk_reward  = sig["risk_reward"],
                    probability  = float(sig.get("probability", 0)),
                    alert_type   = sig.get("alert_type", ""),
                    sl_method    = sig.get("sl_method", ""),
                    tp_method    = sig.get("tp_method", ""),
                    signals_json = json.dumps(sig.get("signals", [])),
                    entry_type   = entry_type,
                    entry_at     = now,
                    status       = _initial_status(entry_type),
                ))

            if new_trades:
                session.add_all(new_trades)
                await session.commit()

        pending_n = sum(1 for t in new_trades if t.status == "pending")
        open_n    = len(new_trades) - pending_n
        logger.info("paper_trades_logged",
                    style=style, open=open_n, pending=pending_n,
                    skipped_dup=len(qualifying) - len(new_trades),
                    skipped_rr=skipped_rr)
        return len(new_trades)

    except SQLAlchemyError as exc:
        logger.warning("log_signals_batch_error", error=str(exc)[:120])
        return 0


async def check_and_close_trades() -> int:
    """
    1. Pending → Open: if limit order entry zone is now reached
    2. Open   → TP/SL: if take profit or stop loss is hit

    Called at most once per _CHECK_INTERVAL seconds.
    """
    global _last_check_ts

    if not is_db_available():
        return 0

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.status.in_(["pending", "open"]))
            )
            active_trades = result.scalars().all()
    except SQLAlchemyError:
        return 0

    if not active_trades:
        return 0

    now = time.time()

    # Fetch Binance prices for all active symbols
    symbols = list({t.symbol for t in active_trades})
    prices: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for sym in symbols:
            try:
                r = await client.get(fapi(f"/fapi/v1/ticker/price?symbol={sym}"))
                if r.status_code == 200:
                    prices[sym] = float(r.json()["price"])
            except Exception:
                pass

    filled = 0
    closed = 0

    try:
        async with AsyncSessionLocal() as session:
            for trade in active_trades:
                price = prices.get(trade.symbol)
                if price is None:
                    continue

                db_trade = await session.get(PaperTrade, trade.id)
                if db_trade is None:
                    continue

                # ── Step 1: Pending → Open (limit order fill check) ───────────
                if db_trade.status == "pending":
                    entry_type = db_trade.entry_type or "market"
                    if entry_type == "wait_pullback" and db_trade.direction == "LONG":
                        filled_now = price <= db_trade.entry_price
                    elif entry_type == "wait_rally" and db_trade.direction == "SHORT":
                        filled_now = price >= db_trade.entry_price
                    else:
                        filled_now = True  # fallback: treat as filled

                    if filled_now:
                        db_trade.status  = "open"
                        db_trade.entry_at = now  # reset entry time when filled
                        filled += 1
                        logger.info("paper_trade_filled",
                                    symbol=db_trade.symbol, direction=db_trade.direction,
                                    entry=db_trade.entry_price, price=price)
                    continue  # don't evaluate TP/SL on same tick as fill

                # ── Step 2: Open → TP/SL ─────────────────────────────────────
                if db_trade.status == "open":
                    if db_trade.direction == "LONG":
                        hit_sl = price <= db_trade.stop_loss
                        hit_tp = price >= db_trade.take_profit
                    else:
                        hit_sl = price >= db_trade.stop_loss
                        hit_tp = price <= db_trade.take_profit

                    if not (hit_tp or hit_sl):
                        continue

                    close_price = db_trade.take_profit if hit_tp else db_trade.stop_loss
                    pnl = (
                        (close_price - db_trade.entry_price) / db_trade.entry_price * 100
                        if db_trade.direction == "LONG"
                        else (db_trade.entry_price - close_price) / db_trade.entry_price * 100
                    )
                    db_trade.status      = "tp" if hit_tp else "sl"
                    db_trade.closed_at   = now
                    db_trade.close_price = close_price
                    db_trade.pnl_pct     = round(pnl, 4)
                    closed += 1
                    logger.info("paper_trade_closed",
                                symbol=db_trade.symbol, status=db_trade.status,
                                pnl_pct=round(pnl, 2))

            await session.commit()

    except SQLAlchemyError as exc:
        logger.warning("check_trades_error", error=str(exc)[:120])

    _last_check_ts = now
    if filled or closed:
        logger.info("price_check_done", filled=filled, closed=closed)
    return closed


async def maybe_check_trades() -> None:
    global _last_check_ts
    if is_db_available() and time.time() - _last_check_ts > _CHECK_INTERVAL:
        await check_and_close_trades()


# ── Read operations ────────────────────────────────────────────────────────────

async def get_all_trades(
    style:  Optional[str] = None,
    status: Optional[str] = None,
    days:   Optional[int] = 14,
) -> list[dict]:
    _require_db()
    cutoff = time.time() - (days or 14) * 86400
    async with AsyncSessionLocal() as session:
        q = select(PaperTrade).where(PaperTrade.entry_at >= cutoff)
        if style:  q = q.where(PaperTrade.style == style)
        if status: q = q.where(PaperTrade.status == status)
        q = q.order_by(PaperTrade.entry_at.desc())
        rows = (await session.execute(q)).scalars().all()
    return [_to_dict(r) for r in rows]


async def get_stats() -> dict:
    _require_db()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(PaperTrade))).scalars().all()

    def _calc(subset: list) -> dict:
        closed  = [t for t in subset if t.status in ("tp", "sl")]
        wins    = [t for t in closed  if t.status == "tp"]
        losses  = [t for t in closed  if t.status == "sl"]
        open_t  = [t for t in subset  if t.status == "open"]
        pending = [t for t in subset  if t.status == "pending"]
        wr      = len(wins) / len(closed) * 100 if closed else 0.0
        pnls    = [t.pnl_pct for t in closed if t.pnl_pct is not None]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        return {
            "total":       len(subset),
            "wins":        len(wins),
            "losses":      len(losses),
            "open":        len(open_t),
            "pending":     len(pending),
            "win_rate":    round(wr, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
        }

    styles = ["scalping", "daytrading", "swing", "position"]
    return {
        "overall":  _calc(rows),
        "by_style": {s: _calc([t for t in rows if t.style == s]) for s in styles},
    }


async def get_daily_pnl(days: int = 30) -> dict:
    _require_db()
    import datetime as dt
    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as session:
        closed = (await session.execute(
            select(PaperTrade)
            .where(PaperTrade.status.in_(["tp", "sl"]), PaperTrade.closed_at >= cutoff)
            .order_by(PaperTrade.closed_at)
        )).scalars().all()

    daily: dict[str, dict] = {}
    for t in closed:
        if not t.closed_at:
            continue
        day = dt.datetime.utcfromtimestamp(t.closed_at).strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}
        daily[day]["trades"] += 1
        if t.status == "tp":
            daily[day]["wins"] += 1
            try: rr = float(t.risk_reward.split(":")[1])
            except: rr = 1.0
            daily[day]["pnl"] = round(daily[day]["pnl"] + rr, 2)
        else:
            daily[day]["losses"] += 1
            daily[day]["pnl"]    = round(daily[day]["pnl"] - 1.0, 2)

    now = dt.datetime.utcnow()
    result_days = [
        daily.get((now - dt.timedelta(days=i)).strftime("%Y-%m-%d"),
                  {"date": (now - dt.timedelta(days=i)).strftime("%Y-%m-%d"),
                   "pnl": 0.0, "wins": 0, "losses": 0, "trades": 0})
        for i in range(days - 1, -1, -1)
    ]
    return {"days": result_days, "total_pnl": round(sum(d["pnl"] for d in result_days), 2), "period_days": days}


async def get_equity_curve() -> list[dict]:
    _require_db()
    async with AsyncSessionLocal() as session:
        closed = (await session.execute(
            select(PaperTrade).where(PaperTrade.status.in_(["tp", "sl"])).order_by(PaperTrade.closed_at)
        )).scalars().all()

    RISK = 1.0
    cumulative = 0.0
    points: list[dict] = [{"ts": int((time.time() - 86400 * 14) * 1000), "pnl": 0.0}]
    for t in closed:
        if t.status == "tp":
            try: rr = float(t.risk_reward.split(":")[1])
            except: rr = 1.0
            gain = RISK * rr
        else:
            gain = -RISK
        cumulative = round(cumulative + gain, 2)
        points.append({"ts": int((t.closed_at or 0) * 1000), "pnl": cumulative})
    return points


# ── Serializer ─────────────────────────────────────────────────────────────────

def _to_dict(t: PaperTrade) -> dict:
    return {
        "id":          t.id,
        "symbol":      t.symbol,
        "direction":   t.direction,
        "style":       t.style,
        "entry_price": t.entry_price,
        "stop_loss":   t.stop_loss,
        "take_profit": t.take_profit,
        "risk_reward": t.risk_reward,
        "probability": t.probability,
        "alert_type":  t.alert_type,
        "sl_method":   t.sl_method,
        "tp_method":   t.tp_method,
        "signals":     json.loads(t.signals_json or "[]"),
        "entry_type":  t.entry_type,
        "entry_at":    t.entry_at,
        "status":      t.status,
        "closed_at":   t.closed_at,
        "close_price": t.close_price,
        "pnl_pct":     t.pnl_pct,
    }
