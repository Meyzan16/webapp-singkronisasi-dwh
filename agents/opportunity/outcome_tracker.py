"""Forward/counterfactual outcome labels for SPOT decision events."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import structlog
from sqlalchemy import or_, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.spot_decision_event import SpotDecisionEvent
from app.services.binance_urls import spot

logger = structlog.get_logger(__name__)

HORIZONS = {
    "pnl_1h_pct": 3600,
    "pnl_4h_pct": 4 * 3600,
    "pnl_24h_pct": 24 * 3600,
    "pnl_3d_pct": 3 * 86400,
    "pnl_7d_pct": 7 * 86400,
}
MAX_EVENTS_PER_RUN = 200


def _entry_price(event: SpotDecisionEvent) -> float:
    try:
        snapshot = json.loads(event.feature_snapshot_json or "{}")
        return float(snapshot.get("current_price") or snapshot.get("entry") or 0.0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def compute_forward_labels(
    entry_price: float,
    scan_ts: float,
    klines: list,
    now: float,
) -> dict[str, float | str | None]:
    """Compute only horizons that are mature; never read future-unavailable bars."""
    if entry_price <= 0 or not klines:
        return {"outcome_status": "pending"}

    parsed = []
    for row in klines:
        if not isinstance(row, list) or len(row) < 7:
            continue
        parsed.append({
            "open_ts": float(row[0]) / 1000,
            "close_ts": float(row[6]) / 1000,
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
        })
    parsed.sort(key=lambda bar: bar["close_ts"])
    labels: dict[str, float | str | None] = {}
    for field, seconds in HORIZONS.items():
        target = scan_ts + seconds
        if now < target:
            labels[field] = None
            continue
        # Point-in-time rule: a candle is evidence only after its close time.
        eligible = [bar for bar in parsed if bar["close_ts"] <= target]
        if not eligible:
            labels[field] = None
            continue
        close = eligible[-1]["close"]
        labels[field] = round((close - entry_price) / entry_price * 100, 4)

    observed = [bar for bar in parsed if bar["close_ts"] <= now]
    if observed:
        labels["mae_pct"] = round(
            (min(bar["low"] for bar in observed) - entry_price) / entry_price * 100,
            4,
        )
        labels["mfe_pct"] = round(
            (max(bar["high"] for bar in observed) - entry_price) / entry_price * 100,
            4,
        )
    labels["outcome_status"] = "complete" if labels.get("pnl_7d_pct") is not None else "partial"
    return labels


async def _fetch_klines(client: httpx.AsyncClient, event: SpotDecisionEvent, now: float) -> list:
    scan_hour = int(event.scan_ts // 3600) * 3600
    end_ts = min(now, scan_hour + 7 * 86400 + 2 * 3600)
    response = await client.get(
        spot("/api/v3/klines"),
        params={
            "symbol": event.symbol,
            "interval": "1h",
            "startTime": int(event.scan_ts * 1000),
            "endTime": int(end_ts * 1000),
            "limit": 171,
        },
        timeout=12,
    )
    if response.status_code != 200:
        return []
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def update_decision_outcomes() -> int:
    """Idempotently enrich due decision events with point-in-time outcomes."""
    if not is_db_available():
        return 0
    now = time.time()
    async with AsyncSessionLocal() as session:
        events = list((await session.execute(
            select(SpotDecisionEvent).where(
                SpotDecisionEvent.scan_ts <= now - 3600,
                or_(
                    SpotDecisionEvent.outcome_status == "pending",
                    (
                        (SpotDecisionEvent.outcome_status == "partial")
                        & (SpotDecisionEvent.outcome_updated_at <= now - 55 * 60)
                    ),
                ),
            ).order_by(
                SpotDecisionEvent.outcome_updated_at.asc().nullsfirst(),
                SpotDecisionEvent.scan_ts,
            ).limit(MAX_EVENTS_PER_RUN)
        )).scalars().all())
    if not events:
        return 0

    semaphore = asyncio.Semaphore(8)
    async with httpx.AsyncClient() as client:
        async def fetch(event: SpotDecisionEvent) -> list:
            async with semaphore:
                try:
                    return await _fetch_klines(client, event, now)
                except Exception as exc:
                    logger.warning("spot_outcome_fetch_failed", symbol=event.symbol, error=str(exc)[:100])
                    return []

        # Scans run every few minutes; many events for the same symbol share the
        # same hourly candle window. Fetch once per (symbol, scan-hour) to avoid
        # multiplying Binance calls and starving newer labels.
        representatives: dict[tuple[str, int], SpotDecisionEvent] = {}
        for event in events:
            representatives.setdefault((event.symbol, int(event.scan_ts // 3600)), event)
        keys = list(representatives)
        payloads = await asyncio.gather(*(fetch(representatives[key]) for key in keys))
        klines_by_key = dict(zip(keys, payloads))
        fetched = [
            (event, klines_by_key.get((event.symbol, int(event.scan_ts // 3600)), []))
            for event in events
        ]

    updated = 0
    async with AsyncSessionLocal() as session:
        for detached, klines in fetched:
            row = await session.get(SpotDecisionEvent, detached.id)
            if row is None:
                continue
            row.outcome_attempts = (row.outcome_attempts or 0) + 1
            row.outcome_updated_at = now
            if not klines:
                row.outcome_error = "no_klines_or_provider_error"
                if row.outcome_attempts >= 5 and now >= row.scan_ts + 7 * 86400:
                    row.outcome_status = "unavailable"
                continue
            labels = compute_forward_labels(_entry_price(detached), detached.scan_ts, klines, now)
            if labels.get("outcome_status") == "pending":
                row.outcome_error = "invalid_entry_or_empty_labels"
                continue
            for field, value in labels.items():
                setattr(row, field, value)
            row.outcome_error = None
            try:
                snapshot = json.loads(row.feature_snapshot_json or "{}")
            except (TypeError, json.JSONDecodeError):
                snapshot = {}
            outcome_24h = labels.get("pnl_24h_pct")
            predicted = snapshot.get("shadow_probability") or row.estimated_win_probability
            row.review_json = json.dumps({
                "prediction": predicted,
                "outcome_24h_pct": outcome_24h,
                "prediction_correct": None if outcome_24h is None or predicted is None else bool(
                    (float(predicted) >= 0.5) == (float(outcome_24h) > 0)
                ),
                "mae_pct": labels.get("mae_pct"),
                "mfe_pct": labels.get("mfe_pct"),
                "decision_reason": row.reason_code,
                "model_version": snapshot.get("shadow_model_version") or row.model_version,
            }, ensure_ascii=False)
            updated += 1
        await session.commit()
    if updated:
        logger.info("spot_decision_outcomes_updated", count=updated)
    return updated
