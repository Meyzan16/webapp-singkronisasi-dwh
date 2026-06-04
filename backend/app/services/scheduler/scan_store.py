"""
Shared in-memory store for the last scanner results per style.

The scheduler is the ONLY writer. The scanner API reads from here
and serves cached results — no live scan triggered by API calls.

This removes the double-logging problem where both the scheduler
and the API endpoint were independently calling log_signals_batch.
"""

import time
from typing import Any, Optional

# style → {"result": ScannerResponse, "ts": float}
_store: dict[str, dict] = {}

STALE_SEC = 20 * 60  # results older than 20 min are considered stale


def set_result(style: str, result: Any) -> None:
    """Called by scheduler after each successful scan cycle."""
    _store[style] = {"result": result, "ts": time.time()}


def get_result(style: str) -> Optional[Any]:
    """Return cached ScannerResponse or None if missing / stale."""
    entry = _store.get(style)
    if entry is None:
        return None
    if time.time() - entry["ts"] > STALE_SEC:
        return None
    return entry["result"]


def last_scan_ts(style: str) -> Optional[float]:
    """Unix timestamp of the last scan for this style, or None."""
    entry = _store.get(style)
    return entry["ts"] if entry else None


def all_styles_cached(styles: list[str]) -> bool:
    """True only if every requested style has a fresh cached result."""
    return all(get_result(s) is not None for s in styles)
