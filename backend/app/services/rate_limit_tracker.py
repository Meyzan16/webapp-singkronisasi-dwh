"""
Binance API Rate Budget Tracker — G22.

Tracks X-MBX-USED-WEIGHT-1M headers from any Binance API response.
Provides warning / emergency threshold state for the Health panel.

Binance limits:
  SPOT  : 1200 weight/min
  FAPI  : 6000 weight/min

G22 thresholds (from PLAN-BIG-MOVERS spec):
  WARNING   : >1800/min  → log + expose in health
  EMERGENCY : >2100/min  → emergency flag (callers should skip non-critical calls)

Usage (anywhere in agent code, after an httpx response):
    from app.services.rate_limit_tracker import record_weight

    r = await client.get(fapi("/fapi/v1/klines"), ...)
    weight = int(r.headers.get("X-MBX-USED-WEIGHT-1M", 0))
    record_weight(weight, api="fapi")
"""

import time
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Binance per-minute weight limits
SPOT_WEIGHT_LIMIT = 1200
FAPI_WEIGHT_LIMIT = 6000

# G22 thresholds — based on FAPI (heavier consumer)
WARNING_WEIGHT   = 1800   # >1800 → warn
EMERGENCY_WEIGHT = 2100   # >2100 → degrade flag

# In-memory state per API type
_state: dict[str, dict] = {
    "fapi": {
        "last_used":    0,
        "peak_1m":      0,
        "warning":      False,
        "emergency":    False,
        "last_updated": None,
    },
    "spot": {
        "last_used":    0,
        "peak_1m":      0,
        "warning":      False,
        "emergency":    False,
        "last_updated": None,
    },
}


def record_weight(weight: int, api: str = "fapi") -> None:
    """
    Record weight from a Binance API response header.
    Call this after any httpx response that carries X-MBX-USED-WEIGHT-1M.
    """
    if weight <= 0 or api not in _state:
        return

    s = _state[api]
    s["last_used"]    = weight
    s["last_updated"] = time.time()
    if weight > s["peak_1m"]:
        s["peak_1m"] = weight

    was_warning   = s["warning"]
    was_emergency = s["emergency"]
    s["warning"]   = weight > WARNING_WEIGHT
    s["emergency"] = weight > EMERGENCY_WEIGHT

    if s["emergency"] and not was_emergency:
        logger.warning(
            "rate_limit_emergency",
            api=api, weight=weight, threshold=EMERGENCY_WEIGHT,
        )
    elif s["warning"] and not was_warning:
        logger.info(
            "rate_limit_warning",
            api=api, weight=weight, threshold=WARNING_WEIGHT,
        )


def is_emergency(api: str = "fapi") -> bool:
    """Return True if current weight exceeds emergency threshold — skip non-critical calls."""
    return _state.get(api, {}).get("emergency", False)


def is_warning(api: str = "fapi") -> bool:
    """Return True if current weight is in warning zone."""
    return _state.get(api, {}).get("warning", False)


def get_state() -> dict:
    """
    Return current rate budget state for /health endpoint.
    Includes staleness flag (>90s since last update = we lost the counter).
    """
    now = time.time()
    out: dict = {}
    for api, s in _state.items():
        limit  = FAPI_WEIGHT_LIMIT if api == "fapi" else SPOT_WEIGHT_LIMIT
        stale  = bool(s["last_updated"] and (now - s["last_updated"]) > 90)
        out[api] = {
            "last_used":    s["last_used"],
            "peak_1m":      s["peak_1m"],
            "limit":        limit,
            "pct":          round(s["last_used"] / limit * 100, 1),
            "warning":      s["warning"],
            "emergency":    s["emergency"],
            "stale":        stale,
            "last_updated": s["last_updated"],
        }
    return out


def reset_peak() -> None:
    """Reset peak counters (e.g. at start of a new 1-min window). Optional call."""
    for s in _state.values():
        s["peak_1m"] = s["last_used"]
