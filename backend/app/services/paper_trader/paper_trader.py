"""
Paper Trading Service — PostgreSQL-backed.

Purpose: measure win rate per trading style.
Each style is tracked independently so win rate stats are style-specific.

Rules:
  1. R:R >= MIN_RR (1:3) — only quality setups get logged
  2. Dedup per coin+style: skip only if that coin already has an OPEN trade
     in the same style. Cross-style duplicates are allowed (scalping BTCUSDT
     and daytrading BTCUSDT are separate data points for different styles).
  3. Limit orders (wait_pullback / wait_rally): TP/SL only checked after fill
  4. MIN_HOLD_SEC: 5-min grace before first TP/SL evaluation (no instant-TP)

DB unavailability:
  log_signals_batch()     → returns 0 silently
  check_and_close_trades()→ returns 0 silently
  get_all_trades()        → raises 503
  get_stats()             → raises 503
  get_equity_curve()      → raises 503
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
_CHECK_INTERVAL = 60      # rate-limit: check at most once per minute
MIN_RR          = 3.0     # minimum R:R ratio to log (1:3)
MIN_HOLD_SEC    = 5 * 60  # 5 min grace before first TP/SL evaluation


# ── Internal helpers ───────────────────────────────────────────────────────────

def _require_db() -> None:
    if not is_db_available():
        raise HTTPException(
            status_code=503,
            detail="Database unavailable — paper trading history requires PostgreSQL.",
        )


def _parse_rr(rr_str: str) -> float:
    """Parse '1:2.5' → 2.5. Returns 0.0 on failure."""
    try:
        return float(str(rr_str).split(":")[1])
    except (IndexError, ValueError):
        return 0.0


# ── Write operations ───────────────────────────────────────────────────────────

async def log_signal(signal: dict, style: str) -> bool:
    """Single signal insert — kept for compatibility."""
    return bool(await log_signals_batch([signal], style))


async def log_signals_batch(signals: list[dict], style: str) -> int:
    """
    Batch-insert scanner signals for the given style.

    Rules:
    • R:R >= MIN_RR (1:3) — quality filter
    • Dedup per coin+style: skip only if that exact coin already has an OPEN
      trade in this style. After TP/SL, the slot is free for the next signal.
      Scalping and daytrading on the same coin are separate rows (different styles).
    • Returns number of trades actually inserted.
    """
    if not is_db_available() or not signals:
        return 0

    # ── 1. R:R filter ─────────────────────────────────────────────────────────
    qualifying = [s for s in signals if _parse_rr(s.get("risk_reward", "1:0")) >= MIN_RR]
    skipped_rr = len(signals) - len(qualifying)
    if not qualifying:
        if skipped_rr:
            logger.info("paper_trades_all_rr_filtered",
                        style=style, total=len(signals), min_rr=MIN_RR)
        return 0

    try:
        symbols = [s["symbol"] for s in qualifying]
        now     = time.time()

        async with AsyncSessionLocal() as session:
            # ── 2. Dedup: one OPEN trade per coin per style ────────────────────
            existing_result = await session.execute(
                select(PaperTrade.symbol).where(
                    PaperTrade.symbol.in_(symbols),
                    PaperTrade.style  == style,
                    PaperTrade.status == "open",
                )
            )
            open_symbols = {row[0] for row in existing_result.fetchall()}

            new_trades = []
            for sig in qualifying:
                if sig["symbol"] in open_symbols:
                    continue
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
                    entry_type   = sig.get("entry_type", "market"),
                    entry_at     = now,
                    status       = "open",
                ))

            if new_trades:
                session.add_all(new_trades)
                await session.commit()

        logger.info("paper_trades_batch_logged",
                    style=style,
                    inserted=len(new_trades),
                    skipped_dup=len(qualifying) - len(new_trades),
                    skipped_rr=skipped_rr)
        return len(new_trades)

    except SQLAlchemyError as exc:
        logger.warning("log_signals_batch_error", error=str(exc)[:120])
        return 0


async def check_and_close_trades() -> int:
    """
    Evaluate open trades against current Binance prices.

    Rules per trade:
    • Skip trades younger than MIN_HOLD_SEC — prevents instant-TP artifacts.
    • For limit orders (wait_pullback / wait_rally): skip TP/SL until
      the current price actually reaches the entry zone (order filled).
    • Then evaluate TP/SL normally.
    """
    global _last_check_ts

    if not is_db_available():
        return 0

    try:
        async with AsyncSessionLocal() as session:
            result      = await session.execute(select(PaperTrade).where(PaperTrade.status == "open"))
            open_trades = result.scalars().all()
    except SQLAlchemyError:
        return 0

    if not open_trades:
        return 0

    now = time.time()

    # Fetch current prices from Binance Futures
    symbols = list({t.symbol for t in open_trades})
    prices: dict[str, float] = {}

    async with httpx.AsyncClient(timeout=10) as client:
        for sym in symbols:
            try:
                r = await client.get(fapi(f"/fapi/v1/ticker/price?symbol={sym}"))
                if r.status_code == 200:
                    prices[sym] = float(r.json()["price"])
            except Exception:
                pass

    closed = 0

    try:
        async with AsyncSessionLocal() as session:
            for trade in open_trades:
                price = prices.get(trade.symbol)
                if price is None:
                    continue

                # ── Rule 1: minimum hold time ──────────────────────────────────
                age_sec = now - trade.entry_at
                if age_sec < MIN_HOLD_SEC:
                    continue

                # ── Rule 2: limit-order fill check ────────────────────────────
                # wait_pullback (LONG limit at support): filled when price drops to entry
                # wait_rally   (SHORT limit at resistance): filled when price rises to entry
                entry_type = trade.entry_type or "market"
                if entry_type == "wait_pullback" and trade.direction == "LONG":
                    if price > trade.entry_price:
                        continue  # not yet filled
                elif entry_type == "wait_rally" and trade.direction == "SHORT":
                    if price < trade.entry_price:
                        continue  # not yet filled

                # ── Rule 3: TP / SL evaluation ────────────────────────────────
                if trade.direction == "LONG":
                    hit_sl = price <= trade.stop_loss
                    hit_tp = price >= trade.take_profit
                else:
                    hit_sl = price >= trade.stop_loss
                    hit_tp = price <= trade.take_profit

                if not (hit_tp or hit_sl):
                    continue

                close_price = trade.take_profit if hit_tp else trade.stop_loss
                pnl = (
                    (close_price - trade.entry_price) / trade.entry_price * 100
                    if trade.direction == "LONG"
                    else (trade.entry_price - close_price) / trade.entry_price * 100
                )

                db_trade = await session.get(PaperTrade, trade.id)
                if db_trade is None:
                    continue

                db_trade.status      = "tp" if hit_tp else "sl"
                db_trade.closed_at   = now
                db_trade.close_price = close_price
                db_trade.pnl_pct     = round(pnl, 4)
                closed += 1

                logger.info("paper_trade_closed",
                            symbol=trade.symbol, status=db_trade.status,
                            pnl_pct=round(pnl, 2), age_min=round(age_sec / 60, 1))

            await session.commit()

    except SQLAlchemyError as exc:
        logger.warning("check_trades_db_error", error=str(exc)[:120])

    _last_check_ts = now
    return closed


async def maybe_check_trades() -> None:
    """Rate-limited wrapper — at most once per _CHECK_INTERVAL seconds."""
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
        if style:
            q = q.where(PaperTrade.style == style)
        if status:
            q = q.where(PaperTrade.status == status)
        q = q.order_by(PaperTrade.entry_at.desc())
        result = await session.execute(q)
        rows   = result.scalars().all()

    return [_to_dict(r) for r in rows]


async def get_stats() -> dict:
    _require_db()

    async with AsyncSessionLocal() as session:
        result     = await session.execute(select(PaperTrade))
        all_trades = result.scalars().all()

    def _calc(subset: list) -> dict:
        closed  = [t for t in subset if t.status in ("tp", "sl")]
        wins    = [t for t in closed  if t.status == "tp"]
        losses  = [t for t in closed  if t.status == "sl"]
        open_t  = [t for t in subset  if t.status == "open"]
        wr      = len(wins) / len(closed) * 100 if closed else 0.0
        pnls    = [t.pnl_pct for t in closed if t.pnl_pct is not None]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        return {
            "total":       len(subset),
            "wins":        len(wins),
            "losses":      len(losses),
            "open":        len(open_t),
            "win_rate":    round(wr, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
        }

    styles = ["scalping", "daytrading", "swing", "position"]
    return {
        "overall":  _calc(all_trades),
        "by_style": {s: _calc([t for t in all_trades if t.style == s]) for s in styles},
    }


async def get_equity_curve() -> list[dict]:
    _require_db()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade)
            .where(PaperTrade.status.in_(["tp", "sl"]))
            .order_by(PaperTrade.closed_at)
        )
        closed = result.scalars().all()

    RISK       = 1.0
    cumulative = 0.0
    start_ts   = int((time.time() - 86400 * 14) * 1000)
    points: list[dict] = [{"ts": start_ts, "pnl": 0.0}]

    for t in closed:
        if t.status == "tp":
            try:
                rr = float(t.risk_reward.split(":")[1])
            except Exception:
                rr = 1.0
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
