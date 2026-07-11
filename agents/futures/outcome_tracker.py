"""Outcome tracker untuk futures_decision_events (PLAN_ADAPTIVE_LEARNING_FUTURES_10X F1).

Dua sumber kebenaran, dua fungsi:
  1. update_decision_outcomes  — label FORWARD (counterfactual) dari harga klines
     15m pada horizon 30m/1h/4h/24m EKSAK (pola R0a big_mover_logger: harga di
     candle yang memuat scan_ts+h, bukan harga saat pass kebetulan jalan).
  2. backfill_closed_futures_trades — label REALIZED dari trade nyata yang match
     (NET true-cost v16: fee+slippage+funding sudah terpotong di pnl paper_trades).

Mirror pola agents/opportunity/outcome_tracker.py (SPOT — tidak disentuh).
"""

from __future__ import annotations

import time

import httpx
import structlog
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_decision_event import FuturesDecisionEvent
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import fapi

logger = structlog.get_logger(__name__)

# Horizon pendek — posisi futures hidup jam-an (keputusan desain plan §2.4)
HORIZONS: list[tuple[int, str]] = [
    (30 * 60,      "pnl_30m_pct"),
    (60 * 60,      "pnl_1h_pct"),
    (4 * 3600,     "pnl_4h_pct"),
    (24 * 3600,    "pnl_24h_pct"),
]
_KLINE_INTERVAL_SEC = 15 * 60
_TRADE_MATCH_WINDOW = (-120.0, 900.0)   # entry_at ∈ [scan_ts−2m, scan_ts+15m]


def compute_forward_labels(
    direction: str,
    price_at_scan: float,
    klines: list,
    scan_ts: float,
    now: float | None = None,
) -> dict[str, float]:
    """Label pnl% direction-aware per horizon yang SUDAH jatuh tempo.
    klines = 15m [openTimeMs, open, high, low, close, ...] urut naik."""
    now = now if now is not None else time.time()
    labels: dict[str, float] = {}
    if price_at_scan <= 0 or not klines:
        return labels
    for horizon_sec, col in HORIZONS:
        if scan_ts + horizon_sec > now:
            continue   # belum jatuh tempo
        target_ms = (scan_ts + horizon_sec) * 1000
        best = None
        for k in klines:
            try:
                open_ms = float(k[0])
            except (IndexError, TypeError, ValueError):
                continue
            if open_ms <= target_ms:
                best = k
            else:
                break
        if best is None:
            continue
        try:
            close = float(best[4])
        except (IndexError, TypeError, ValueError):
            continue
        pnl = (close - price_at_scan) / price_at_scan * 100
        if direction == "SHORT":
            pnl = -pnl
        labels[col] = round(pnl, 4)
    return labels


def _has_due_unfilled(row: FuturesDecisionEvent, now: float) -> bool:
    for horizon_sec, col in HORIZONS:
        if row.scan_ts + horizon_sec <= now and getattr(row, col) is None:
            return True
    return False


async def _fetch_klines_15m(client: httpx.AsyncClient, symbol: str, start_ts: float) -> list:
    try:
        r = await client.get(fapi("/fapi/v1/klines"), params={
            "symbol": symbol, "interval": "15m",
            "startTime": int(start_ts * 1000), "limit": 110,   # ≈ 27 jam
        })
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


async def update_decision_outcomes(max_symbols: int = 40) -> int:
    """Isi label forward untuk baris pending yang horizon-nya jatuh tempo.
    Satu fetch klines per simbol per pass. Fail-open per simbol."""
    if not is_db_available():
        return 0
    now = time.time()
    updated = 0

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(FuturesDecisionEvent).where(
                FuturesDecisionEvent.outcome_status == "pending",
                FuturesDecisionEvent.scan_ts <= now - HORIZONS[0][0],
            ).order_by(FuturesDecisionEvent.scan_ts.asc()).limit(400)
        )).scalars().all())

        due_rows = [r for r in rows if _has_due_unfilled(r, now)]
        if not due_rows:
            return 0

        by_symbol: dict[str, list[FuturesDecisionEvent]] = {}
        for r in due_rows:
            by_symbol.setdefault(r.symbol, []).append(r)

        async with httpx.AsyncClient(timeout=15) as client:
            for symbol in list(by_symbol.keys())[:max_symbols]:
                sym_rows = by_symbol[symbol]
                start_ts = min(r.scan_ts for r in sym_rows)
                klines = await _fetch_klines_15m(client, symbol, start_ts)
                if not klines:
                    # Simbol delisted/feed mati: baris tua tanpa data tak boleh
                    # menyumbat window pending selamanya → tandai failed.
                    for r in sym_rows:
                        if r.scan_ts < now - 26 * 3600 and r.outcome_status == "pending":
                            r.outcome_status = "failed"
                            r.outcome_updated_at = now
                            updated += 1
                    continue
                for r in sym_rows:
                    labels = compute_forward_labels(
                        r.direction, r.price_at_scan, klines, r.scan_ts, now=now
                    )
                    changed = False
                    for col, val in labels.items():
                        if getattr(r, col) is None:
                            setattr(r, col, val)
                            changed = True
                    if r.pnl_24h_pct is not None and r.outcome_status == "pending":
                        r.outcome_status = "labelled"
                        changed = True
                    if changed:
                        r.outcome_updated_at = now
                        updated += 1
        if updated:
            await session.commit()

    if updated:
        logger.info("futures_decision_outcomes_updated", rows=updated)
    return updated


async def backfill_closed_futures_trades(limit: int = 200) -> int:
    """Link event `opened` ke trade nyata yang sudah closed → label realized NET."""
    if not is_db_available():
        return 0
    now = time.time()
    linked = 0

    async with AsyncSessionLocal() as session:
        events = list((await session.execute(
            select(FuturesDecisionEvent).where(
                FuturesDecisionEvent.opened.is_(True),
                FuturesDecisionEvent.realized_pnl_pct.is_(None),
            ).order_by(FuturesDecisionEvent.scan_ts.asc()).limit(limit)
        )).scalars().all())

        for ev in events:
            trade = (await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style == ev.agent,
                    PaperTrade.symbol == ev.symbol,
                    PaperTrade.alert_type == ev.direction.lower(),
                    PaperTrade.status.in_(["tp", "sl", "expired"]),
                    PaperTrade.pnl_pct.isnot(None),
                    PaperTrade.entry_at >= ev.scan_ts + _TRADE_MATCH_WINDOW[0],
                    PaperTrade.entry_at <= ev.scan_ts + _TRADE_MATCH_WINDOW[1],
                ).order_by(PaperTrade.entry_at.asc()).limit(1)
            )).scalar_one_or_none()
            if trade is None:
                continue
            ev.realized_pnl_pct    = float(trade.pnl_pct)
            ev.realized_pnl_dollar = float(trade.pnl_dollar or 0.0)
            ev.closed_at           = trade.closed_at
            try:
                import json as _json
                ev.close_reason = (_json.loads(trade.signals_json or "{}") or {}).get(
                    "close_reason", trade.status)
            except Exception:
                ev.close_reason = trade.status
            ev.outcome_updated_at = now
            linked += 1
        if linked:
            await session.commit()

    if linked:
        logger.info("futures_decision_trades_linked", rows=linked)
    return linked


async def prune_old_events(days: int = 45) -> int:
    """Ledger retention — baris lebih tua dari `days` dihapus."""
    if not is_db_available():
        return 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(FuturesDecisionEvent).where(
                FuturesDecisionEvent.scan_ts < time.time() - days * 86400
            )
        )
        await session.commit()
    n = result.rowcount or 0
    if n:
        logger.info("futures_decision_events_pruned", rows=n)
    return n
