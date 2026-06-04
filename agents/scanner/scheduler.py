"""
Scanner Scheduler Agent — single source of truth for scanning + logging.

Runs all 4 trading styles every 15 minutes.
Independent of the web browser — keeps running 24/7.

Flow per cycle:
  for each style (scalping → daytrading → swing → position):
    1. Run core scan (Binance REST + TA engine)
    2. Write results to agents.scanner.store (backend API reads from here)
    3. Log qualifying signals to paper_trades DB (only place that writes)
    4. Sleep 3s before next style (avoid hammering Binance)

To run standalone:
    python -m agents

To run inside backend (current mode):
    Imported by backend/app/main.py lifespan
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from agents.scanner import store as scan_store

logger = structlog.get_logger(__name__)

STYLES        = ["scalping", "daytrading", "swing", "position"]
INTERVAL_SEC  = 15 * 60   # 15 minutes between cycles
STARTUP_DELAY = 15         # seconds after start before first scan


# ── State (read by /health and /api/v1/scheduler/status) ─────────────────────

@dataclass
class SchedulerState:
    running:         bool            = False
    last_scan_ts:    Optional[float] = None
    next_scan_ts:    Optional[float] = None
    cycle_count:     int             = 0
    last_logged:     int             = 0
    total_logged:    int             = 0
    last_error:      Optional[str]   = None
    style_last_scan: dict            = field(default_factory=dict)


_state = SchedulerState()


def get_state() -> dict:
    return {
        "running":          _state.running,
        "interval_minutes": INTERVAL_SEC // 60,
        "cycle_count":      _state.cycle_count,
        "last_scan":        _state.last_scan_ts,
        "next_scan":        _state.next_scan_ts,
        "last_logged":      _state.last_logged,
        "total_logged":     _state.total_logged,
        "last_error":       _state.last_error,
        "style_last_scan":  _state.style_last_scan,
    }


# ── Core scan ─────────────────────────────────────────────────────────────────

async def _scan_one_style(style: str) -> int:
    """
    Scan one style, cache results, log qualifying signals.
    Returns number of new trades logged.
    """
    # Lazy imports to avoid circular dependency at module load time
    from app.api.v1.scanner import scan_market_core          # TA engine (in backend)
    from app.services.paper_trader import paper_trader        # DB writer (in backend)

    try:
        result  = await scan_market_core(style=style)

        # 1. Publish to scan_store (backend scanner API reads from here)
        scan_store.set_result(style, result)

        # 2. Log to paper_trades — agents.scanner.scheduler is the only writer
        signals = [sig.model_dump() for sig in result.results]
        logged  = await paper_trader.log_signals_batch(signals, style)

        _state.style_last_scan[style] = time.time()
        logger.info("scheduler_style_done",
                    style=style, found=len(signals), logged=logged)
        return logged

    except Exception as exc:
        err = str(exc)[:120]
        _state.last_error = f"{style}: {err}"
        logger.warning("scheduler_style_error", style=style, error=err)
        return 0


async def _run_one_cycle() -> None:
    """Scan all 4 styles sequentially."""
    _state.last_scan_ts = time.time()
    _state.last_error   = None
    cycle_logged        = 0

    for style in STYLES:
        logged        = await _scan_one_style(style)
        cycle_logged += logged
        await asyncio.sleep(3)

    _state.last_logged   = cycle_logged
    _state.total_logged += cycle_logged
    _state.cycle_count  += 1
    _state.next_scan_ts  = time.time() + INTERVAL_SEC

    logger.info("scheduler_cycle_complete",
                cycle=_state.cycle_count,
                logged=cycle_logged,
                total=_state.total_logged,
                next_in_minutes=INTERVAL_SEC // 60)


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_scanner_loop() -> None:
    """Infinite background loop. Started by backend lifespan or agents/main.py."""
    _state.running      = True
    _state.next_scan_ts = time.time() + STARTUP_DELAY

    logger.info("scanner_agent_started",
                interval_minutes=INTERVAL_SEC // 60,
                startup_delay_seconds=STARTUP_DELAY)

    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            await _run_one_cycle()
        except asyncio.CancelledError:
            logger.info("scanner_agent_stopped")
            _state.running = False
            raise
        except Exception as exc:
            _state.last_error = str(exc)[:120]
            logger.error("scanner_agent_error", error=_state.last_error)

        elapsed   = time.time() - _state.last_scan_ts
        sleep_for = max(60, INTERVAL_SEC - elapsed)
        await asyncio.sleep(sleep_for)
