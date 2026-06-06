"""
In-memory store for Futures Scanner results — Agent 1 + Agent 2.
Supports WebSocket pub/sub (same pattern as opportunity store).
"""

import asyncio
import time
from typing import Any, Optional

STALE_SEC = 20 * 60  # results older than 20 min are stale

# ── State ─────────────────────────────────────────────────────────────────────

_results: dict[str, Any] = {}   # "agent1" | "agent2" → scan result
_ts:      dict[str, float] = {} # last scan timestamp per agent
_scanning: bool = False

_subscribers: list[asyncio.Queue] = []


# ── Write ──────────────────────────────────────────────────────────────────────

def set_result(agent: str, result: Any) -> None:
    """Called by scheduler after each successful scan cycle."""
    _results[agent] = result
    _ts[agent]      = time.time()
    _broadcast({"type": "snapshot", "agent": agent, **result})
    set_scanning(False)


def set_scanning(flag: bool) -> None:
    global _scanning
    _scanning = flag
    _broadcast({"type": "scanning", "scanning": flag})


def clear_results() -> None:
    _results.clear()
    _ts.clear()


# ── Read ───────────────────────────────────────────────────────────────────────

def get_result(agent: str) -> Optional[Any]:
    if agent not in _results:
        return None
    if time.time() - _ts.get(agent, 0) > STALE_SEC:
        return None
    return _results[agent]


def get_all_results() -> dict:
    """Return fresh results for both agents."""
    return {
        agent: res
        for agent, res in _results.items()
        if time.time() - _ts.get(agent, 0) <= STALE_SEC
    }


def last_scan_ts(agent: str) -> Optional[float]:
    return _ts.get(agent)


def is_scanning() -> bool:
    return _scanning


# ── Pub/Sub ────────────────────────────────────────────────────────────────────

def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def _broadcast(msg: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass
