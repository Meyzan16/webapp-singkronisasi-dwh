"""Verifier progress perbaikan — before/after + auto-revert (R3).

Jantung "progress sinyal perbaikan": tiap aksi bobot yang berumur ≥24 jam diukur
ulang (hit-rate SESUDAH aksi, era predictive yang sama) lalu diberi vonis:
  weight_down: hit_after < 30%  → verified_improved   (keputusan benar — sinyal memang buruk)
               hit_after ≥ 45%  → REVERT (+step balik) (sinyal ternyata pulih; aksi salah)
               di antaranya     → verified_no_change
  weight_up:   hit_after ≥ 55%  → verified_improved
               hit_after < 40%  → REVERT (−step balik)
               di antaranya     → verified_no_change
Sampel sesudah < MIN_AFTER_N → tunggu (retry pass berikutnya); > 7 hari tetap
kurang → verified_no_change (insufficient). Revert kena cooldown 48 jam dan
tercatat sebagai baris baru source=verifier (revert_of=id asal).
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_repair_action import FuturesRepairAction
from agents.learning.predictive_repair import _apply_weight_step, collect_predictive_stats
from agents.futures.repair_log import COOLDOWN_REVERT_H, has_recent_action, record_action

logger = structlog.get_logger(__name__)

VERIFY_AFTER_H   = 24.0
MIN_AFTER_N      = 8
GIVEUP_DAYS      = 7.0
DOWN_IMPROVED_LT = 0.30   # weight_down terbukti benar bila sinyal tetap buruk
DOWN_REVERT_GE   = 0.45   # sinyal pulih → kembalikan bobot
UP_IMPROVED_GE   = 0.55
UP_REVERT_LT     = 0.40

_status: dict = {"last_run": None, "verified_last_run": 0, "reverted_total": 0}


def get_verifier_status() -> dict:
    return dict(_status)


async def verify_repairs() -> dict:
    global _status
    if not is_db_available():
        return {"status": "db_unavailable"}
    now = time.time()

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(FuturesRepairAction).where(
                FuturesRepairAction.status == "applied",
                FuturesRepairAction.action.in_(["weight_down", "weight_up"]),
                FuturesRepairAction.applied_at <= now - VERIFY_AFTER_H * 3600,
            ).order_by(FuturesRepairAction.applied_at.asc()).limit(100)
        )).scalars().all())
    if not rows:
        _status = {**_status, "last_run": now, "verified_last_run": 0}
        return {"status": "ok", "verified": 0}

    verified = 0
    reverted = 0
    for r in rows:
        if ":" not in r.target_key:
            continue
        agent, key = r.target_key.split(":", 1)
        # metrik SESUDAH: hanya sampel yang di-scan setelah aksi diterapkan
        stats = await collect_predictive_stats(r.applied_at or r.detected_at,
                                               agent_filter=agent)
        d = stats.get((agent, key), {"n": 0, "hits": 0})
        if d["n"] < MIN_AFTER_N:
            if (now - (r.applied_at or r.detected_at)) > GIVEUP_DAYS * 86400:
                async with AsyncSessionLocal() as session:
                    row = await session.get(FuturesRepairAction, r.id)
                    if row:
                        row.status = "verified_no_change"
                        row.verified_at = now
                        row.note = f"insufficient after-samples (n={d['n']})"
                        await session.commit()
                verified += 1
            continue   # belum cukup sampel — coba lagi pass berikutnya

        hit_after = d["hits"] / d["n"]
        if r.action == "weight_down":
            should_revert = hit_after >= DOWN_REVERT_GE
            improved = hit_after < DOWN_IMPROVED_LT
            revert_step = +abs(r.delta or 0.10)
        else:
            should_revert = hit_after < UP_REVERT_LT
            improved = hit_after >= UP_IMPROVED_GE
            revert_step = -abs(r.delta or 0.10)

        new_status = ("reverted" if should_revert
                      else "verified_improved" if improved
                      else "verified_no_change")

        if should_revert:
            # anti flip-flop: revert kena cooldown 48 jam per target
            if await has_recent_action(r.target_key, hours=COOLDOWN_REVERT_H):
                continue   # tunggu — jangan bolak-balik
            applied = await _apply_weight_step(agent, key, revert_step, now)
            if applied is not None:
                old_w, new_w = applied
                await record_action(
                    source="verifier",
                    target_key=r.target_key,
                    agent=agent,
                    issue="reverted_by_verifier",
                    action="weight_up" if revert_step > 0 else "weight_down",
                    evidence={"n_after": d["n"], "hit_after": round(hit_after, 4),
                              "before_weight": old_w, "after_weight": new_w},
                    delta=revert_step,
                    before_metric=round(hit_after, 4),
                    revert_of=r.id,
                    note=f"revert aksi #{r.id} — hit sesudah {hit_after:.0%}",
                )
                reverted += 1
                logger.warning("repair_reverted", target=r.target_key,
                               original=r.id, hit_after=round(hit_after, 3))

        async with AsyncSessionLocal() as session:
            row = await session.get(FuturesRepairAction, r.id)
            if row:
                row.after_metric = round(hit_after, 4)
                row.status = new_status
                row.verified_at = now
                await session.commit()
        verified += 1

    _status = {"last_run": now, "verified_last_run": verified,
               "reverted_total": _status.get("reverted_total", 0) + reverted}
    if verified:
        logger.info("repair_verifier_pass", verified=verified, reverted=reverted)
    return {"status": "ok", "verified": verified, "reverted": reverted}
