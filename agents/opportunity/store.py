"""In-memory store for opportunity scanner results."""
import time
from typing import Any, Optional

_result: Optional[dict] = None
_ts: float = 0.0
STALE_SEC = 30 * 60  # 30 minutes


def set_result(data: dict) -> None:
    global _result, _ts
    _result = data
    _ts = time.time()


def get_result() -> Optional[dict]:
    if _result is None:
        return None
    if time.time() - _ts > STALE_SEC:
        return None
    return _result


def last_scan_ts() -> Optional[float]:
    return _ts if _result else None
