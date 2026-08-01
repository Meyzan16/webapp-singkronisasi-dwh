"""Penyalaan bertahap parameter KELUAR — satu lane dulu, dengan bukti (M5).

Masalah yang diselesaikan: sampai M4, hasil belajar sisi keluar berhenti sebagai
rekomendasi. Menyalakannya adalah satu saklar biner untuk SEMUA lane sekaligus,
tanpa baseline pembanding dan tanpa jalan pulang otomatis bila ternyata memburuk.

Modul ini memberi sisi KELUAR tahapan yang sudah lama dimiliki sisi MASUK
(`shadow → canary → champion` di `futures_adaptive_model`), tapi per
**(lane × parameter)**:

    shadow      angka tercatat, monitor mengabaikannya. Baseline diukur di sini.
    canary      berlaku untuk SATU lane saja.
    active      lolos gate; tetap diawasi.
    rolled_back gagal gate; nilai dikembalikan otomatis.

Tiga disiplin yang membuat ini bukan sekadar tombol:

1. **Baseline direkam SEBELUM angka berlaku.** Tanpa pembanding, "membaik" cuma
   klaim. Pelajaran dari angka "116 terbukti membaik" yang ternyata menyesatkan.
2. **Satu lane dalam canary pada satu waktu.** Kalau dua lane dinyalakan bersama
   dan hasilnya membaik, tak ada cara tahu lane mana penyebabnya.
3. **Hanya exit yang terjadi SESUDAH aktivasi yang dihitung.** Posisi yang sudah
   terbuka memakai parameter lama; memasukkannya akan mengencerkan hasil.

Modul ini tidak pernah menyalakan apa pun sendiri — `advance()` dipanggil oleh
loop learning, dan naik ke canary tetap butuh perintah eksplisit.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.agent_config import AgentConfig
from app.models.futures_exit_event import FuturesExitEvent
from app.models.futures_exit_rollout import FuturesExitRollout

logger = structlog.get_logger(__name__)

#: Parameter keluar yang boleh melewati tahapan ini, dipetakan ke kunci config
#: masing-masing. Fungsi, bukan dict literal, supaya kunci per-lane selalu
#: diturunkan dari sumber yang sama dengan yang dibaca monitor.
def param_config_key(param: str, lane: str) -> str:
    from agents.futures import monitor_config as mcfg
    if param == "tp_atr_mult":
        return mcfg.tp_lane_key(lane)
    if param == "failfast_min_sl_gap":
        return mcfg.failfast_gap_key(lane)
    raise ValueError(f"parameter keluar tak dikenal: {param}")


SUPPORTED_PARAMS: tuple[str, ...] = ("tp_atr_mult", "failfast_min_sl_gap")

#: Exit minimum sesudah aktivasi sebelum canary boleh diputuskan. Di bawah ini
#: hasilnya belum bisa dibedakan dari kebetulan.
CANARY_MIN_OUTCOMES = 15

#: Baseline minimum — tanpa pembanding yang layak, kenaikan apa pun tak berarti.
BASELINE_MIN_OUTCOMES = 10

#: Canary lulus bila expectancy-nya minimal sebaik baseline dikurangi toleransi
#: ini (dalam % P&L). Toleransi kecil mencegah rollback karena derau, tapi tetap
#: menolak perubahan yang benar-benar memburuk.
CANARY_TOLERANCE_PCT = 0.25


def _stats(rows: list[FuturesExitEvent]) -> tuple[int, float | None, float | None]:
    pnls = [r.pnl_pct for r in rows if r.pnl_pct is not None]
    if not pnls:
        return len(rows), None, None
    wins = sum(1 for p in pnls if p > 0)
    return (len(pnls),
            round(sum(pnls) / len(pnls), 4),
            round(100.0 * wins / len(pnls), 1))


async def _lane_exits(session, lane: str, since: float | None = None,
                      until: float | None = None, limit: int = 500) -> list:
    q = select(FuturesExitEvent).where(FuturesExitEvent.lane == lane)
    if since is not None:
        q = q.where(FuturesExitEvent.closed_at >= since)
    if until is not None:
        q = q.where(FuturesExitEvent.closed_at < until)
    q = q.order_by(FuturesExitEvent.closed_at.desc()).limit(limit)
    return list((await session.execute(q)).scalars().all())


async def _config_value(session, key: str) -> tuple[AgentConfig | None, float]:
    row = (await session.execute(select(AgentConfig).where(
        AgentConfig.agent_group == "futures", AgentConfig.key == key,
    ))).scalar_one_or_none()
    return row, (row.value_num if row else 0.0)


# ── Tahap 1: catat usulan sebagai shadow ──────────────────────────────────────

async def propose(lane: str, param: str, value: float, reason: str = "") -> dict:
    """Catat usulan sebagai `shadow` beserta baseline lane saat ini.

    Baseline diambil SEKARANG — sebelum angka berlaku — karena itulah satu-satunya
    saat pembanding masih bersih.
    """
    if param not in SUPPORTED_PARAMS:
        return {"status": "param_tak_dikenal", "param": param,
                "supported": list(SUPPORTED_PARAMS)}
    if not is_db_available():
        return {"status": "db_unavailable"}

    key = param_config_key(param, lane)
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.lane == lane, FuturesExitRollout.param == param,
            FuturesExitRollout.stage.in_(["shadow", "canary", "active"]),
        ))).scalars().first()
        if existing:
            return {"status": "sudah_ada", "stage": existing.stage,
                    "id": existing.id, "proposed_value": existing.proposed_value}

        _, current = await _config_value(session, key)
        n, exp, wr = _stats(await _lane_exits(session, lane))
        row = FuturesExitRollout(
            lane=lane, param=param, stage="shadow",
            proposed_value=value, previous_value=current,
            baseline_n=n, baseline_expectancy=exp, baseline_win_rate=wr,
            reason=reason or "usulan dari ledger keluar",
        )
        session.add(row)
        await session.commit()
        rid = row.id

    logger.info("exit_rollout_proposed", lane=lane, param=param, value=value, id=rid)
    return {"status": "ok", "id": rid, "stage": "shadow", "lane": lane,
            "param": param, "proposed_value": value, "previous_value": current,
            "baseline": {"n": n, "expectancy_pct": exp, "win_rate": wr}}


# ── Tahap 2: naikkan ke canary (menulis nilai ke config) ──────────────────────

async def start_canary(rollout_id: int) -> dict:
    """Berlakukan usulan untuk SATU lane. Ditolak bila baseline belum cukup, atau
    bila sudah ada lane lain yang sedang canary — dua perubahan bersamaan membuat
    hasilnya mustahil ditafsirkan."""
    if not is_db_available():
        return {"status": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.id == rollout_id))).scalar_one_or_none()
        if row is None:
            return {"status": "tak_ditemukan"}
        if row.stage != "shadow":
            return {"status": "bukan_shadow", "stage": row.stage}
        if row.baseline_n < BASELINE_MIN_OUTCOMES:
            return {"status": "baseline_kurang", "baseline_n": row.baseline_n,
                    "required": BASELINE_MIN_OUTCOMES,
                    "reason": "tanpa pembanding yang layak, perbaikan apa pun tak bisa dibuktikan"}

        busy = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.stage == "canary"))).scalars().first()
        if busy is not None:
            return {"status": "canary_lain_berjalan", "lane": busy.lane,
                    "param": busy.param, "id": busy.id,
                    "reason": "satu lane pada satu waktu — kalau dua dinyalakan "
                              "bersama, tak ada cara tahu mana penyebabnya"}

        key = param_config_key(row.param, row.lane)
        cfg_row, current = await _config_value(session, key)
        if cfg_row is None:
            return {"status": "baris_config_hilang", "key": key}
        row.previous_value = current
        cfg_row.value_num = row.proposed_value
        cfg_row.updated_at = time.time()
        cfg_row.updated_by = "exit_rollout"
        row.stage = "canary"
        row.activated_at = time.time()
        row.reason = (f"canary: {key} {current} -> {row.proposed_value}; "
                      f"baseline n={row.baseline_n} "
                      f"expectancy={row.baseline_expectancy}")
        await session.commit()
        out = {"status": "ok", "stage": "canary", "id": row.id, "lane": row.lane,
               "param": row.param, "key": key, "from": current,
               "to": row.proposed_value,
               "note": ("nilai sudah tertulis, TAPI monitor baru memakainya bila "
                        "futures.monitor_exit_learning_enabled menyala")}

    logger.info("exit_rollout_canary_started", **{k: out[k] for k in ("lane", "param", "to")})
    return out


# ── Tahap 3: evaluasi & putuskan ──────────────────────────────────────────────

async def evaluate(rollout_id: int) -> dict:
    """Bandingkan hasil SESUDAH aktivasi dengan baseline, lalu putuskan.

    Hanya exit yang tertutup sesudah `activated_at` yang dihitung — posisi yang
    sudah terbuka masih memakai parameter lama.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.id == rollout_id))).scalar_one_or_none()
        if row is None:
            return {"status": "tak_ditemukan"}
        if row.stage != "canary":
            return {"status": "bukan_canary", "stage": row.stage}

        after = await _lane_exits(session, row.lane, since=row.activated_at or 0.0)
        n, exp, wr = _stats(after)
        row.observed_n, row.observed_expectancy, row.observed_win_rate = n, exp, wr

        if n < CANARY_MIN_OUTCOMES:
            await session.commit()
            return {"status": "mengumpulkan", "n": n, "required": CANARY_MIN_OUTCOMES,
                    "lane": row.lane, "param": row.param}

        base = row.baseline_expectancy if row.baseline_expectancy is not None else 0.0
        lulus = exp is not None and exp >= base - CANARY_TOLERANCE_PCT
        row.decided_at = time.time()

        if lulus:
            row.stage = "active"
            row.reason = (f"lulus: expectancy {exp} vs baseline {base} "
                          f"(toleransi {CANARY_TOLERANCE_PCT}), n={n}")
        else:
            key = param_config_key(row.param, row.lane)
            cfg_row, _ = await _config_value(session, key)
            if cfg_row is not None:
                cfg_row.value_num = row.previous_value
                cfg_row.updated_at = time.time()
                cfg_row.updated_by = "exit_rollout_rollback"
            row.stage = "rolled_back"
            row.reason = (f"dibalik: expectancy {exp} di bawah baseline {base} "
                          f"(toleransi {CANARY_TOLERANCE_PCT}), n={n}; "
                          f"{key} dikembalikan ke {row.previous_value}")

        await session.commit()
        out = {"status": "ok", "stage": row.stage, "id": row.id, "lane": row.lane,
               "param": row.param, "reason": row.reason,
               "baseline": {"n": row.baseline_n, "expectancy_pct": base,
                            "win_rate": row.baseline_win_rate},
               "observed": {"n": n, "expectancy_pct": exp, "win_rate": wr}}

    logger.info("exit_rollout_decided", lane=out["lane"], param=out["param"],
                stage=out["stage"])
    return out


async def rollback(rollout_id: int, reason: str = "dibalik manual") -> dict:
    """Kembalikan parameter ke nilai sebelumnya, apa pun tahapannya.

    Tersedia untuk `active` juga — parameter yang sudah lulus gate tetap boleh
    dibatalkan tanpa harus menunggu evaluasi berikutnya.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.id == rollout_id))).scalar_one_or_none()
        if row is None:
            return {"status": "tak_ditemukan"}
        if row.stage not in ("canary", "active"):
            return {"status": "tak_bisa_dibalik", "stage": row.stage}

        key = param_config_key(row.param, row.lane)
        cfg_row, _ = await _config_value(session, key)
        if cfg_row is not None:
            cfg_row.value_num = row.previous_value
            cfg_row.updated_at = time.time()
            cfg_row.updated_by = "exit_rollout_rollback"
        row.stage = "rolled_back"
        row.decided_at = time.time()
        row.reason = f"{reason}; {key} dikembalikan ke {row.previous_value}"
        await session.commit()
        out = {"status": "ok", "stage": "rolled_back", "id": row.id,
               "lane": row.lane, "param": row.param, "key": key,
               "restored_to": row.previous_value}
    logger.info("exit_rollout_rolled_back", lane=out["lane"], param=out["param"])
    return out


async def propose_from_recommendations(days: int = 90) -> dict:
    """Alirkan usulan mesin belajar ke antrean tahapan ini.

    Inilah sambungan antara `exit_learning` (yang menghitung angka) dan tahapan
    penyalaan (yang menguji angka itu di dunia nyata). Tanpa sambungan ini, dua
    lapisan itu hidup terpisah dan hasil belajar berhenti sebagai laporan.

    Tidak ada yang berlaku di sini — semua masuk sebagai `shadow`.
    """
    from agents.learning.exit_learning import (
        recommend_exit_params, recommend_failfast_params,
    )

    hasil, dilewati = [], []

    tp = await recommend_exit_params(days=days)
    for rec in tp.get("recommendations", []):
        if rec.get("status") != "ok" or not rec.get("suggested_tp_atr"):
            dilewati.append({"lane": rec.get("lane"), "param": "tp_atr_mult",
                             "reason": rec.get("status", "usulan_kosong")})
            continue
        if rec.get("premature_frac", 0.0) >= 0.5:
            dilewati.append({"lane": rec["lane"], "param": "tp_atr_mult",
                             "reason": "mayoritas_exit_prematur"})
            continue
        hasil.append(await propose(
            rec["lane"], "tp_atr_mult", rec["suggested_tp_atr"],
            reason=f"TP realistis dari {rec['n']} exit; "
                   f"akan tersentuh ~{rec.get('would_be_reached_pct')}%"))

    ff = await recommend_failfast_params(days=days)
    for rec in ff.get("recommendations", []):
        if rec.get("status") != "ok":
            dilewati.append({"lane": rec.get("lane"), "param": "failfast_min_sl_gap",
                             "reason": rec.get("status")})
            continue
        hasil.append(await propose(
            rec["lane"], "failfast_min_sl_gap", rec["suggested_gap"],
            reason=rec.get("note", "")))

    return {"status": "ok", "diusulkan": hasil, "dilewati": dilewati}


# ── Loop: maju sendiri sejauh yang aman ───────────────────────────────────────

async def advance() -> dict:
    """Evaluasi semua canary yang berjalan. Dipanggil loop learning.

    Sengaja TIDAK menaikkan shadow→canary sendiri: memberlakukan parameter baru
    ke uang sungguhan tetap butuh perintah eksplisit.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        ids = [r.id for r in (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.stage == "canary"))).scalars().all()]
    return {"status": "ok", "evaluated": [await evaluate(i) for i in ids]}


async def status() -> dict:
    """Semua tahapan penyalaan beserta posisinya — untuk endpoint/UI."""
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(select(FuturesExitRollout).order_by(
            FuturesExitRollout.created_at.desc()).limit(100))).scalars().all())
        _, learning_on = await _config_value(session, "monitor_exit_learning_enabled")

    return {
        "status": "ok",
        "learning_enabled": learning_on > 0,
        "note": ("Selama monitor_exit_learning_enabled masih 0, angka per-lane "
                 "tersimpan dan tercatat tapi TIDAK dipakai satu pun keputusan."),
        "gates": {"canary_min_outcomes": CANARY_MIN_OUTCOMES,
                  "baseline_min_outcomes": BASELINE_MIN_OUTCOMES,
                  "canary_tolerance_pct": CANARY_TOLERANCE_PCT},
        "rollouts": [{
            "id": r.id, "lane": r.lane, "param": r.param, "stage": r.stage,
            "proposed_value": r.proposed_value, "previous_value": r.previous_value,
            "baseline": {"n": r.baseline_n, "expectancy_pct": r.baseline_expectancy,
                         "win_rate": r.baseline_win_rate},
            "observed": {"n": r.observed_n, "expectancy_pct": r.observed_expectancy,
                         "win_rate": r.observed_win_rate},
            "created_at": r.created_at, "activated_at": r.activated_at,
            "decided_at": r.decided_at, "reason": r.reason,
        } for r in rows],
    }
