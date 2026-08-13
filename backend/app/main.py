import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

# When agents run in a separate container, set AGENTS_STANDALONE=true to skip
# starting them here. Health endpoint still imports agent state for monitoring.
_AGENTS_STANDALONE = os.getenv("AGENTS_STANDALONE", "false").lower() == "true"
_AGENTS_HEALTH_URL = os.getenv("AGENTS_HEALTH_URL", "http://agents:8001")

# Make agents/ importable whether backend is run from:
#   cd backend && uvicorn app.main:app        ← adds repo root to sys.path
#   cd agents-trading && python backend/...   ← repo root already in path
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# ── TLS trust: pakai Windows certificate store, bukan hanya bundle `certifi` ──────
# Antivirus dgn "Encrypted Web Scan" (mis. Bitdefender) menyadap HTTPS dan
# menyodorkan sertifikat MITM yang ditandatangani CA lokalnya. CA itu ada di
# Windows store (schannel/PowerShell percaya), TAPI TIDAK ada di certifi → httpx &
# websockets Python gagal "CERTIFICATE_VERIFY_FAILED: unable to get local issuer
# certificate", walau hanya intermiten. Cukup 1 koneksi tersadap per cycle sudah
# bikin _run_scan raise → cycle_count mentok 0 (scanner spot & futures tak jalan).
# truststore.inject_into_ssl() mengalihkan ssl.create_default_context ke Windows
# store → httpx/websockets otomatis mempercayai CA AV. Harus jalan SEBELUM modul
# lain membuat client. Defensif: kalau paket tak ada, jangan halangi startup.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 — best-effort; fallback ke certifi bila gagal
    pass

import structlog
from fastapi import FastAPI, WebSocket

from app.logging_config import configure_logging
configure_logging("backend")   # JSON-to-stdout, no file writes — see logging_config.py

from app.api.v1.market import router as market_router
from app.api.v1.history import router as history_router
from app.api.v1.opportunity import router as opportunity_router
from app.api.v1.futures_scanner import router as futures_router
from app.api.v1.futures_learning import router as futures_learning_router
from app.api.v1.market_context import router as market_context_router
from app.api.v1.binance_status import router as binance_status_router
from app.api.v1.futures_market  import router as futures_market_router
from app.api.v1.spot_market     import router as spot_market_router
from app.api.v1.balance import router as balance_router
from app.api.v1.signals import router as signals_router
from app.api.v1.futures_eligibility import router as futures_eligibility_router
from app.api.v1.big_mover_log import router as big_mover_log_router
from app.api.v1.backtest import router as backtest_router
from app.api.v1.admin             import router as admin_router
from app.api.v1.diagnostics       import router as diagnostics_router
from app.api.v1.predictive        import router as predictive_router
from app.api.v1.agent_config      import router as agent_config_router
from app.api.v1.exchange_settings import router as exchange_router
from app.api.v1.spot_repair       import router as spot_repair_router
from app.models.paper_trade import PaperTrade as _PaperTrade          # noqa: F401
from app.models.paper_balance import PaperBalance as _PaperBalance    # noqa: F401
from app.models.balance_transaction import BalanceTransaction as _BalTxn  # noqa: F401
from app.models.signal_weight import AgentSignalWeight as _ASW         # noqa: F401
from app.models.big_mover_log import BigMoverLog as _BML               # noqa: F401
from app.models.force_open_log import ForceOpenLog as _FOL             # noqa: F401
from app.models.backtest_result import WeeklyBacktestResult as _WBR   # noqa: F401
from app.models.rejection_log import RejectionLog as _RL
from app.models.predictive_log import PredictiveLog as _PL   # noqa: F401
from app.models.app_settings import AppSettings as _AS       # noqa: F401
from app.models.agent_config import AgentConfig as _AC       # noqa: F401
from app.models.spot_decision_event import SpotDecisionEvent as _SDE  # noqa: F401
from app.models.spot_model_version import SpotModelVersion as _SMV  # noqa: F401
from app.models.spot_repair_action import SpotRepairAction as _SRA  # noqa: F401
from app.config import get_settings
from app.database import create_db_schema, dispose_engine, set_db_available
from agents.opportunity.scheduler import run_opportunity_loop, run_bigmover_fastpass
from agents.opportunity.monitor import run_opportunity_monitor
from agents.futures.scheduler import run_futures_loop
from agents.futures.monitor import run_futures_monitor
from agents.futures.ws_big_mover_feed import run_ws_big_mover_feed   # Phase 2 BM4 / G21
from agents.futures.delisting_monitor import run_delisting_monitor   # G17
from app.ws.opportunity_stream import opportunity_stream
from app.ws.futures_stream import futures_stream
from app.ws.big_mover_alerts import big_mover_alert_stream   # G12

logger = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup:
      - Connect to PostgreSQL, create tables.
      - Start 4 background agents: Spot Scanner, Spot Monitor, Futures Scanner, Futures Monitor.
    Shutdown:
      - Cancel all background tasks.
    """
    # ── Database ───────────────────────────────────────────────────────────────
    try:
        await create_db_schema()
        set_db_available(True)
        logger.info("database_ready", msg="PostgreSQL connected")

        # PLAN_v5 Group C: seed agent_config defaults (idempotent — never
        # overwrites an operator's saved override).
        try:
            from app.services.agent_config_defaults import seed_agent_config_defaults
            n = await seed_agent_config_defaults()
            if n:
                logger.info("agent_config_seeded", inserted=n)
        except Exception as exc:
            logger.warning("agent_config_seed_failed", error=str(exc)[:120])
    except Exception as exc:
        set_db_available(False)
        logger.warning("database_unavailable", error=str(exc)[:120])

    # ── DB watchdog ────────────────────────────────────────────────────────────
    # Flag `_db_available` dulu HANYA diset sekali di atas. Kalau PostgreSQL belum
    # siap saat uvicorn naik (mesin baru boot / Docker menyusul), flag terkunci
    # False SELAMANYA: bobot tak termuat (cached_keys=0), learning mati, endpoint
    # DB balas 503 — dan tak ada yang menyembuhkan sampai restart manual.
    # Kejadian nyata: 22 Jul 2026 dan lagi 30 Jul 2026 ("WinError 1225 refused"
    # 18:07, baru ketahuan 21:40). Sejak kini flag mengikuti KENYATAAN: watchdog
    # menyondek DB berkala, menaikkan flag saat DB kembali (sekaligus menjalankan
    # schema+seed yang tadi gagal) dan menurunkannya saat DB hilang.
    async def _db_watchdog() -> None:
        from app.database import is_db_available, probe_db

        schema_done = is_db_available()
        while True:
            await asyncio.sleep(20)
            try:
                alive = await probe_db()
                if alive and not is_db_available():
                    if not schema_done:
                        # Startup tadi gagal — selesaikan skema + seed sekarang.
                        try:
                            await create_db_schema()
                            from app.services.agent_config_defaults import seed_agent_config_defaults
                            await seed_agent_config_defaults()
                            schema_done = True
                        except Exception as exc:
                            logger.warning("db_watchdog_schema_failed", error=str(exc)[:120])
                            continue
                    set_db_available(True)
                    logger.info("db_watchdog_recovered", msg="PostgreSQL kembali — fitur DB aktif lagi")
                elif not alive and is_db_available():
                    set_db_available(False)
                    logger.warning("db_watchdog_lost", msg="PostgreSQL tak menjawab — fitur DB dinonaktifkan sementara")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("db_watchdog_error", error=str(exc)[:120])

    db_watchdog_task = asyncio.create_task(_db_watchdog())

    # Penjaga host SPOT — tugas MANDIRI, bukan di dalam loop scanner.
    # 13 Agu: host utama mati, kedua scanner macet 42 menit, dan failover-nya
    # tak pernah menyala karena ia dipanggil dari atas loop yang justru sedang
    # terjebak menunggu timeout pada host mati itu. Tugas terpisah tak ikut
    # terblokir, jadi ia tetap bisa memindahkan host selagi loop utama macet.
    from app.services.binance_urls import run_host_watchdog
    host_watchdog_task = asyncio.create_task(run_host_watchdog())

    # ── Background agents ─────────────────────────────────────────────────────
    if _AGENTS_STANDALONE:
        logger.info("agents_mode", mode="standalone", msg="agents run in separate container")
        yield
        db_watchdog_task.cancel()
        try:
            await db_watchdog_task
        except asyncio.CancelledError:
            pass
        await dispose_engine()
        return

    # Embedded mode: all agents run inside this process
    opportunity_task     = asyncio.create_task(run_opportunity_loop())
    monitor_task         = asyncio.create_task(run_opportunity_monitor())
    futures_task         = asyncio.create_task(run_futures_loop())
    futures_monitor_task = asyncio.create_task(run_futures_monitor())
    # Phase 2 BM3 / G13: 60s fastpass for SPOT big-mover lane
    bigmover_fastpass_task = asyncio.create_task(run_bigmover_fastpass())
    # Phase 2 BM4 / G21: real-time WebSocket big-mover feed
    ws_big_mover_task = asyncio.create_task(run_ws_big_mover_feed())
    # G17: delisting risk monitor (poll every 6h)
    delisting_task = asyncio.create_task(run_delisting_monitor())
    # Notifier Telegram — pantau paper_trades, kabari open/close (zero-touch trading)
    from agents.notify.trade_watcher import run_notifier_loop
    notifier_task = asyncio.create_task(run_notifier_loop())

    # SPOT Adaptive Repair Agent + Verifier — guarded env, default off untuk safety launch
    _spot_repair_enabled = os.getenv("SPOT_REPAIR_ENABLED", "false").lower() == "true"
    spot_repair_task: asyncio.Task | None = None
    spot_verifier_task: asyncio.Task | None = None
    if _spot_repair_enabled:
        from agents.learning.spot_repair_agent import run_spot_repair_loop
        from agents.learning.spot_repair_verifier import run_spot_verifier_loop
        spot_repair_task = asyncio.create_task(run_spot_repair_loop())
        spot_verifier_task = asyncio.create_task(run_spot_verifier_loop())
        logger.info("spot_repair_agent_wired", enabled=True, verifier=True)
    else:
        logger.info("spot_repair_agent_wired", enabled=False,
                    hint="set SPOT_REPAIR_ENABLED=true untuk aktifkan loop background")

    yield  # ← app is running

    # ── Shutdown ───────────────────────────────────────────────────────────────
    _shutdown_tasks = [
        opportunity_task, monitor_task, futures_task, futures_monitor_task,
        bigmover_fastpass_task, ws_big_mover_task, delisting_task, notifier_task,
        db_watchdog_task,
    ]
    if spot_repair_task is not None:
        _shutdown_tasks.append(spot_repair_task)
    if spot_verifier_task is not None:
        _shutdown_tasks.append(spot_verifier_task)
    for task in _shutdown_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# ── Active Routers ─────────────────────────────────────────────────────────────
app.include_router(market_router,           prefix=settings.api_v1_prefix)
app.include_router(history_router,          prefix=settings.api_v1_prefix)
app.include_router(opportunity_router,      prefix=settings.api_v1_prefix)
app.include_router(futures_router,          prefix=settings.api_v1_prefix)
app.include_router(futures_learning_router, prefix=settings.api_v1_prefix)
app.include_router(market_context_router,   prefix=settings.api_v1_prefix)
app.include_router(binance_status_router,   prefix=settings.api_v1_prefix)
app.include_router(futures_market_router,   prefix=settings.api_v1_prefix)
app.include_router(spot_market_router,      prefix=settings.api_v1_prefix)
app.include_router(balance_router,          prefix=settings.api_v1_prefix)
app.include_router(signals_router,          prefix=settings.api_v1_prefix)
app.include_router(futures_eligibility_router, prefix=settings.api_v1_prefix)
app.include_router(big_mover_log_router,    prefix=settings.api_v1_prefix)
app.include_router(backtest_router,         prefix=settings.api_v1_prefix)
app.include_router(admin_router,            prefix=settings.api_v1_prefix)
app.include_router(diagnostics_router,      prefix=settings.api_v1_prefix)
app.include_router(predictive_router,       prefix=settings.api_v1_prefix)
app.include_router(agent_config_router,     prefix=settings.api_v1_prefix)
app.include_router(exchange_router,         prefix=settings.api_v1_prefix)
app.include_router(spot_repair_router,      prefix=settings.api_v1_prefix)


@app.websocket("/ws/opportunity")
async def ws_opportunity(websocket: WebSocket) -> None:
    await opportunity_stream(websocket)


@app.websocket("/ws/futures")
async def ws_futures(websocket: WebSocket) -> None:
    await futures_stream(websocket)


@app.websocket("/ws/big-movers")
async def ws_big_movers(websocket: WebSocket) -> None:
    await big_mover_alert_stream(websocket)


@app.get("/health")
async def health() -> dict:
    """Health check — DB + all agent statuses."""
    import httpx
    from app.database import is_db_available
    from agents.opportunity.scheduler  import get_state as opp_sched_state
    from agents.opportunity.monitor    import get_state as opp_mon_state
    from agents.futures.scheduler      import get_state as fut_sched_state
    from agents.futures.monitor        import get_state as fut_mon_state
    from agents.futures.weight_updater import get_state as weight_state
    db_ok = is_db_available()

    # In standalone mode agents run in a separate container — fetch their live
    # state from the agents health server (port 8001) instead of reading local
    # in-memory modules that were never started.
    agent_data: dict = {}
    if _AGENTS_STANDALONE:
        try:
            async with httpx.AsyncClient(timeout=2.0) as hc:
                r = await hc.get(f"{_AGENTS_HEALTH_URL}/health")
                if r.status_code == 200:
                    agent_data = r.json()
        except Exception:
            pass  # agents not ready yet — fall back to empty (shows "Stopped")

    opp_s = agent_data.get("spot_scanner",    opp_sched_state())
    opp_m = agent_data.get("spot_monitor",    opp_mon_state())
    fut_s = agent_data.get("futures_scanner", fut_sched_state())
    fut_m = agent_data.get("futures_monitor", fut_mon_state())
    w_s   = agent_data.get("weight_updater",  weight_state())

    # Record status changes for health log
    try:
        from app.services.health_logger import record_agent_status, record_db_status
        record_db_status(db_ok)
        record_agent_status("spot_scanner",    opp_s.get("running", False), opp_s.get("last_error"))
        record_agent_status("spot_monitor",    opp_m.get("running", False), opp_m.get("last_error"))
        record_agent_status("futures_scanner", fut_s.get("running", False), fut_s.get("last_error"))
        record_agent_status("futures_monitor", fut_m.get("running", False), fut_m.get("last_error"))
        record_agent_status("weight_updater",  not bool(w_s.get("last_error")), w_s.get("last_error"))
    except Exception:
        pass

    return {
        "status":          "ok",
        "db":              "ok" if db_ok else "unavailable",
        "database":        "connected" if db_ok else "unavailable",
        "spot_scanner":    opp_s,
        "spot_monitor":    opp_m,
        "futures_scanner": fut_s,
        "futures_monitor": fut_m,
        "weight_updater":  w_s,
        "notifier":        _notifier_state(),
        "scheduler":       opp_s,  # legacy key
    }


def _notifier_state() -> dict:
    """Status notifier Telegram (aman kalau modul belum siap)."""
    try:
        from agents.notify.trade_watcher import get_state
        return get_state()
    except Exception:
        return {"running": False, "last_error": "unavailable"}


@app.get("/health/log")
async def health_log(limit: int = 100) -> dict:
    """System health event log — API up/down, agent start/stop history."""
    from app.services.health_logger import get_log, get_stats
    return {
        "events": get_log(limit=min(limit, 200)),
        "stats":  get_stats(),
    }
