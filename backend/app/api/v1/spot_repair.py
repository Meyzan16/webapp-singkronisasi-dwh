"""SPOT Adaptive Repair API — status agent + ledger aksi + kontrol manual.

Endpoint di sini TIDAK menyentuh `signals.py` (area Claude Code untuk
plan Signal Repair Live futures+predictive).

- GET  /api/v1/spot-repair/status          — enabled, running, last_run, dst.
- GET  /api/v1/spot-repair/actions/recent  — 72 jam terakhir + filter
- GET  /api/v1/spot-repair/repairs         — bentuk identik /signals/repairs (funnel+log)
- GET  /api/v1/spot-repair/recommendations — saran auto-applicable + tombol apply
- POST /api/v1/spot-repair/toggle          — enable/disable per action_type
- POST /api/v1/spot-repair/execute         — trigger 1 siklus aksi manual
- POST /api/v1/spot-repair/apply           — apply satu saran bobot bounded
- POST /api/v1/spot-repair/rollback/{id}   — rollback aksi tertentu
"""

import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, require_db
from app.models.spot_repair_action import SpotRepairAction
from agents.learning import spot_repair_agent as agent
from agents.learning import spot_repair_verifier as verifier

router = APIRouter(tags=["spot-repair"])


class ToggleRequest(BaseModel):
    action_type: str = Field(..., description="Tipe aksi (mis. THRESHOLD_LOOSEN)")
    enabled: bool


class ExecuteRequest(BaseModel):
    action_type: str = Field(..., description="Tipe aksi yang akan dipicu manual")


class ApplySuggestionBody(BaseModel):
    type: str = Field(..., description="'weight' — hanya weight yang auto-applicable")
    signal_key: str = Field(..., max_length=100)
    regime: str = Field(default="all", max_length=30)
    delta: float = Field(..., description="±0.05 saja (dipotong ke bound)")
    label: str = Field(default="", max_length=160)


@router.get("/spot-repair/status")
async def spot_repair_status() -> dict:
    """Status lengkap SPOT Adaptive Repair Agent (+ ringkas verifier)."""
    st = agent.get_state()
    st["verifier"] = verifier.get_status()
    return st


@router.get("/spot-repair/actions/recent", dependencies=[Depends(require_db)])
async def spot_repair_actions_recent(
    hours: int = Query(72, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
    action_type: str | None = Query(None),
    status: str | None = Query(None),
) -> dict:
    """Daftar aksi terbaru terurut waktu (terbaru di atas)."""
    rows = await agent.list_recent_actions(
        hours=hours,
        limit=limit,
        action_type=action_type,
        status=status,
    )
    return {
        "count": len(rows),
        "hours": hours,
        "filters": {"action_type": action_type, "status": status},
        "actions": rows,
    }


@router.get("/spot-repair/repairs", dependencies=[Depends(require_db)])
async def spot_repair_repairs(limit: int = Query(100, ge=1, le=300)) -> dict:
    """Progress perbaikan sinyal SPOT — bentuk **identik** `/signals/repairs`
    (futures) supaya satu komponen UI bisa render dua scope.
    Funnel deteksi → aksi → verifikasi + agent state + verifier state + log aksi
    dengan before/after metric per baris.
    """
    now = time.time()
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(SpotRepairAction)
            .order_by(SpotRepairAction.detected_at.desc())
            .limit(limit)
        )).scalars().all())

        status_counts = dict((await session.execute(
            select(SpotRepairAction.status, func.count(SpotRepairAction.id))
            .group_by(SpotRepairAction.status)
        )).all())

        actions_24h = int(await session.scalar(
            select(func.count(SpotRepairAction.id)).where(
                SpotRepairAction.applied_at.is_not(None),
                SpotRepairAction.applied_at >= now - 86400,
            )
        ) or 0)
        total = int(await session.scalar(
            select(func.count(SpotRepairAction.id))
        ) or 0)

    # "reversed" (TTL / manual rollback) DITAMPILKAN sebagai "reverted" di funnel
    # supaya sejalan dengan vocab futures.
    verified_total = (
        status_counts.get("verified_improved", 0)
        + status_counts.get("verified_no_change", 0)
        + status_counts.get("reverted", 0)
        + status_counts.get("reversed", 0)
    )
    reverted_total = status_counts.get("reverted", 0) + status_counts.get("reversed", 0)

    agent_state = agent.get_state()
    # Loop repair SPOT dijaga env `SPOT_REPAIR_ENABLED` (default OFF, lihat
    # main.py). Tanpa menyebutkannya, UI menampilkan "menunggu run pertama" —
    # padahal agen TIDAK menunggu, ia memang tak pernah dijalankan, dan seluruh
    # angka di bawah adalah riwayat beku (aksi terakhir 29 Jul). Kirim status
    # sebenarnya supaya tak terbaca seolah masih hidup.
    _enabled = os.getenv("SPOT_REPAIR_ENABLED", "false").lower() == "true"
    agent_status = {
        "enabled": _enabled,
        # Kalimat untuk MANUSIA — nama variabel/env tak pernah ditampilkan ke
        # pengguna; kalau perlu diubah, itu urusan operator lewat konfigurasi.
        "disabled_reason": None if _enabled else "mesin perbaikan SPOT dimatikan",
        "last_run": agent_state.get("last_run"),
        "checked": agent_state.get("action_count_24h", 0),
        "actions_last_run": None,
        "actions_total": total,
    }
    verifier_status = verifier.get_status()

    def _issue_of(row: SpotRepairAction) -> str:
        return {
            "OUTCOME_BACKFILL":  "completeness_low",
            "THRESHOLD_LOOSEN":  "opened_low",
            "THRESHOLD_TIGHTEN": "wr_low",
            "WEIGHT_BOOST":      "wr_high",
            "WEIGHT_TRIM":       "wr_low",
            "SYMBOL_COOLDOWN":   "symbol_bleed",
            "PROMOTION_RETRY":   "promotion_stuck",
        }.get(row.action_type, "unknown")

    def _action_verb(row: SpotRepairAction) -> str:
        return {
            "OUTCOME_BACKFILL":  "backfill",
            "THRESHOLD_LOOSEN":  "threshold_down",
            "THRESHOLD_TIGHTEN": "threshold_up",
            "WEIGHT_BOOST":      "weight_up",
            "WEIGHT_TRIM":       "weight_down",
        }.get(row.action_type, row.action_type.lower())

    def _pack(r: SpotRepairAction) -> dict:
        try:
            before = json.loads(r.before_json or "{}")
        except (TypeError, json.JSONDecodeError):
            before = {}
        try:
            after = json.loads(r.after_json or "{}")
        except (TypeError, json.JSONDecodeError):
            after = {}
        # kompatibel field-for-field dengan /signals/repairs (futures)
        delta = None
        if "weight" in before and "weight" in after:
            try:
                delta = round(float(after["weight"]) - float(before["weight"]), 4)
            except Exception:
                pass
        elif "auto_open_score" in before and "auto_open_score" in after:
            try:
                delta = round(
                    float(after["auto_open_score"]) - float(before["auto_open_score"]), 4)
            except Exception:
                pass
        # UI-facing status: normalisasi "reversed" → "reverted"
        vstat = r.status if r.status != "reversed" else "reverted"
        return {
            "id": r.id,
            "detected_at": r.detected_at,
            "source": r.source,
            "target_key": r.target_key,
            "agent": "opportunity_spot",
            "issue": _issue_of(r),
            "action": _action_verb(r),
            "delta": delta,
            "applied": r.status in ("applied", "verified_improved",
                                     "verified_no_change", "reverted", "reversed"),
            "applied_at": r.applied_at,
            "evidence": {"before": before, "after": after,
                         "affected_count": r.affected_count,
                         "reason": r.reason},
            "before_metric": r.before_metric,
            "after_metric": r.after_metric,
            "status": vstat,
            "verified_at": r.verified_at,
            "revert_of": r.revert_of,
            "note": r.note,
        }

    return {
        "funnel": {
            "total": total,
            "applied": status_counts.get("applied", 0),
            "verified": verified_total,
            "improved": status_counts.get("verified_improved", 0),
            # Bentuk field disamakan dgn futures supaya satu komponen UI bisa
            # merender dua scope. SPOT TIDAK punya era "tak terukur": kuncinya
            # sudah canonical sejak awal (weight_updater memakai
            # canonical_signal_key, sama dgn learning_keys) dan zombie-prune-nya
            # hanya MENGHAPUS kunci basi >30 hari — tak pernah menyeret bobot
            # repair kembali ke 1.0 seperti bug futures. Jadi seluruh vonis SPOT
            # memang terukur.
            "improved_measured": status_counts.get("verified_improved", 0),
            "improved_legacy": 0,
            "effect_epoch": None,
            "no_change": status_counts.get("verified_no_change", 0),
            "reverted": reverted_total,
            "suggested": status_counts.get("suggested", 0),
            "actions_24h": actions_24h,
        },
        "agent": agent_status,
        "verifier": verifier_status,
        "actions": [_pack(r) for r in rows],
        "updated_at": now,
        "scope": "spot",
    }


@router.get("/spot-repair/recommendations", dependencies=[Depends(require_db)])
async def spot_repair_recommendations() -> dict:
    """Saran auto-applicable untuk SPOT (WEIGHT_BOOST/TRIM yang lolos guardrail).
    Setiap saran menyertakan payload `apply` yang bisa diposting langsung ke
    `/spot-repair/apply` untuk menerapkannya."""
    recs = await agent.get_pending_recommendations()
    return {
        "scope": "spot",
        "count": len(recs),
        "recommendations": recs,
        "updated_at": time.time(),
    }


@router.post("/spot-repair/toggle")
async def spot_repair_toggle(body: ToggleRequest) -> dict:
    """Enable/disable eksekusi live untuk 1 tipe aksi (in-memory, per proses)."""
    ok = agent.set_action_enabled(body.action_type, body.enabled)
    if not ok:
        return {
            "ok": False,
            "error": f"action_type tidak dikenal: {body.action_type}",
            "known": list(agent._action_enabled.keys()),  # noqa: SLF001
        }
    return {"ok": True, "action_type": body.action_type, "enabled": body.enabled}


@router.post("/spot-repair/execute", dependencies=[Depends(require_db)])
async def spot_repair_execute(body: ExecuteRequest) -> dict:
    """Trigger 1 siklus aksi tertentu manual (semua guardrail tetap aktif)."""
    return await agent.execute_manual(body.action_type)


@router.post("/spot-repair/apply", dependencies=[Depends(require_db)])
async def spot_repair_apply(body: ApplySuggestionBody) -> dict:
    """Terapkan 1 saran bobot bounded untuk SPOT (mirror /signals/recommendations/apply)."""
    if body.type != "weight":
        raise HTTPException(status_code=400, detail="Hanya type 'weight' yang auto-applicable")
    result = await agent.apply_weight_step(
        signal_key=body.signal_key,
        regime=body.regime,
        delta=body.delta,
        label=body.label,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "apply gagal"))
    return result


@router.post("/spot-repair/rollback/{action_id}", dependencies=[Depends(require_db)])
async def spot_repair_rollback(action_id: int) -> dict:
    """Rollback aksi tertentu bila reversible + belum di-reverse."""
    return await agent.rollback_action(action_id)


@router.post("/spot-repair/verify", dependencies=[Depends(require_db)])
async def spot_repair_verify_now() -> dict:
    """Trigger satu pass verifier segera (dev/manual)."""
    return await verifier.verify_once()
