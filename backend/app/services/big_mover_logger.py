"""
Big Mover Logger — Phase 1 T4 / T4b.

Insert big_mover_log row per scan cycle. Backfill forward-pnl periodically.

B1.1: multi-horizon (1h, 4h, 24h, 7d) — bukan 24h saja.
B1.1: simpan slip-adjusted entry assumption (0.3% slippage @ ATR×1.5 SL).
"""

import time
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update

from app.database import AsyncSessionLocal, is_db_available
from app.models.big_mover_log import BigMoverLog
from app.services.binance_urls import fapi, spot
from app.services.slippage_sim import calculate_entry_slippage

logger = structlog.get_logger(__name__)

# B4.1: ASSUMED_SL/TP kept fixed for comparability; slippage now volume-parameterized.
ASSUMED_SL_PCT = 4.0            # ATR×1.5 typical for momentum coin
ASSUMED_TP_PCT = 12.0           # 1:3 R:R

# Backfill horizons (seconds → label)
HORIZONS = [
    (3600,    "pnl_1h_pct"),
    (4*3600,  "pnl_4h_pct"),
    (24*3600, "pnl_24h_pct"),
    (7*24*3600, "pnl_7d_pct"),
]


async def log_big_movers(
    movers: list[dict],
    *,
    market: str = "futures",
    threshold: float = 72,
) -> int:
    """Insert one row per big mover this cycle. Dedup soft-window 5 min/symbol."""
    if not is_db_available() or not movers:
        return 0

    now = time.time()
    inserted = 0

    async with AsyncSessionLocal() as s:
        # Dedup window — don't double-log the same symbol within 5 min
        recent_cutoff = now - 5 * 60
        r = await s.execute(
            select(BigMoverLog.symbol).where(
                BigMoverLog.ts >= recent_cutoff,
                BigMoverLog.market == market,
            )
        )
        recent_syms = {row[0] for row in r.fetchall()}

        for m in movers:
            sym = m.get("symbol", "")
            if not sym or sym in recent_syms:
                continue

            change_24h = float(m.get("change_24h", 0))
            matches    = m.get("matches", []) or []
            best_score = max((mt.get("score", 0) for mt in matches), default=0.0)
            status_str = m.get("status", "tidak_lolos")

            # Translate to log status
            if status_str == "lolos":
                log_status = "opened" if best_score >= threshold else "missed"
            else:
                log_status = "missed"

            # Best direction inferred from matches; fallback by change_24h sign
            direction = "LONG" if change_24h >= 0 else "SHORT"
            if matches:
                direction = matches[0].get("direction", direction)

            s.add(BigMoverLog(
                ts=now,
                symbol=sym,
                market=market,
                direction=direction,
                change_24h=round(change_24h, 2),
                scan_price=float(m.get("price", 0) or 0),
                max_score=round(float(best_score), 1),
                threshold=float(threshold),
                scoring_gap=round(float(best_score) - threshold, 1),
                funding_rate=float(m.get("funding_rate", 0)),
                status=log_status,
                reason=m.get("reason", "")[:500],
            ))
            inserted += 1

        if inserted:
            await s.commit()
    if inserted:
        logger.info("big_mover_log_inserted", count=inserted, market=market)
    return inserted


async def _fetch_mark_price(symbol: str, market: str) -> Optional[float]:
    """Get current mark/last price from Binance."""
    url = fapi("/fapi/v1/ticker/price") if market == "futures" else spot("/api/v3/ticker/price")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url, params={"symbol": symbol})
            if r.status_code == 200:
                return float(r.json()["price"])
    except Exception:
        pass
    return None


def _hypothetical_outcome(
    direction: str,
    entry: float,
    current: float,
    quote_vol_24h: float = 0.0,
) -> tuple[Optional[str], Optional[float]]:
    """
    Simulate 1:3 RR outcome with B1.1 assumptions:
      Entry: scan_price × (1 ± slippage)  — B4.1: dynamic slippage by volume
      SL:    entry × (1 ∓ ASSUMED_SL_PCT/100)
      TP:    entry × (1 ± ASSUMED_TP_PCT/100)
    Returns (status, pnl_pct) — status one of tp/sl/open.
    """
    if entry <= 0 or current <= 0:
        return None, None

    # B4.1: volume-parameterized slippage (default 0.40% for unknown vol)
    slip = calculate_entry_slippage(quote_vol_24h) / 100
    if direction == "LONG":
        eff_entry = entry * (1 + slip)
        sl = eff_entry * (1 - ASSUMED_SL_PCT / 100)
        tp = eff_entry * (1 + ASSUMED_TP_PCT / 100)
        pnl_pct = (current - eff_entry) / eff_entry * 100
        if current <= sl:
            return "sl", -ASSUMED_SL_PCT
        if current >= tp:
            return "tp", ASSUMED_TP_PCT
    else:
        eff_entry = entry * (1 - slip)
        sl = eff_entry * (1 + ASSUMED_SL_PCT / 100)
        tp = eff_entry * (1 - ASSUMED_TP_PCT / 100)
        pnl_pct = (eff_entry - current) / eff_entry * 100
        if current >= sl:
            return "sl", -ASSUMED_SL_PCT
        if current <= tp:
            return "tp", ASSUMED_TP_PCT
    return "open", round(pnl_pct, 2)


async def backfill_pending(max_rows: int = 50) -> int:
    """
    Fill horizon pnl columns for rows past their horizon mark.
    Returns number of rows updated.
    """
    if not is_db_available():
        return 0

    now = time.time()
    updated = 0

    async with AsyncSessionLocal() as s:
        # Find rows where last_backfill_at is None OR oldest horizon hasn't been filled yet
        r = await s.execute(
            select(BigMoverLog).where(
                BigMoverLog.ts < now - HORIZONS[0][0],   # at least 1h old
                ((BigMoverLog.last_backfill_at.is_(None))
                 | (BigMoverLog.pnl_7d_pct.is_(None) & (BigMoverLog.ts < now - HORIZONS[-1][0])))
            ).order_by(BigMoverLog.ts).limit(max_rows)
        )
        rows = list(r.scalars().all())

        for row in rows:
            current = await _fetch_mark_price(row.symbol, row.market)
            if current is None:
                continue

            patch: dict = {"last_backfill_at": now}
            age = now - row.ts
            for horizon_sec, col in HORIZONS:
                if age >= horizon_sec and getattr(row, col) is None:
                    if row.scan_price > 0:
                        if row.direction == "LONG":
                            pnl = (current - row.scan_price) / row.scan_price * 100
                        else:
                            pnl = (row.scan_price - current) / row.scan_price * 100
                        patch[col] = round(pnl, 2)

            # Hypothetical TP/SL outcome (best determinable at 24h horizon)
            if age >= HORIZONS[2][0]:  # 24h
                status_h, pnl_h = _hypothetical_outcome(row.direction, row.scan_price, current)
                if status_h:
                    patch["would_be_status"] = status_h
                if pnl_h is not None:
                    patch["would_be_pnl_pct"] = pnl_h

            if patch:
                await s.execute(
                    update(BigMoverLog).where(BigMoverLog.id == row.id).values(**patch)
                )
                updated += 1
        if updated:
            await s.commit()

    if updated:
        logger.info("big_mover_log_backfilled", rows=updated)
    return updated
