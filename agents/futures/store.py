"""
In-memory store for Futures Scanner results — Agent 1 + Agent 2.
Supports WebSocket pub/sub (same pattern as opportunity store).
"""

import asyncio
import time
from typing import Any, Optional

STALE_SEC = 5 * 60   # F32: results older than 5 min are stale (was 20 min)

# ── State ─────────────────────────────────────────────────────────────────────

_results: dict[str, Any] = {}   # "agent1" | "agent2" → scan result
_ts:      dict[str, float] = {} # last scan timestamp per agent
_scanning: bool = False

_subscribers: list[asyncio.Queue] = []

# PLAN-SIGNAL-GAP P4: Big Movers monitor — coins with large 24h change that the
# scanner saw this cycle, with their score/qualification status, regardless of
# whether they made it into any agent's accepted results.
_big_movers:    list[Any] = []
_big_movers_ts: float     = 0.0

# PLAN_v15 P3a: market breadth — fraction of top gainers (24h > +10%) whose 1h
# change is negative this cycle. High fade_frac = pump-and-fade day (4 Juli pattern).
_market_breadth:    dict  = {}
_market_breadth_ts: float = 0.0


# ── Write ──────────────────────────────────────────────────────────────────────

def set_result(agent: str, result: Any) -> None:
    """Called by scheduler after each successful scan cycle.
    F107: does NOT call set_scanning(False) — caller must do that after ALL agents done."""
    _results[agent] = result
    _ts[agent]      = time.time()
    _broadcast({"type": "snapshot", "agent": agent, **result})


def set_scanning(flag: bool) -> None:
    global _scanning
    _scanning = flag
    _broadcast({"type": "scanning", "scanning": flag})


def clear_results() -> None:
    _results.clear()
    _ts.clear()


def set_big_movers(movers: list) -> None:
    """PLAN-SIGNAL-GAP P4: called by scheduler after each scan cycle."""
    global _big_movers, _big_movers_ts
    _big_movers    = movers
    _big_movers_ts = time.time()


def set_market_breadth(breadth: dict) -> None:
    """PLAN_v15 P3a: called by scheduler after each scan cycle."""
    global _market_breadth, _market_breadth_ts
    _market_breadth    = breadth
    _market_breadth_ts = time.time()


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


def get_big_movers() -> list:
    """PLAN-SIGNAL-GAP P4: stale-checked like agent results (5 min TTL)."""
    if time.time() - _big_movers_ts > STALE_SEC:
        return []
    return _big_movers


def get_market_breadth() -> dict:
    """PLAN_v15 P3a: stale-checked (5 min TTL) — empty dict = unknown → gates fail open."""
    if time.time() - _market_breadth_ts > STALE_SEC:
        return {}
    return _market_breadth


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
