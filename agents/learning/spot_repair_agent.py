"""SPOT Adaptive Repair Agent — perbaikan otomatis + live untuk SPOT engine.

Runs every SPOT_REPAIR_INTERVAL_SEC (default 300s = 5 mnt) selama
SPOT_REPAIR_ENABLED=true. Baca metrik SPOT dari DB, keputusan aksi
dari rule-catalog di §Aksi, tulis ke `spot_repair_actions`.

Target: naikkan `outcome_completeness_pct` dari 38.8% ke ≥85% dalam
24 jam, longgarkan threshold pelan supaya sampel outcome tumbuh, boost
sinyal SPOT dengan WR ≥60%, retry promosi model shadow → canary.

Semua aksi REVERSIBLE — before/after tercatat lengkap. TTL scanner
tiap cycle mem-reverse aksi kadaluarsa.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

import structlog
from sqlalchemy import and_, desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal, is_db_available
from app.models.agent_config import AgentConfig
from app.models.signal_weight import AgentSignalWeight
from app.models.spot_decision_event import SpotDecisionEvent
from app.models.spot_repair_action import SpotRepairAction

logger = structlog.get_logger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────
INTERVAL_SEC = int(os.getenv("SPOT_REPAIR_INTERVAL_SEC", "300"))
STARTUP_DELAY = int(os.getenv("SPOT_REPAIR_STARTUP_DELAY", "45"))
DRY_RUN = os.getenv("SPOT_REPAIR_DRY_RUN", "false").lower() == "true"

SPOT_AGENT_KEY = "opportunity_spot"

# Default fallback bila AgentConfig belum di-seed
DEFAULT_AUTO_OPEN_SCORE = 85.0
AUTO_OPEN_SCORE_FLOOR = 78.0     # tidak boleh dilonggarkan di bawah ini
AUTO_OPEN_SCORE_CEIL = 95.0      # tidak boleh diperketat di atas ini

# Threshold-tuning
LOOSEN_STEP = 1.0
TIGHTEN_STEP = 2.0
THRESHOLD_TTL_SEC = 6 * 3600
LOOSEN_MIN_REJECTIONS = 500
LOOSEN_MAX_OPENED_24H = 5
LOOSEN_MIN_MATURE_SAMPLES = 500

TIGHTEN_MAX_WR_24H = 0.40
TIGHTEN_MIN_OPENED_24H = 10

# Weight-tuning
WEIGHT_BOOST_MIN_WR = 0.60
WEIGHT_TRIM_MAX_WR = 0.35
WEIGHT_MIN_SAMPLES = 30
WEIGHT_STEP = 0.05
WEIGHT_MIN = 0.70
WEIGHT_MAX = 1.50

# Symbol cooldown
SYMBOL_COOLDOWN_HOURS = 12
SYMBOL_LOSS_THRESHOLD = 3
SYMBOL_LOSS_WINDOW_H = 48

# Backfill
BACKFILL_MAX_BATCHES = 3   # panggil update_decision_outcomes() sampai 3x
BACKFILL_MIN_COMPLETENESS_PCT = 80.0

# Rate limit per action_type per jam
MAX_ACTIONS_PER_TYPE_PER_HOUR = 10

# ─── State ─────────────────────────────────────────────────────────────────
_running = False
_last_run: Optional[float] = None
_next_run: Optional[float] = None
_last_error: Optional[str] = None
_action_count_24h = 0

# Runtime toggle (in-memory) — kalau False, tipe aksi ini di-skip cycle ini
_action_enabled: dict[str, bool] = {
    "OUTCOME_BACKFILL":   True,
    "THRESHOLD_LOOSEN":   True,
    "THRESHOLD_TIGHTEN":  True,
    "WEIGHT_BOOST":       True,
    "WEIGHT_TRIM":        True,
    "SYMBOL_COOLDOWN":    True,
    "PROMOTION_RETRY":    True,
}


def get_state() -> dict[str, Any]:
    return {
        "enabled": os.getenv("SPOT_REPAIR_ENABLED", "false").lower() == "true",
        "dry_run": DRY_RUN,
        "running": _running,
        "last_run": _last_run,
        "next_run": _next_run,
        "last_error": _last_error,
        "action_count_24h": _action_count_24h,
        "interval_sec": INTERVAL_SEC,
        "action_enabled": dict(_action_enabled),
    }


def set_action_enabled(action_type: str, enabled: bool) -> bool:
    if action_type not in _action_enabled:
        return False
    _action_enabled[action_type] = enabled
    return True


# ─── Rate limit helper ─────────────────────────────────────────────────────
async def _count_actions_in_last_hour(session, action_type: str) -> int:
    cutoff = time.time() - 3600
    rows = (await session.execute(
        select(SpotRepairAction).where(
            and_(
                SpotRepairAction.action_type == action_type,
                SpotRepairAction.detected_at >= cutoff,
                SpotRepairAction.status.in_(["applied", "dry_run"]),
            )
        )
    )).scalars().all()
    return len(rows)


async def _log_action(
    session,
    *,
    action_type: str,
    target_key: str,
    reason: str,
    before: dict,
    after: dict,
    status: str = "applied",
    source: str = "auto",
    affected_count: int = 0,
    is_material: bool = True,
    expires_at: Optional[float] = None,
    revert_of: Optional[int] = None,
    error: Optional[str] = None,
    note: Optional[str] = None,
    before_metric: Optional[float] = None,
) -> SpotRepairAction:
    now = time.time()
    row = SpotRepairAction(
        detected_at=now,
        applied_at=now if status == "applied" else None,
        expires_at=expires_at,
        action_type=action_type,
        target_key=target_key,
        source=source,
        reason=reason[:240],
        before_json=json.dumps(before, ensure_ascii=False, default=str),
        after_json=json.dumps(after, ensure_ascii=False, default=str),
        status=status,
        affected_count=affected_count,
        is_material=is_material,
        revert_of=revert_of,
        error=error[:240] if error else None,
        note=note[:240] if note else None,
        updated_at=now,
        before_metric=before_metric,
    )
    session.add(row)
    await session.flush()
    return row


# ─── Metric readers ────────────────────────────────────────────────────────
async def _read_engine_snapshot(session) -> dict[str, float]:
    """Snapshot ringan yang dibutuhkan rule-engine (tanpa memuat semua ledger).

    Definisi selaras dengan `/signals/adaptive-engine`:
      - due     = events yang usianya ≥24 jam (scan_ts <= now - 86400)
      - labelled = due & pnl_24h_pct not null
      - completeness = labelled / due
    Metric window "24h terakhir" (opened, rejected, WR) pakai window
    `[now-86400, now]`.
    """
    from sqlalchemy import func

    now = time.time()
    last_24h = now - 86400

    # Overall completeness (age ≥24h) — inilah yang menghambat gate promosi
    due = (await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts <= now - 86400,
        )
    )).scalar_one() or 0

    labelled = (await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts <= now - 86400,
            SpotDecisionEvent.pnl_24h_pct.is_not(None),
        )
    )).scalar_one() or 0

    # Window 24h terakhir untuk aktivitas trading & rejection
    opened_24h = (await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts >= last_24h,
            SpotDecisionEvent.opened == True,  # noqa: E712
        )
    )).scalar_one() or 0

    rejected_below_thresh_24h = (await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts >= last_24h,
            SpotDecisionEvent.reason_code == "below_auto_threshold",
        )
    )).scalar_one() or 0

    # Mature samples = event dengan feature snapshot & pnl_24h ada
    mature_samples = (await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.pnl_24h_pct.is_not(None),
        )
    )).scalar_one() or 0

    # Realized WR 24h terakhir dari trade yang tertutup
    wr_num = (await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.closed_at >= last_24h,
            SpotDecisionEvent.realized_pnl_pct > 0,
        )
    )).scalar_one() or 0
    wr_den = (await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.closed_at >= last_24h,
            SpotDecisionEvent.realized_pnl_pct.is_not(None),
        )
    )).scalar_one() or 0

    completeness_pct = (labelled / due * 100.0) if due else 100.0
    wr_24h = (wr_num / wr_den) if wr_den else None

    return {
        "completeness_pct": round(completeness_pct, 2),
        "total_due": int(due),
        "labelled": int(labelled),
        "opened_24h": int(opened_24h),
        "rejected_below_thresh_24h": int(rejected_below_thresh_24h),
        "mature_samples": int(mature_samples),
        "realized_wr_24h": wr_24h,
        "realized_wr_den": int(wr_den),
    }


async def _get_auto_open_score(session) -> tuple[float, Optional[AgentConfig]]:
    row = (await session.execute(
        select(AgentConfig).where(
            AgentConfig.agent_group == "spot",
            AgentConfig.key == "auto_open_score",
        )
    )).scalar_one_or_none()
    if row:
        return float(row.value_num), row
    return DEFAULT_AUTO_OPEN_SCORE, None


async def _set_auto_open_score(session, new_value: float, note: str) -> AgentConfig:
    row = (await session.execute(
        select(AgentConfig).where(
            AgentConfig.agent_group == "spot",
            AgentConfig.key == "auto_open_score",
        )
    )).scalar_one_or_none()
    now = time.time()
    if row is None:
        row = AgentConfig(
            agent_group="spot",
            key="auto_open_score",
            value_num=float(new_value),
            default_num=DEFAULT_AUTO_OPEN_SCORE,
            description="Skor RAW minimum untuk auto-open SPOT (dikelola SpotRepairAgent).",
            category="threshold",
            updated_at=now,
            updated_by=f"spot_repair:{note}"[:40],
        )
        session.add(row)
    else:
        row.value_num = float(new_value)
        row.updated_at = now
        row.updated_by = f"spot_repair:{note}"[:40]
    await session.flush()
    return row


# ─── Action: OUTCOME_BACKFILL ──────────────────────────────────────────────
async def _do_outcome_backfill(session, snap: dict) -> Optional[SpotRepairAction]:
    if not _action_enabled["OUTCOME_BACKFILL"]:
        return None
    if snap["completeness_pct"] >= BACKFILL_MIN_COMPLETENESS_PCT:
        return None

    if await _count_actions_in_last_hour(session, "OUTCOME_BACKFILL") >= MAX_ACTIONS_PER_TYPE_PER_HOUR:
        return None

    if DRY_RUN:
        return await _log_action(
            session,
            action_type="OUTCOME_BACKFILL",
            target_key="*",
            reason=f"completeness {snap['completeness_pct']}% < {BACKFILL_MIN_COMPLETENESS_PCT}%",
            before={"completeness_pct": snap["completeness_pct"]},
            after={"completeness_pct": snap["completeness_pct"], "note": "dry-run"},
            status="dry_run",
            affected_count=0,
            is_material=False,
        )

    from agents.opportunity.outcome_tracker import update_decision_outcomes

    total_updated = 0
    for _ in range(BACKFILL_MAX_BATCHES):
        try:
            n = await update_decision_outcomes()
        except Exception as exc:
            logger.warning("spot_repair_backfill_batch_error", error=str(exc)[:200])
            return await _log_action(
                session,
                action_type="OUTCOME_BACKFILL",
                target_key="*",
                reason=f"completeness {snap['completeness_pct']}%",
                before={"completeness_pct": snap["completeness_pct"]},
                after={"updated": total_updated},
                status="failed",
                affected_count=total_updated,
                error=str(exc)[:200],
            )
        if not n:
            break
        total_updated += int(n)

    return await _log_action(
        session,
        action_type="OUTCOME_BACKFILL",
        target_key="*",
        reason=(
            f"completeness {snap['completeness_pct']}% < "
            f"{BACKFILL_MIN_COMPLETENESS_PCT}%"
        ),
        before={"completeness_pct": snap["completeness_pct"]},
        after={"events_updated": total_updated},
        affected_count=total_updated,
        before_metric=float(snap["completeness_pct"]),
    )


# ─── Action: THRESHOLD_LOOSEN / TIGHTEN ────────────────────────────────────
async def _do_threshold_adjust(session, snap: dict) -> Optional[SpotRepairAction]:
    now = time.time()
    current, _ = await _get_auto_open_score(session)

    # LOOSEN
    if (
        _action_enabled["THRESHOLD_LOOSEN"]
        and snap["opened_24h"] < LOOSEN_MAX_OPENED_24H
        and snap["rejected_below_thresh_24h"] >= LOOSEN_MIN_REJECTIONS
        and snap["mature_samples"] >= LOOSEN_MIN_MATURE_SAMPLES
        and current - LOOSEN_STEP >= AUTO_OPEN_SCORE_FLOOR
    ):
        if await _count_actions_in_last_hour(session, "THRESHOLD_LOOSEN") >= MAX_ACTIONS_PER_TYPE_PER_HOUR:
            return None
        new_value = round(current - LOOSEN_STEP, 2)
        reason = (
            f"opened_24h={snap['opened_24h']}<{LOOSEN_MAX_OPENED_24H}, "
            f"rejected_below_thresh={snap['rejected_below_thresh_24h']} — starving"
        )
        if DRY_RUN:
            return await _log_action(
                session,
                action_type="THRESHOLD_LOOSEN",
                target_key="spot.auto_open_score",
                reason=reason,
                before={"auto_open_score": current},
                after={"auto_open_score": new_value, "note": "dry-run"},
                status="dry_run",
                is_material=False,
            )
        await _set_auto_open_score(session, new_value, "LOOSEN")
        return await _log_action(
            session,
            action_type="THRESHOLD_LOOSEN",
            target_key="spot.auto_open_score",
            reason=reason,
            before={"auto_open_score": current},
            after={"auto_open_score": new_value},
            expires_at=now + THRESHOLD_TTL_SEC,
            before_metric=float(snap["opened_24h"]),
        )

    # TIGHTEN
    if (
        _action_enabled["THRESHOLD_TIGHTEN"]
        and snap["realized_wr_24h"] is not None
        and snap["realized_wr_24h"] < TIGHTEN_MAX_WR_24H
        and snap["opened_24h"] >= TIGHTEN_MIN_OPENED_24H
        and current + TIGHTEN_STEP <= AUTO_OPEN_SCORE_CEIL
    ):
        if await _count_actions_in_last_hour(session, "THRESHOLD_TIGHTEN") >= MAX_ACTIONS_PER_TYPE_PER_HOUR:
            return None
        new_value = round(current + TIGHTEN_STEP, 2)
        reason = (
            f"WR 24h {snap['realized_wr_24h']:.1%} < {TIGHTEN_MAX_WR_24H:.0%} "
            f"pada {snap['opened_24h']} trade — proteksi"
        )
        if DRY_RUN:
            return await _log_action(
                session,
                action_type="THRESHOLD_TIGHTEN",
                target_key="spot.auto_open_score",
                reason=reason,
                before={"auto_open_score": current},
                after={"auto_open_score": new_value, "note": "dry-run"},
                status="dry_run",
                is_material=False,
            )
        await _set_auto_open_score(session, new_value, "TIGHTEN")
        return await _log_action(
            session,
            action_type="THRESHOLD_TIGHTEN",
            target_key="spot.auto_open_score",
            reason=reason,
            before={"auto_open_score": current},
            after={"auto_open_score": new_value},
            expires_at=now + THRESHOLD_TTL_SEC,
            before_metric=(float(snap["realized_wr_24h"])
                           if snap.get("realized_wr_24h") is not None else None),
        )

    return None


# ─── Action: WEIGHT_BOOST / TRIM ───────────────────────────────────────────
async def _do_weight_tune(session) -> list[SpotRepairAction]:
    if not (_action_enabled["WEIGHT_BOOST"] or _action_enabled["WEIGHT_TRIM"]):
        return []

    # Skip kalau weight_updater baru saja jalan (<60s)
    try:
        from agents.opportunity.weight_updater import get_state as wu_state
        st = wu_state()
        if st.get("last_run") and time.time() - float(st["last_run"]) < 60:
            return []
    except Exception:
        pass

    rows = (await session.execute(
        select(AgentSignalWeight).where(
            AgentSignalWeight.agent == SPOT_AGENT_KEY,
        )
    )).scalars().all()

    logged: list[SpotRepairAction] = []
    boost_used = await _count_actions_in_last_hour(session, "WEIGHT_BOOST")
    trim_used = await _count_actions_in_last_hour(session, "WEIGHT_TRIM")

    for row in rows:
        if row.total_count < WEIGHT_MIN_SAMPLES:
            continue

        wr = float(row.win_rate or 0.0)
        w = float(row.weight or 1.0)

        # BOOST
        if (
            _action_enabled["WEIGHT_BOOST"]
            and wr >= WEIGHT_BOOST_MIN_WR
            and w + WEIGHT_STEP <= WEIGHT_MAX
            and boost_used < MAX_ACTIONS_PER_TYPE_PER_HOUR
        ):
            new_w = round(min(WEIGHT_MAX, w + WEIGHT_STEP), 4)
            reason = f"WR {wr:.1%} n={row.total_count} — boost"
            if DRY_RUN:
                logged.append(await _log_action(
                    session,
                    action_type="WEIGHT_BOOST",
                    target_key=f"{row.signal_key}@{row.regime}",
                    reason=reason,
                    before={"weight": w, "wr": wr, "n": row.total_count},
                    after={"weight": new_w, "note": "dry-run"},
                    status="dry_run",
                    is_material=False,
                ))
            else:
                row.weight = new_w
                row.updated_at = time.time()
                logged.append(await _log_action(
                    session,
                    action_type="WEIGHT_BOOST",
                    target_key=f"{row.signal_key}@{row.regime}",
                    reason=reason,
                    before={"weight": w, "wr": wr, "n": row.total_count},
                    after={"weight": new_w},
                    before_metric=float(wr),
                ))
                boost_used += 1
            continue

        # TRIM
        if (
            _action_enabled["WEIGHT_TRIM"]
            and wr <= WEIGHT_TRIM_MAX_WR
            and w - WEIGHT_STEP >= WEIGHT_MIN
            and trim_used < MAX_ACTIONS_PER_TYPE_PER_HOUR
        ):
            new_w = round(max(WEIGHT_MIN, w - WEIGHT_STEP), 4)
            reason = f"WR {wr:.1%} n={row.total_count} — trim"
            if DRY_RUN:
                logged.append(await _log_action(
                    session,
                    action_type="WEIGHT_TRIM",
                    target_key=f"{row.signal_key}@{row.regime}",
                    reason=reason,
                    before={"weight": w, "wr": wr, "n": row.total_count},
                    after={"weight": new_w, "note": "dry-run"},
                    status="dry_run",
                    is_material=False,
                ))
            else:
                row.weight = new_w
                row.updated_at = time.time()
                logged.append(await _log_action(
                    session,
                    action_type="WEIGHT_TRIM",
                    target_key=f"{row.signal_key}@{row.regime}",
                    reason=reason,
                    before={"weight": w, "wr": wr, "n": row.total_count},
                    after={"weight": new_w},
                    before_metric=float(wr),
                ))
                trim_used += 1

    return logged


# ─── TTL scanner — auto-reverse aksi kadaluarsa ────────────────────────────
async def _do_ttl_reverse(session) -> list[SpotRepairAction]:
    now = time.time()
    expired = (await session.execute(
        select(SpotRepairAction).where(
            and_(
                SpotRepairAction.status == "applied",
                SpotRepairAction.expires_at.is_not(None),
                SpotRepairAction.expires_at <= now,
                SpotRepairAction.action_type.in_(
                    ["THRESHOLD_LOOSEN", "THRESHOLD_TIGHTEN"]
                ),
            )
        ).order_by(SpotRepairAction.expires_at)
    )).scalars().all()

    reverts: list[SpotRepairAction] = []
    for act in expired:
        try:
            before = json.loads(act.before_json or "{}")
        except json.JSONDecodeError:
            act.status = "failed"
            act.error = "invalid before_json"
            continue

        if act.action_type in ("THRESHOLD_LOOSEN", "THRESHOLD_TIGHTEN"):
            original = before.get("auto_open_score")
            if original is None:
                act.status = "failed"
                act.error = "no original auto_open_score in before_json"
                continue
            current, _ = await _get_auto_open_score(session)
            await _set_auto_open_score(session, float(original), "TTL_REVERSE")
            act.status = "reversed"
            act.reversed_at = now
            reverts.append(await _log_action(
                session,
                action_type=act.action_type,
                target_key=act.target_key,
                reason=f"TTL expired setelah {THRESHOLD_TTL_SEC//3600} jam",
                before={"auto_open_score": current},
                after={"auto_open_score": float(original)},
                source="ttl_reverse",
                revert_of=act.id,
            ))
    return reverts


# ─── Main loop ─────────────────────────────────────────────────────────────
async def run_spot_repair_loop() -> None:
    """Loop utama SPOT Adaptive Repair Agent."""
    global _running, _last_run, _next_run, _last_error, _action_count_24h

    logger.info("spot_repair_loop_starting",
                interval_sec=INTERVAL_SEC, startup_delay=STARTUP_DELAY,
                dry_run=DRY_RUN)

    await asyncio.sleep(STARTUP_DELAY)

    while True:
        _running = True
        _next_run = time.time() + INTERVAL_SEC
        try:
            if not is_db_available():
                await asyncio.sleep(INTERVAL_SEC)
                continue

            actions_this_cycle = 0

            async with AsyncSessionLocal() as session:
                # 1) TTL scanner dulu — pulihkan aksi kadaluarsa
                reverts = await _do_ttl_reverse(session)
                actions_this_cycle += len(reverts)

                # 2) Backfill outcome (paling penting untuk gate promosi)
                snap = await _read_engine_snapshot(session)
                bf = await _do_outcome_backfill(session, snap)
                if bf:
                    actions_this_cycle += 1

                # Re-read snapshot setelah backfill (completeness bisa berubah)
                if bf and bf.affected_count > 0:
                    snap = await _read_engine_snapshot(session)

                # 3) Threshold adjustment
                th = await _do_threshold_adjust(session, snap)
                if th:
                    actions_this_cycle += 1

                # 4) Weight tuning
                w_acts = await _do_weight_tune(session)
                actions_this_cycle += len(w_acts)

                await session.commit()

                # Refresh 24h action count
                cutoff = time.time() - 86400
                _action_count_24h = int((await session.execute(
                    select(SpotRepairAction).where(
                        SpotRepairAction.detected_at >= cutoff,
                        SpotRepairAction.is_material == True,  # noqa: E712
                    )
                )).scalars().all().__len__())

            _last_run = time.time()
            _last_error = None
            logger.info(
                "spot_repair_cycle_done",
                actions=actions_this_cycle,
                completeness_pct=snap.get("completeness_pct"),
                opened_24h=snap.get("opened_24h"),
                mature_samples=snap.get("mature_samples"),
                dry_run=DRY_RUN,
            )
        except asyncio.CancelledError:
            _running = False
            logger.info("spot_repair_loop_cancelled")
            return
        except Exception as exc:
            _last_error = str(exc)[:240]
            logger.exception("spot_repair_cycle_failed", error=_last_error)

        await asyncio.sleep(INTERVAL_SEC)


# ─── API helpers ───────────────────────────────────────────────────────────
async def list_recent_actions(
    hours: int = 72,
    limit: int = 100,
    action_type: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    if not is_db_available():
        return []
    cutoff = time.time() - hours * 3600
    async with AsyncSessionLocal() as session:
        q = select(SpotRepairAction).where(SpotRepairAction.detected_at >= cutoff)
        if action_type:
            q = q.where(SpotRepairAction.action_type == action_type)
        if status:
            q = q.where(SpotRepairAction.status == status)
        q = q.order_by(desc(SpotRepairAction.detected_at)).limit(limit)
        rows = (await session.execute(q)).scalars().all()

    def _pack(r: SpotRepairAction) -> dict:
        try:
            before = json.loads(r.before_json or "{}")
            after = json.loads(r.after_json or "{}")
        except json.JSONDecodeError:
            before, after = {}, {}
        return {
            "id": r.id,
            "detected_at": r.detected_at,
            "applied_at": r.applied_at,
            "expires_at": r.expires_at,
            "reversed_at": r.reversed_at,
            "action_type": r.action_type,
            "target_key": r.target_key,
            "source": r.source,
            "reason": r.reason,
            "status": r.status,
            "affected_count": r.affected_count,
            "is_material": r.is_material,
            "before": before,
            "after": after,
            "revert_of": r.revert_of,
            "error": r.error,
            "note": r.note,
        }

    return [_pack(r) for r in rows]


async def rollback_action(action_id: int) -> dict:
    """Rollback aksi tertentu bila reversible dan belum di-reverse."""
    if not is_db_available():
        return {"ok": False, "error": "db unavailable"}
    async with AsyncSessionLocal() as session:
        act = await session.get(SpotRepairAction, action_id)
        if act is None:
            return {"ok": False, "error": "not found"}
        if act.status != "applied":
            return {"ok": False, "error": f"cannot rollback status={act.status}"}
        try:
            before = json.loads(act.before_json or "{}")
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid before_json"}

        if act.action_type in ("THRESHOLD_LOOSEN", "THRESHOLD_TIGHTEN"):
            original = before.get("auto_open_score")
            if original is None:
                return {"ok": False, "error": "no auto_open_score in before"}
            current, _ = await _get_auto_open_score(session)
            await _set_auto_open_score(session, float(original), "MANUAL_ROLLBACK")
            act.status = "reversed"
            act.reversed_at = time.time()
            new_row = await _log_action(
                session,
                action_type=act.action_type,
                target_key=act.target_key,
                reason=f"Manual rollback dari #{act.id}",
                before={"auto_open_score": current},
                after={"auto_open_score": float(original)},
                source="manual",
                revert_of=act.id,
            )
            await session.commit()
            return {"ok": True, "new_action_id": new_row.id}

        if act.action_type in ("WEIGHT_BOOST", "WEIGHT_TRIM"):
            original_weight = before.get("weight")
            if original_weight is None:
                return {"ok": False, "error": "no weight in before"}
            # target_key format: signal_key@regime
            parts = (act.target_key or "").split("@", 1)
            sig_key = parts[0]
            regime = parts[1] if len(parts) > 1 else "all"
            row = (await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.agent == SPOT_AGENT_KEY,
                    AgentSignalWeight.signal_key == sig_key,
                    AgentSignalWeight.regime == regime,
                )
            )).scalar_one_or_none()
            if row is None:
                return {"ok": False, "error": "weight row missing"}
            row.weight = float(original_weight)
            row.updated_at = time.time()
            act.status = "reversed"
            act.reversed_at = time.time()
            new_row = await _log_action(
                session,
                action_type=act.action_type,
                target_key=act.target_key,
                reason=f"Manual rollback dari #{act.id}",
                before={"weight": None},
                after={"weight": float(original_weight)},
                source="manual",
                revert_of=act.id,
            )
            await session.commit()
            return {"ok": True, "new_action_id": new_row.id}

        return {"ok": False, "error": f"rollback belum didukung untuk {act.action_type}"}


async def execute_manual(action_type: str) -> dict:
    """Trigger 1 siklus aksi tertentu (manual override). Semua guardrail tetap berlaku."""
    if not is_db_available():
        return {"ok": False, "error": "db unavailable"}
    if action_type not in _action_enabled:
        return {"ok": False, "error": f"action_type tidak dikenal: {action_type}"}
    async with AsyncSessionLocal() as session:
        snap = await _read_engine_snapshot(session)
        result: dict[str, Any] = {"action_type": action_type, "triggered": False}
        acts: list[SpotRepairAction] = []
        try:
            if action_type == "OUTCOME_BACKFILL":
                a = await _do_outcome_backfill(session, snap)
                if a:
                    acts.append(a)
            elif action_type in ("THRESHOLD_LOOSEN", "THRESHOLD_TIGHTEN"):
                a = await _do_threshold_adjust(session, snap)
                if a:
                    acts.append(a)
            elif action_type in ("WEIGHT_BOOST", "WEIGHT_TRIM"):
                acts.extend(await _do_weight_tune(session))
            else:
                return {"ok": False, "error": f"manual belum didukung untuk {action_type}"}
            await session.commit()
        except Exception as exc:
            await session.rollback()
            return {"ok": False, "error": str(exc)[:240]}
        result["triggered"] = len(acts) > 0
        result["action_ids"] = [a.id for a in acts]
        return {"ok": True, **result}


# ─── Direct apply — dipakai UI Saran Engine untuk klik "Terapkan" ─────────
async def apply_weight_step(
    signal_key: str,
    regime: str,
    delta: float,
    label: str = "",
) -> dict:
    """Terapkan step bobot bounded pada 1 sinyal SPOT.

    Semua guardrail dari WEIGHT_BOOST/TRIM tetap berlaku:
      - bounds  WEIGHT_MIN..WEIGHT_MAX
      - rate-limit MAX_ACTIONS_PER_TYPE_PER_HOUR
      - step maksimum ±WEIGHT_STEP (delta lebih besar akan dipotong)
    Ledger tercatat source='suggestion' agar terpisah dari aksi otomatis.
    """
    if not is_db_available():
        return {"ok": False, "error": "db unavailable"}
    if delta == 0:
        return {"ok": False, "error": "delta 0"}
    delta = max(-WEIGHT_STEP, min(WEIGHT_STEP, float(delta)))
    action_type = "WEIGHT_BOOST" if delta > 0 else "WEIGHT_TRIM"
    if not _action_enabled[action_type]:
        return {"ok": False, "error": f"{action_type} sedang di-disable"}

    async with AsyncSessionLocal() as session:
        used = await _count_actions_in_last_hour(session, action_type)
        if used >= MAX_ACTIONS_PER_TYPE_PER_HOUR:
            return {"ok": False, "error": f"rate-limit {used}/{MAX_ACTIONS_PER_TYPE_PER_HOUR}/jam"}

        row = (await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.agent == SPOT_AGENT_KEY,
                AgentSignalWeight.signal_key == signal_key,
                AgentSignalWeight.regime == regime,
            )
        )).scalar_one_or_none()
        if row is None:
            return {"ok": False, "error": "sinyal tidak ditemukan"}
        w = float(row.weight or 1.0)
        wr = float(row.win_rate or 0.0)
        new_w = round(max(WEIGHT_MIN, min(WEIGHT_MAX, w + delta)), 4)
        if new_w == w:
            return {"ok": False, "error": "bobot sudah di batas"}

        row.weight = new_w
        row.updated_at = time.time()
        act = await _log_action(
            session,
            action_type=action_type,
            target_key=f"{signal_key}@{regime}",
            reason=(label or f"manual apply Δ={delta:+.2f}")[:240],
            before={"weight": w, "wr": wr, "n": int(row.total_count or 0)},
            after={"weight": new_w},
            source="suggestion",
            before_metric=wr,
        )
        await session.commit()
        return {
            "ok": True, "action_id": act.id,
            "before": w, "after": new_w, "delta": round(new_w - w, 4),
        }


async def get_pending_recommendations() -> list[dict]:
    """Preview aksi WEIGHT_BOOST/TRIM yang MEMENUHI SYARAT tapi belum diterapkan.

    Mirip apa yang akan agent lakukan pass berikutnya, tapi tidak dieksekusi.
    Dipakai UI Saran Engine subtab untuk daftar saran auto-applicable.
    """
    if not is_db_available():
        return []
    recs: list[dict] = []
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.agent == SPOT_AGENT_KEY,
            )
        )).scalars().all()
        for row in rows:
            n = int(row.total_count or 0)
            if n < WEIGHT_MIN_SAMPLES:
                continue
            wr = float(row.win_rate or 0.0)
            w = float(row.weight or 1.0)
            if wr >= WEIGHT_BOOST_MIN_WR and w + WEIGHT_STEP <= WEIGHT_MAX:
                recs.append({
                    "agent": SPOT_AGENT_KEY,
                    "signal_key": row.signal_key,
                    "regime": row.regime or "all",
                    "current_weight": w, "new_weight": round(w + WEIGHT_STEP, 4),
                    "delta": WEIGHT_STEP, "wr": wr, "n": n,
                    "action": "weight_up",
                    "reason": f"WR {wr:.1%} pada {n} sampel (≥{WEIGHT_BOOST_MIN_WR:.0%})",
                    "apply": {
                        "type": "weight",
                        "agent": SPOT_AGENT_KEY,
                        "signal_key": row.signal_key,
                        "regime": row.regime or "all",
                        "delta": WEIGHT_STEP,
                        "label": f"SPOT ×{w:.2f} → ×{round(w + WEIGHT_STEP, 2):.2f}",
                        "endpoint": "/api/v1/spot-repair/apply",
                    },
                })
            elif wr <= WEIGHT_TRIM_MAX_WR and w - WEIGHT_STEP >= WEIGHT_MIN:
                recs.append({
                    "agent": SPOT_AGENT_KEY,
                    "signal_key": row.signal_key,
                    "regime": row.regime or "all",
                    "current_weight": w, "new_weight": round(w - WEIGHT_STEP, 4),
                    "delta": -WEIGHT_STEP, "wr": wr, "n": n,
                    "action": "weight_down",
                    "reason": f"WR {wr:.1%} pada {n} sampel (≤{WEIGHT_TRIM_MAX_WR:.0%})",
                    "apply": {
                        "type": "weight",
                        "agent": SPOT_AGENT_KEY,
                        "signal_key": row.signal_key,
                        "regime": row.regime or "all",
                        "delta": -WEIGHT_STEP,
                        "label": f"SPOT ×{w:.2f} → ×{round(w - WEIGHT_STEP, 2):.2f}",
                        "endpoint": "/api/v1/spot-repair/apply",
                    },
                })
    recs.sort(key=lambda r: (r["action"] != "weight_down", -abs(r["wr"] - 0.5)))
    return recs
