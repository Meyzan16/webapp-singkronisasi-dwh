"""Proses pembelajaran mandiri.

Jalankan:
    cd backend && ../.venv/Scripts/python.exe -m agents.learning
    (atau: python -m agents.learning dengan repo root di PYTHONPATH)

Dan set LEARNING_STANDALONE=true di proses backend supaya langkah berat tidak
jalan dua kali. Lihat [agents/learning/mode.py] untuk alasannya.
"""

import asyncio
import os
import sys

# TLS lewat trust store Windows — WAJIB sebelum modul apa pun membuat client
# httpx/websocket, kalau tidak antivirus yang menyadap HTTPS (mis. Bitdefender)
# membuat semua panggilan gagal CERTIFICATE_VERIFY_FAILED. Pola sama dgn
# backend/app/main.py dan agents/main.py.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 — best-effort, fallback ke certifi
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "backend"))

import structlog  # noqa: E402

from app.logging_config import configure_logging  # noqa: E402

configure_logging("learning")

logger = structlog.get_logger(__name__)

_HEALTH_PORT = int(os.getenv("LEARNING_HEALTH_PORT", "8002"))


async def _db_watchdog() -> None:
    """Jaga flag `_db_available` proses INI mengikuti kenyataan.

    Wajib ada. Flag itu variabel modul PER PROSES dan lahir False; tanpa
    watchdog di sini `is_db_available()` tak pernah menjadi True dan seluruh
    pembelajaran mati diam-diam tanpa satu pun pesan error — persis jebakan yang
    pernah memakan 3,5 jam pada 30 Jul 2026 di proses backend.
    """
    from app.database import is_db_available, probe_db, set_db_available

    while True:
        try:
            alive = await probe_db()
            if alive and not is_db_available():
                set_db_available(True)
                logger.info("db_available", msg="PostgreSQL siap — pembelajaran aktif")
            elif not alive and is_db_available():
                set_db_available(False)
                logger.warning("db_lost", msg="PostgreSQL tak menjawab — pembelajaran ditahan")
        except asyncio.CancelledError:
            raise
        except Exception as exc:      # noqa: BLE001
            logger.warning("db_watchdog_error", error=str(exc)[:120])
        await asyncio.sleep(20)


async def _run_health_server() -> None:
    """Health kecil supaya status proses ini bisa dilihat dari luar."""
    from fastapi import FastAPI
    import uvicorn

    health_app = FastAPI(title="learning-health")

    @health_app.get("/health")
    def learning_health() -> dict:
        from app.database import is_db_available
        from agents.learning.runner import get_state
        return {"db": "ok" if is_db_available() else "unavailable", "learning": get_state()}

    server = uvicorn.Server(uvicorn.Config(
        health_app, host="0.0.0.0", port=_HEALTH_PORT,
        log_level="warning", access_log=False,
    ))
    await server.serve()


async def main() -> None:
    from agents.learning.runner import run_learning_loop

    logger.info("learning_process_starting", health_port=_HEALTH_PORT)
    # Watchdog dulu: loop pembelajaran menunggu flag DB naik sebelum bekerja.
    await asyncio.gather(
        _db_watchdog(),
        run_learning_loop(),
        _run_health_server(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("learning_process_stopped")
