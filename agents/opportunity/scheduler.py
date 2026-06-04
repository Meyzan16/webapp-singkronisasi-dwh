"""
Opportunity Scanner Scheduler — runs every 15 minutes.
Finds coins with high potential for price increase across all styles/timeframes.
"""

import asyncio
import time
from typing import Optional

import structlog

from agents.opportunity import scanner as opp_scanner
from agents.opportunity import store as opp_store

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 15 * 60
STARTUP_DELAY = 20   # slightly after main scanner starts

_running      = False
_cycle_count  = 0
_last_scan_ts: Optional[float] = None
_last_error:   Optional[str]   = None


def get_state() -> dict:
    return {
        "running":         _running,
        "cycle_count":     _cycle_count,
        "last_scan_ts":    _last_scan_ts,
        "last_error":      _last_error,
        "interval_minutes": INTERVAL_SEC // 60,
    }


async def run_opportunity_loop() -> None:
    global _running, _cycle_count, _last_scan_ts, _last_error

    _running = True
    logger.info("opportunity_agent_started", interval_min=INTERVAL_SEC // 60)

    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            result = await opp_scanner.run_opportunity_scan()
            opp_store.set_result(result)
            _last_scan_ts = time.time()
            _cycle_count += 1
            _last_error   = None
            logger.info("opportunity_cycle_done",
                        cycle=_cycle_count, found=result.get("found", 0))

        except asyncio.CancelledError:
            logger.info("opportunity_agent_stopped")
            _running = False
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.error("opportunity_agent_error", error=_last_error)

        elapsed   = time.time() - (_last_scan_ts or time.time())
        sleep_for = max(60, INTERVAL_SEC - elapsed)
        await asyncio.sleep(sleep_for)
