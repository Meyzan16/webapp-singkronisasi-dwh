"""
Shared in-memory store for the last scanner results per style.

The scanner scheduler is the ONLY writer.
The backend scanner API reads from here — no live scan on API calls.
"""

import time
from typing import Any, Optional

# style → {"result": ScannerResponse, "ts": float}
_store: dict[str, dict] = {}

STALE_SEC = 20 * 60  # results older than 20 min are stale


def set_result(style: str, result: Any) -> None:
    """Called by scheduler after each successful scan cycle."""
    _store[style] = {"result": result, "ts": time.time()}


def get_result(style: str) -> Optional[Any]:
    """Return cached ScannerResponse or None if missing/stale."""
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
    """True only if every style has a fresh cached result."""
    return all(get_result(s) is not None for s in styles)
