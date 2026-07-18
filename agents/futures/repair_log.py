"""Helper repair ledger FUTURES (PLAN_SIGNAL_REPAIR_LIVE R1).

Satu pintu tulis untuk SEMUA aksi perbaikan material (agen predictive, weekly
review, transisi ban/unban, pause lane, saran yang diterapkan, revert verifier)
+ cek cooldown anti-osilasi. Fail-open: kegagalan mencatat tak boleh menghentikan
mekanisme perbaikannya sendiri (dicatat sebagai warning).
"""

from __future__ import annotations

import json
import time
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_repair_action import FuturesRepairAction

logger = structlog.get_logger(__name__)

COOLDOWN_ACTION_H = 24.0   # maks 1 aksi bobot per target per 24 jam
COOLDOWN_REVERT_H = 48.0   # revert kena cooldown lebih panjang (anti flip-flop)


async def record_action(
    *,
    source: str,
    target_key: str,
    issue: str,
    action: str,
    agent: str = "",
    evidence: dict | None = None,
    delta: float | None = None,
    applied: bool = True,
    before_metric: float | None = None,
    status: str | None = None,
    revert_of: int | None = None,
    note: str | None = None,
) -> Optional[int]:
    """Tulis satu baris aksi. Return id (None bila DB tak tersedia/gagal)."""
    if not is_db_available():
        return None
    now = time.time()
    try:
        async with AsyncSessionLocal() as session:
            row = FuturesRepairAction(
                detected_at=now,
                source=source[:30],
                target_key=target_key[:120],
                agent=agent[:40],
                issue=issue[:40],
                evidence_json=json.dumps(evidence or {}, ensure_ascii=False),
                action=action[:30],
                delta=delta,
                applied=applied,
                applied_at=now if applied else None,
                before_metric=before_metric,
                status=(status or ("applied" if applied else "suggested"))[:30],
                revert_of=revert_of,
                note=(note[:200] if note else None),
            )
            session.add(row)
            await session.commit()
            return row.id
    except Exception as exc:
        logger.warning("repair_log_record_failed", target=target_key, error=str(exc)[:120])
        return None


async def has_recent_action(
    target_key: str,
    hours: float = COOLDOWN_ACTION_H,
    actions: tuple[str, ...] = ("weight_down", "weight_up"),
) -> bool:
    """Cooldown check: sudah ada aksi (jenis tsb) utk target ini dalam N jam?"""
    if not is_db_available():
        return True   # fail-CLOSED utk cooldown: tanpa DB jangan bertindak
    try:
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(FuturesRepairAction.id).where(
                    FuturesRepairAction.target_key == target_key,
                    FuturesRepairAction.action.in_(list(actions)),
                    FuturesRepairAction.applied.is_(True),
                    FuturesRepairAction.applied_at >= time.time() - hours * 3600,
                ).limit(1)
            )).scalar_one_or_none()
            return row is not None
    except Exception:
        return True
