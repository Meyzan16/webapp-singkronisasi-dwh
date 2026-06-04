"""
Background Scanner Scheduler — single source of truth for scanning + logging.

Runs all 4 trading styles every 15 minutes. Completely independent of
the web browser — keeps running 24/7 as long as the backend process is alive.

Flow per cycle:
  for each style (scalping → daytrading → swing → position):
    1. Run core scan (Binance data + TA)
    2. Write results to scan_store (scanner API reads from here)
    3. Log qualifying signals to paper_trades (only place that writes DB)
    4. Sleep 3s before next style (avoid hammering Binance)

The scanner API is read-only: it serves scan_store cache and does NOT
log anything. This guarantees each signal is logged exactly once.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from app.services.paper_trader import paper_trader
from app.services.scheduler import scan_store

logger = structlog.get_logger(__name__)

STYLES       = ["scalping", "daytrading", "swing", "position"]
INTERVAL_SEC = 15 * 60   # 15 minutes between cycles
STARTUP_DELAY = 15        # seconds after app start before first scan


# ── State ─────────────────────────────────────────────────────────────────────

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
    from app.api.v1.scanner import scan_market_core  # lazy — avoids circular import
    try:
        result  = await scan_market_core(style=style)

        # ── 1. Publish to scan_store (scanner API reads from here) ────────────
        scan_store.set_result(style, result)

        # ── 2. Log to paper_trades (scheduler is the only writer) ─────────────
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
        await asyncio.sleep(3)   # brief gap between styles

    _state.last_logged   = cycle_logged
    _state.total_logged += cycle_logged
    _state.cycle_count  += 1
    _state.next_scan_ts  = time.time() + INTERVAL_SEC

    logger.info("scheduler_cycle_complete",
                cycle=_state.cycle_count,
                logged=cycle_logged,
                total=_state.total_logged,
                next_in_minutes=INTERVAL_SEC // 60)


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run_scanner_loop() -> None:
    """Infinite background loop. Started once in FastAPI lifespan."""
    _state.running      = True
    _state.next_scan_ts = time.time() + STARTUP_DELAY

    logger.info("scanner_scheduler_started",
                interval_minutes=INTERVAL_SEC // 60,
                startup_delay_seconds=STARTUP_DELAY)

    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            await _run_one_cycle()
        except asyncio.CancelledError:
            logger.info("scanner_scheduler_stopped")
            _state.running = False
            raise
        except Exception as exc:
            _state.last_error = str(exc)[:120]
            logger.error("scheduler_unexpected_error", error=_state.last_error)

        elapsed   = time.time() - _state.last_scan_ts
        sleep_for = max(60, INTERVAL_SEC - elapsed)
        await asyncio.sleep(sleep_for)
