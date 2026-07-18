"""SPOT Repair Verifier — before/after untuk semua aksi repair SPOT.

Sekali pass tiap `SPOT_REPAIR_VERIFY_INTERVAL_SEC` (default 6 jam).
Aksi berusia ≥24 jam yang statusnya masih `applied` diukur ulang:

  - WEIGHT_BOOST/TRIM: WR sinyal-agnostik pada trade SPOT yang dibuka SETELAH
    `applied_at`. Butuh minimal MIN_AFTER_N=8 sampel.
      • BOOST: after_wr ≥ 0.55 → verified_improved
                after_wr < 0.40 → REVERT (tulis baris baru revert_of=id)
                lain-lain      → verified_no_change
      • TRIM  : after_wr ≤ 0.35 → verified_improved (trim benar—sinyal buruk)
                after_wr ≥ 0.55 → REVERT
                lain-lain      → verified_no_change

  - THRESHOLD_LOOSEN: opened_24h SETELAH applied_at.
      • opened_after ≥ 10  → verified_improved
      • opened_after < 3   → verified_no_change (loosen tidak mengalirkan trade)
      • lain-lain          → verified_no_change

  - THRESHOLD_TIGHTEN: WR window setelah applied_at.
      • after_wr ≥ 0.45 → verified_improved (tighten memproteksi WR)
      • after_wr < 0.30 & opened_after ≥ 5 → REVERT
      • lain-lain      → verified_no_change

  - OUTCOME_BACKFILL: completeness_pct sekarang vs before_metric.
      • after_pct - before_pct ≥ 5 → verified_improved
      • lain-lain                  → verified_no_change  (backfill tidak di-revert)

Sampel setelah tidak cukup + umur >7 hari → verified_no_change (insufficient).
Revert kena cooldown 48 jam per target_key (anti flip-flop).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

import structlog
from sqlalchemy import and_, func, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.agent_config import AgentConfig
from app.models.signal_weight import AgentSignalWeight
from app.models.spot_decision_event import SpotDecisionEvent
from app.models.spot_repair_action import SpotRepairAction

logger = structlog.get_logger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────
INTERVAL_SEC = int(os.getenv("SPOT_REPAIR_VERIFY_INTERVAL_SEC", "21600"))  # 6 jam
STARTUP_DELAY = int(os.getenv("SPOT_REPAIR_VERIFY_STARTUP_DELAY", "180"))
DRY_RUN = os.getenv("SPOT_REPAIR_DRY_RUN", "false").lower() == "true"

VERIFY_AFTER_H = 24.0
GIVEUP_DAYS = 7.0
MIN_AFTER_N = 8

WEIGHT_BOOST_IMPROVED_GE = 0.55
WEIGHT_BOOST_REVERT_LT = 0.40
WEIGHT_TRIM_IMPROVED_LE = 0.35
WEIGHT_TRIM_REVERT_GE = 0.55

THR_LOOSEN_IMPROVED_OPENED = 10
THR_LOOSEN_NEUTRAL_OPENED = 3

THR_TIGHTEN_IMPROVED_WR = 0.45
THR_TIGHTEN_REVERT_WR = 0.30
THR_TIGHTEN_MIN_OPENED = 5

BACKFILL_IMPROVED_DELTA_PCT = 5.0

COOLDOWN_REVERT_H = 48.0
WEIGHT_STEP = 0.05
AUTO_OPEN_SCORE_FLOOR = 78.0
AUTO_OPEN_SCORE_CEIL = 95.0

# ─── State ─────────────────────────────────────────────────────────────────
_status: dict[str, Any] = {
    "last_run": None,
    "verified_last_run": 0,
    "reverted_total": 0,
    "next_run": None,
    "last_error": None,
    "interval_sec": INTERVAL_SEC,
}


def get_status() -> dict[str, Any]:
    return dict(_status)


# ─── Metric readers ────────────────────────────────────────────────────────
async def _wr_spot_after(session, applied_at: float) -> tuple[Optional[float], int]:
    """Realized WR pada trade SPOT yang tertutup setelah `applied_at`."""
    now = time.time()
    den = int((await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.closed_at >= applied_at,
            SpotDecisionEvent.closed_at <= now,
            SpotDecisionEvent.realized_pnl_pct.is_not(None),
        )
    )).scalar_one() or 0)
    if den == 0:
        return None, 0
    num = int((await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.closed_at >= applied_at,
            SpotDecisionEvent.closed_at <= now,
            SpotDecisionEvent.realized_pnl_pct > 0,
        )
    )).scalar_one() or 0)
    return num / den, den


async def _opened_after(session, applied_at: float) -> int:
    now = time.time()
    return int((await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts >= applied_at,
            SpotDecisionEvent.scan_ts <= now,
            SpotDecisionEvent.opened == True,  # noqa: E712
        )
    )).scalar_one() or 0)


async def _current_completeness_pct(session) -> float:
    now = time.time()
    due = int((await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts <= now - 86400,
        )
    )).scalar_one() or 0)
    if due == 0:
        return 100.0
    labelled = int((await session.execute(
        select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts <= now - 86400,
            SpotDecisionEvent.pnl_24h_pct.is_not(None),
        )
    )).scalar_one() or 0)
    return round(labelled / due * 100.0, 2)


async def _has_recent_revert(session, target_key: str, hours: float) -> bool:
    cutoff = time.time() - hours * 3600
    n = int((await session.execute(
        select(func.count(SpotRepairAction.id)).where(
            SpotRepairAction.target_key == target_key,
            SpotRepairAction.source == "verifier",
            SpotRepairAction.detected_at >= cutoff,
        )
    )).scalar_one() or 0)
    return n > 0


# ─── Revert executors ──────────────────────────────────────────────────────
async def _revert_weight(session, orig: SpotRepairAction, before_weight: float,
                          after_wr: float, after_n: int) -> Optional[SpotRepairAction]:
    parts = (orig.target_key or "").split("@", 1)
    sig_key = parts[0]
    regime = parts[1] if len(parts) > 1 else "all"
    row = (await session.execute(
        select(AgentSignalWeight).where(
            AgentSignalWeight.agent == "opportunity_spot",
            AgentSignalWeight.signal_key == sig_key,
            AgentSignalWeight.regime == regime,
        )
    )).scalar_one_or_none()
    if row is None:
        return None
    current = float(row.weight or 1.0)
    row.weight = float(before_weight)
    row.updated_at = time.time()
    now = time.time()
    reason = f"verifier revert #{orig.id} — WR sesudah {after_wr:.1%} pada {after_n} trade"
    revert_row = SpotRepairAction(
        detected_at=now, applied_at=now,
        action_type=orig.action_type,
        target_key=orig.target_key,
        source="verifier",
        reason=reason[:240],
        before_json=json.dumps({"weight": current}, default=str),
        after_json=json.dumps({"weight": float(before_weight)}, default=str),
        status="applied",
        affected_count=1,
        is_material=True,
        revert_of=orig.id,
        before_metric=after_wr,
        after_metric=None,
        updated_at=now,
    )
    session.add(revert_row)
    await session.flush()
    return revert_row


async def _revert_threshold(session, orig: SpotRepairAction, before_score: float,
                             after_wr: Optional[float], opened_after: int) -> Optional[SpotRepairAction]:
    row = (await session.execute(
        select(AgentConfig).where(
            AgentConfig.agent_group == "spot",
            AgentConfig.key == "auto_open_score",
        )
    )).scalar_one_or_none()
    if row is None:
        return None
    current = float(row.value_num)
    row.value_num = float(before_score)
    row.updated_at = time.time()
    row.updated_by = "spot_verifier:REVERT"
    now = time.time()
    wr_txt = f"{after_wr:.1%}" if after_wr is not None else "n/a"
    reason = f"verifier revert #{orig.id} — WR {wr_txt} pada {opened_after} trade"
    revert_row = SpotRepairAction(
        detected_at=now, applied_at=now,
        action_type=orig.action_type,
        target_key=orig.target_key,
        source="verifier",
        reason=reason[:240],
        before_json=json.dumps({"auto_open_score": current}, default=str),
        after_json=json.dumps({"auto_open_score": float(before_score)}, default=str),
        status="applied",
        affected_count=1,
        is_material=True,
        revert_of=orig.id,
        before_metric=after_wr,
        after_metric=None,
        updated_at=now,
    )
    session.add(revert_row)
    await session.flush()
    return revert_row


# ─── Per-action verification ───────────────────────────────────────────────
async def _verify_weight(session, act: SpotRepairAction) -> tuple[str, Optional[float]]:
    before = {}
    try:
        before = json.loads(act.before_json or "{}")
    except json.JSONDecodeError:
        pass
    after_wr, after_n = await _wr_spot_after(session, act.applied_at or act.detected_at)
    if after_wr is None or after_n < MIN_AFTER_N:
        age_days = (time.time() - (act.applied_at or act.detected_at)) / 86400
        if age_days > GIVEUP_DAYS:
            act.after_metric = after_wr
            act.status = "verified_no_change"
            act.verified_at = time.time()
            act.note = (act.note or "") + f" | insufficient after-samples n={after_n}"
            return "no_change", after_wr
        return "pending", None

    boost = act.action_type == "WEIGHT_BOOST"
    if boost:
        should_revert = after_wr < WEIGHT_BOOST_REVERT_LT
        improved = after_wr >= WEIGHT_BOOST_IMPROVED_GE
    else:
        should_revert = after_wr >= WEIGHT_TRIM_REVERT_GE
        improved = after_wr <= WEIGHT_TRIM_IMPROVED_LE

    act.after_metric = round(after_wr, 4)

    if should_revert and not await _has_recent_revert(session, act.target_key, COOLDOWN_REVERT_H):
        before_w = float(before.get("weight", 1.0))
        rev = await _revert_weight(session, act, before_w, after_wr, after_n)
        if rev is not None:
            act.status = "reverted"
            act.verified_at = time.time()
            return "reverted", after_wr

    if improved:
        act.status = "verified_improved"
    else:
        act.status = "verified_no_change"
    act.verified_at = time.time()
    return act.status, after_wr


async def _verify_threshold(session, act: SpotRepairAction) -> tuple[str, Optional[float]]:
    before = {}
    try:
        before = json.loads(act.before_json or "{}")
    except json.JSONDecodeError:
        pass
    opened_after = await _opened_after(session, act.applied_at or act.detected_at)
    after_wr, after_n = await _wr_spot_after(session, act.applied_at or act.detected_at)

    loosen = act.action_type == "THRESHOLD_LOOSEN"

    if loosen:
        act.after_metric = float(opened_after)
        if opened_after >= THR_LOOSEN_IMPROVED_OPENED:
            act.status = "verified_improved"
        else:
            act.status = "verified_no_change"
        act.verified_at = time.time()
        return act.status, act.after_metric

    # TIGHTEN — measure WR after tighten
    act.after_metric = after_wr
    if after_wr is None or after_n < MIN_AFTER_N:
        age_days = (time.time() - (act.applied_at or act.detected_at)) / 86400
        if age_days > GIVEUP_DAYS:
            act.status = "verified_no_change"
            act.verified_at = time.time()
            act.note = (act.note or "") + f" | insufficient after-samples n={after_n}"
            return "no_change", after_wr
        return "pending", None

    should_revert = (after_wr < THR_TIGHTEN_REVERT_WR
                     and opened_after >= THR_TIGHTEN_MIN_OPENED)
    if should_revert and not await _has_recent_revert(session, act.target_key, COOLDOWN_REVERT_H):
        before_s = float(before.get("auto_open_score", 85.0))
        rev = await _revert_threshold(session, act, before_s, after_wr, opened_after)
        if rev is not None:
            act.status = "reverted"
            act.verified_at = time.time()
            return "reverted", after_wr

    if after_wr >= THR_TIGHTEN_IMPROVED_WR:
        act.status = "verified_improved"
    else:
        act.status = "verified_no_change"
    act.verified_at = time.time()
    return act.status, after_wr


async def _verify_backfill(session, act: SpotRepairAction) -> tuple[str, Optional[float]]:
    before = {}
    try:
        before = json.loads(act.before_json or "{}")
    except json.JSONDecodeError:
        pass
    before_pct = float(act.before_metric) if act.before_metric is not None else float(
        before.get("completeness_pct", 0.0)
    )
    after_pct = await _current_completeness_pct(session)
    act.after_metric = after_pct
    if act.before_metric is None:
        act.before_metric = before_pct
    delta = after_pct - before_pct
    if delta >= BACKFILL_IMPROVED_DELTA_PCT:
        act.status = "verified_improved"
    else:
        act.status = "verified_no_change"
    act.verified_at = time.time()
    return act.status, after_pct


# ─── One pass ──────────────────────────────────────────────────────────────
async def verify_once() -> dict[str, Any]:
    if not is_db_available():
        return {"status": "db_unavailable"}
    now = time.time()

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(SpotRepairAction).where(
                and_(
                    SpotRepairAction.status == "applied",
                    SpotRepairAction.action_type.in_([
                        "WEIGHT_BOOST", "WEIGHT_TRIM",
                        "THRESHOLD_LOOSEN", "THRESHOLD_TIGHTEN",
                        "OUTCOME_BACKFILL",
                    ]),
                    SpotRepairAction.applied_at.is_not(None),
                    SpotRepairAction.applied_at <= now - VERIFY_AFTER_H * 3600,
                    SpotRepairAction.source != "verifier",
                )
            ).order_by(SpotRepairAction.applied_at.asc()).limit(100)
        )).scalars().all())

        verified = 0
        reverted = 0
        pending = 0
        for act in rows:
            try:
                if act.action_type in ("WEIGHT_BOOST", "WEIGHT_TRIM"):
                    outcome, _ = await _verify_weight(session, act)
                elif act.action_type in ("THRESHOLD_LOOSEN", "THRESHOLD_TIGHTEN"):
                    outcome, _ = await _verify_threshold(session, act)
                elif act.action_type == "OUTCOME_BACKFILL":
                    outcome, _ = await _verify_backfill(session, act)
                else:
                    continue
                if outcome == "pending":
                    pending += 1
                    continue
                verified += 1
                if outcome == "reverted":
                    reverted += 1
            except Exception as exc:
                logger.exception("spot_verify_row_failed", id=act.id, error=str(exc)[:200])
        await session.commit()

    _status.update({
        "last_run": now,
        "verified_last_run": verified,
        "reverted_total": _status.get("reverted_total", 0) + reverted,
        "pending_last_run": pending,
    })
    if verified or pending:
        logger.info("spot_verifier_pass", verified=verified, reverted=reverted, pending=pending)
    return {"status": "ok", "verified": verified, "reverted": reverted, "pending": pending}


# ─── Loop ──────────────────────────────────────────────────────────────────
async def run_spot_verifier_loop() -> None:
    logger.info("spot_verifier_loop_starting", interval_sec=INTERVAL_SEC,
                startup_delay=STARTUP_DELAY, dry_run=DRY_RUN)
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        _status["next_run"] = time.time() + INTERVAL_SEC
        try:
            await verify_once()
            _status["last_error"] = None
        except asyncio.CancelledError:
            logger.info("spot_verifier_loop_cancelled")
            return
        except Exception as exc:
            _status["last_error"] = str(exc)[:240]
            logger.exception("spot_verifier_cycle_failed", error=_status["last_error"])
        await asyncio.sleep(INTERVAL_SEC)
