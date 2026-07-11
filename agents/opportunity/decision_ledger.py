"""Persistence for immutable SPOT candidate/decision snapshots."""

from __future__ import annotations

import hashlib
import json
import time

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal, is_db_available
from app.models.spot_decision_event import SpotDecisionEvent
from app.models.paper_trade import PaperTrade

logger = structlog.get_logger(__name__)

MODEL_VERSION = "spot_rules_adaptive_v1"
FEATURE_SCHEMA_VERSION = "spot_features_v1"


def _reason_code(candidate: dict, opened: bool) -> tuple[str, str]:
    if opened:
        return "opened", "opened"
    if candidate.get("decision_reason"):
        return "rejected", str(candidate["decision_reason"])
    if candidate.get("banned_by_learning"):
        return "blocked", "learning_ban"
    if candidate.get("auto_open"):
        return "eligible_not_opened", "portfolio_or_quota_gate"
    if not candidate.get("direction_confirmed", True):
        return "recommendation", "direction_not_confirmed"
    return "recommendation", "strategy_threshold"


def build_event_rows(scan_result: dict, opened_symbols: set[str]) -> list[dict]:
    """Build deterministic rows; safe to retry the same scan."""
    scan_ts = float(scan_result.get("generated_at") or time.time())
    regime = scan_result.get("btc_regime")
    learning_status = str(scan_result.get("learning_status") or "unknown")
    rows: list[dict] = []

    for candidate in scan_result.get("_decision_events", scan_result.get("results", [])):
        symbol = str(candidate.get("symbol") or "")
        if not symbol:
            continue
        alert_type = str(candidate.get("alert_type") or "unknown")
        entry_mode = str(candidate.get("entry_mode") or "unknown")
        key_material = f"{scan_ts:.6f}|{symbol}|{alert_type}|{entry_mode}"
        decision_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:64]
        opened = symbol in opened_symbols
        action, reason = _reason_code(candidate, opened)
        snapshot = dict(candidate)
        snapshot["scan_regime"] = regime
        snapshot["regime_status"] = scan_result.get("regime_status")

        rows.append({
            "decision_key": decision_key,
            "scan_ts": scan_ts,
            "symbol": symbol,
            "alert_type": alert_type,
            "entry_mode": entry_mode,
            "action": action,
            "reason_code": reason,
            "auto_eligible": bool(candidate.get("auto_open")),
            "opened": opened,
            "raw_score": float(candidate.get("raw_score") or 0.0),
            "adaptive_score": float(candidate.get("adaptive_score") or candidate.get("raw_score") or 0.0),
            "weight_applied": float(candidate.get("weight_applied") or 1.0),
            "estimated_win_probability": candidate.get("estimated_win_probability"),
            "regime": str(regime) if regime else None,
            "learning_status": learning_status,
            "model_version": MODEL_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_snapshot_json": json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            "created_at": time.time(),
            "outcome_status": "pending",
        })
    return rows


async def log_scan_decisions(scan_result: dict, opened_symbols: set[str]) -> int:
    """Insert one scan batch with PostgreSQL conflict protection."""
    if not is_db_available():
        return 0
    rows = build_event_rows(scan_result, opened_symbols)
    if not rows:
        return 0
    try:
        async with AsyncSessionLocal() as session:
            statement = insert(SpotDecisionEvent).values(rows)
            statement = statement.on_conflict_do_nothing(index_elements=["decision_key"])
            result = await session.execute(statement)
            await session.commit()
            inserted = result.rowcount or 0
        logger.info("spot_decisions_logged", inserted=inserted, candidates=len(rows))
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(delete(SpotDecisionEvent).where(
                SpotDecisionEvent.scan_ts < time.time() - 180 * 86400,
                SpotDecisionEvent.outcome_status.in_(["complete", "unavailable"]),
            ))
            await cleanup_session.commit()
        return inserted
    except Exception as exc:
        logger.error("spot_decision_ledger_error", error=str(exc)[:160])
        return 0


async def backfill_closed_spot_trades() -> int:
    """Non-destructively seed the ledger from existing closed SPOT history."""
    if not is_db_available():
        return 0
    async with AsyncSessionLocal() as session:
        trades = list((await session.execute(
            select(PaperTrade).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status.in_(["tp", "sl", "manual", "expired"]),
                PaperTrade.closed_at.isnot(None),
            )
        )).scalars().all())
    rows: list[dict] = []
    for trade in trades:
        try:
            meta = json.loads(trade.signals_json or "{}")
            if not isinstance(meta, dict):
                meta = {"signals": meta if isinstance(meta, list) else []}
        except (TypeError, json.JSONDecodeError):
            meta = {}
        scan_ts = float(trade.entry_at or trade.closed_at or time.time())
        rows.append({
            "decision_key": f"legacy_spot_trade:{trade.id}",
            "scan_ts": scan_ts,
            "symbol": trade.symbol,
            "alert_type": trade.alert_type or "unknown",
            "entry_mode": str(meta.get("entry_mode") or "legacy"),
            "action": "opened",
            "reason_code": "historical_backfill",
            "auto_eligible": trade.entry_type == "auto",
            "opened": True,
            "raw_score": float(meta.get("raw_score") or trade.probability or 0.0),
            "adaptive_score": float(meta.get("adaptive_score") or meta.get("raw_score") or trade.probability or 0.0),
            "weight_applied": float(meta.get("weight_applied") or 1.0),
            "estimated_win_probability": meta.get("estimated_win_probability"),
            "regime": trade.regime,
            "learning_status": "historical",
            "model_version": "legacy_spot_history",
            "feature_schema_version": "legacy_meta_v1",
            "feature_snapshot_json": json.dumps({
                **meta,
                "current_price": trade.entry_price,
                "entry": trade.entry_price,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
            }, ensure_ascii=False, sort_keys=True),
            "created_at": time.time(),
            "outcome_status": "pending",
            "realized_pnl_pct": trade.pnl_pct,
            "realized_pnl_dollar": trade.pnl_dollar,
            "close_reason": str(meta.get("close_reason") or trade.status),
            "closed_at": trade.closed_at,
        })
    if not rows:
        return 0
    async with AsyncSessionLocal() as session:
        statement = insert(SpotDecisionEvent).values(rows)
        statement = statement.on_conflict_do_nothing(index_elements=["decision_key"])
        result = await session.execute(statement)
        await session.commit()
        inserted = result.rowcount or 0
    if inserted:
        logger.info("spot_decision_history_backfilled", inserted=inserted)
    return inserted
