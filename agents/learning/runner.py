"""Loop pembelajaran berat — dijalankan di PROSES TERPISAH.

Isinya persis langkah-langkah yang dulu dipanggil inline di dalam loop scanner
(`agents/opportunity/scheduler.py` dan `agents/futures/scheduler.py`), tanpa
perubahan urutan maupun parameter — hanya pindah tempat. Alasannya di
[agents/learning/mode.py].

Cadence: dulu latihan dipicu tepat setelah ada outcome baru matang. Di sini ia
dipicu berkala, dan itu AMAN karena kedua `train_and_register()` punya rem
sendiri (`no_new_evidence`: butuh minimal +50 sampel baru dibanding versi
terakhir sebelum mendaftarkan model baru). Jadi jalan lebih sering tak
menghasilkan model ekstra — hanya pekerjaan sia-sia yang, di proses ini,
tidak mengganggu siapa pun.
"""

import asyncio
import os
import time

import structlog

logger = structlog.get_logger(__name__)

# Sekali per 10 menit: cukup rapat untuk tak tertinggal outcome baru, cukup
# jarang untuk tak membakar CPU terus-menerus (satu putaran = 2-4 menit).
INTERVAL_SEC = int(os.getenv("LEARNING_INTERVAL_SEC", "600"))

_state: dict = {
    "running": False,
    "cycles": 0,
    "last_run_at": 0.0,
    "last_duration_sec": 0.0,
    "last_spot": None,
    "last_futures": None,
    "last_error": None,
}


def get_state() -> dict:
    """Status loop — dipakai health server proses ini."""
    return dict(_state)


async def _run_spot() -> dict:
    from agents.learning.spot_adaptive_model import train_and_register, monitor_champion_drift

    out: dict = {}
    training = await train_and_register()
    out["training"] = training.get("status")
    if training.get("status") == "registered":
        logger.info("spot_challenger_registered", version=training.get("version"))
    drift = await monitor_champion_drift()
    out["drift"] = drift.get("status")
    if drift.get("status") == "rolled_back":
        logger.warning("spot_model_auto_rollback", **drift)
    return out


async def _run_futures() -> dict:
    from agents.learning.futures_adaptive_model import (
        train_and_register, advance_lifecycle, monitor_champion_drift,
    )

    out: dict = {}
    training = await train_and_register()
    out["training"] = training.get("status")
    if training.get("status") == "registered":
        logger.info("futures_challenger_registered", version=training.get("version"))
    # Walk-forward + cost-stress 1.5x (F4). Ikut pindah ke sini karena di
    # scheduler ia satu blok dengan latihan — kalau ditinggal, ia berhenti jalan.
    from agents.learning.futures_walkforward import run_futures_walkforward
    wf = await run_futures_walkforward()
    out["walkforward"] = wf.get("status")
    if wf.get("status") == "ok":
        logger.info("futures_walkforward",
                    best_threshold=wf.get("best_threshold"),
                    promotion_eligible=wf.get("promotion_eligible"))
    lifecycle = await advance_lifecycle()
    out["lifecycle"] = lifecycle.get("status")
    drift = await monitor_champion_drift()
    out["drift"] = drift.get("status")
    if drift.get("status") == "rolled_back":
        logger.warning("futures_model_auto_rollback", **drift)
    return out


async def _run_jobs_berat() -> dict:
    """Jalankan pekerjaan belajar berkala yang berat — di SINI, bukan di backend.

    Jadwal dan catatan waktu jalannya tetap satu-satunya sumber di
    `agents.futures.jobs`; yang pindah hanyalah proses yang mengeksekusinya.
    Memisahkan jadwalnya juga akan berarti dua kebenaran tentang "kapan terakhir
    jalan", dan kebenaran kedua itu pasti akan menyimpang diam-diam.

    Satu pekerjaan per siklus. Pada jalan pertama `_last_run` masih kosong,
    jadi ketiganya terhitung terlambat sekaligus — menjalankan semuanya
    berbarengan persis yang membekukan backend 8 Sep 2026. Yang belum kebagian
    tidak hilang: ia tetap terlambat dan diambil siklus berikutnya.
    """
    from agents.futures import jobs as _jobs

    hasil = await _jobs.run_due(lingkup="berat", maks=1)
    if hasil["dijalankan"]:
        logger.info("learning_jobs_ran", jobs=hasil["dijalankan"])
    if hasil["gagal"]:
        logger.warning("learning_jobs_failed", jobs=hasil["gagal"])
    return hasil


async def run_learning_loop() -> None:
    """Loop utama proses pembelajaran."""
    from app.database import is_db_available

    _state["running"] = True
    logger.info("learning_runner_started", interval_sec=INTERVAL_SEC)
    try:
        while True:
            if not is_db_available():
                # Jangan hitung ini sebagai siklus — DB belum siap, watchdog
                # di __main__ yang akan menaikkan flag begitu Postgres kembali.
                await asyncio.sleep(20)
                continue

            started = time.time()
            try:
                # SPOT dan FUTURES berurutan, bukan gather: keduanya CPU-berat,
                # menjalankannya bersamaan hanya membuat keduanya lebih lambat
                # dan melipatgandakan puncak memori atas ledger ratusan ribu baris.
                _state["last_spot"] = await _run_spot()
                _state["last_futures"] = await _run_futures()
                _state["last_jobs"] = await _run_jobs_berat()
                _state["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:      # noqa: BLE001 — satu siklus gagal tak boleh mematikan loop
                _state["last_error"] = str(exc)[:200]
                logger.warning("learning_cycle_error", error=str(exc)[:200])

            _state["cycles"] += 1
            _state["last_run_at"] = time.time()
            _state["last_duration_sec"] = round(time.time() - started, 1)
            logger.info("learning_cycle_done",
                        cycles=_state["cycles"],
                        duration_sec=_state["last_duration_sec"],
                        spot=_state["last_spot"], futures=_state["last_futures"])
            await asyncio.sleep(INTERVAL_SEC)
    except asyncio.CancelledError:
        _state["running"] = False
        logger.info("learning_runner_stopped")
        raise
