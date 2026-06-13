"""In-memory store for opportunity scanner results with WebSocket pub/sub."""
import asyncio
import time
from typing import Optional

_result: Optional[dict] = None
_ts: float = 0.0
_scanning: bool = False
STALE_SEC = 30 * 60  # 30 minutes

_subscribers: list[asyncio.Queue] = []


def subscribe() -> "asyncio.Queue[dict]":
    """Register a WebSocket listener queue. Returns the queue."""
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=10)
    _subscribers.append(q)
    return q


def unsubscribe(q: "asyncio.Queue[dict]") -> None:
    """Remove a listener queue."""
    if q in _subscribers:
        _subscribers.remove(q)


def _broadcast(msg: dict) -> None:
    for q in _subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            # §13.7: keep-latest — client lambat tidak boleh kehilangan snapshot
            # terbaru selamanya; buang antrean lama, masukkan yang terbaru
            try:
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(msg)
            except (asyncio.QueueFull, asyncio.QueueEmpty):
                pass


def set_scanning(state: bool) -> None:
    """Notify clients that a scan has started or failed."""
    global _scanning
    _scanning = state
    _broadcast({"type": "scanning", "scanning": state})


def set_result(data: dict) -> None:
    """Store scan result and broadcast to all WebSocket clients."""
    global _result, _ts, _scanning
    _result = data
    _ts = time.time()
    _scanning = False
    _broadcast({"type": "snapshot", **data})


def get_result() -> Optional[dict]:
    if _result is None:
        return None
    if time.time() - _ts > STALE_SEC:
        return None
    return _result


def last_scan_ts() -> Optional[float]:
    # §13.8: kembalikan _ts walau result di-clear — countdown UI tetap jalan
    return _ts if _ts > 0 else None


def is_scanning() -> bool:
    return _scanning


def clear_result() -> None:
    """Clear cache so next request triggers a fresh scan."""
    global _result, _ts
    _result = None
    _ts = 0.0
