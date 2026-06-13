"""
Binance API Status — cek kondisi koneksi ke Binance.

GET /market/binance-status

Returns:
  - spot_ok / futures_ok : apakah API reachable
  - banned_until         : timestamp (epoch) kalau IP banned
  - rate_limit_pct       : % dari weight limit terpakai (1200/min spot, 2400/min futures)
  - latency_ms           : round-trip latency ke Binance
  - error                : pesan error terakhir
"""

import time
from typing import Optional

import httpx
import structlog

from fastapi import APIRouter
from app.services.binance_urls import spot, fapi

router = APIRouter(tags=["market"])
logger = structlog.get_logger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache: Optional[dict] = None
_cache_ts: float = 0.0
CACHE_TTL = 30  # refresh every 30s

SPOT_WEIGHT_LIMIT    = 1200   # requests per minute
FUTURES_WEIGHT_LIMIT = 2400   # requests per minute


async def _check_binance() -> dict:
    result = {
        "spot_ok":        False,
        "futures_ok":     False,
        "spot_latency_ms":    None,
        "futures_latency_ms": None,
        "spot_weight_used":    0,
        "futures_weight_used": 0,
        "spot_weight_pct":     0.0,
        "futures_weight_pct":  0.0,
        "spot_banned_until":    None,
        "futures_banned_until": None,
        "spot_error":     None,
        "futures_error":  None,
        "checked_at":     int(time.time()),
    }

    async with httpx.AsyncClient(timeout=8) as client:
        # ── Spot ping ──────────────────────────────────────────────────────────
        try:
            t0 = time.monotonic()
            r  = await client.get(spot("/api/v3/ping"))
            ms = round((time.monotonic() - t0) * 1000)

            if r.status_code == 200:
                result["spot_ok"]         = True
                result["spot_latency_ms"] = ms
                used = r.headers.get("X-MBX-USED-WEIGHT-1M", "0")
                result["spot_weight_used"] = int(used)
                result["spot_weight_pct"]  = round(int(used) / SPOT_WEIGHT_LIMIT * 100, 1)

            elif r.status_code == 429:
                retry = r.headers.get("Retry-After", "60")
                result["spot_error"] = f"Rate limited (429) — retry after {retry}s"

            elif r.status_code == 418:
                retry_after = int(r.headers.get("Retry-After", "3600"))
                banned_until = int(time.time()) + retry_after
                result["spot_banned_until"] = banned_until
                result["spot_error"] = (
                    f"IP BANNED (418) — sampai {_fmt_ban_time(banned_until)} "
                    f"({_fmt_duration(retry_after)})"
                )
            else:
                result["spot_error"] = f"HTTP {r.status_code}"

        except httpx.ConnectError:
            result["spot_error"] = "Tidak bisa terhubung ke Binance Spot API"
        except httpx.TimeoutException:
            result["spot_error"] = "Timeout — koneksi ke Binance lambat"
        except Exception as exc:
            result["spot_error"] = str(exc)[:80]

        # ── Futures ping ───────────────────────────────────────────────────────
        try:
            t0 = time.monotonic()
            r  = await client.get(fapi("/fapi/v1/ping"))
            ms = round((time.monotonic() - t0) * 1000)

            if r.status_code == 200:
                result["futures_ok"]         = True
                result["futures_latency_ms"] = ms
                used = r.headers.get("X-MBX-USED-WEIGHT-1M", "0")
                result["futures_weight_used"] = int(used)
                result["futures_weight_pct"]  = round(int(used) / FUTURES_WEIGHT_LIMIT * 100, 1)

            elif r.status_code == 429:
                retry = r.headers.get("Retry-After", "60")
                result["futures_error"] = f"Rate limited (429) — retry after {retry}s"

            elif r.status_code == 418:
                retry_after = int(r.headers.get("Retry-After", "3600"))
                banned_until = int(time.time()) + retry_after
                result["futures_banned_until"] = banned_until
                result["futures_error"] = (
                    f"IP BANNED (418) — sampai {_fmt_ban_time(banned_until)} "
                    f"({_fmt_duration(retry_after)})"
                )
            else:
                result["futures_error"] = f"HTTP {r.status_code}"

        except httpx.ConnectError:
            result["futures_error"] = "Tidak bisa terhubung ke Binance Futures API"
        except httpx.TimeoutException:
            result["futures_error"] = "Timeout — koneksi ke Binance Futures lambat"
        except Exception as exc:
            result["futures_error"] = str(exc)[:80]

    return result


def _fmt_ban_time(ts: int) -> str:
    """Format ban expiry as HH:MM:SS WIB."""
    import datetime
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} detik"
    if seconds < 3600:
        return f"{seconds // 60} menit"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h} jam {m} menit"


@router.get("/market/binance-status")
async def get_binance_status() -> dict:
    """Check Binance Spot + Futures API connectivity, rate limits, ban status."""
    global _cache, _cache_ts

    if _cache and (time.time() - _cache_ts) < CACHE_TTL:
        return _cache

    try:
        result    = await _check_binance()
        _cache    = result
        _cache_ts = time.time()

        # ── Log status changes ──────────────────────────────────────────────
        try:
            from app.services.health_logger import record_api_status
            record_api_status(
                "spot",
                ok=result["spot_ok"],
                latency_ms=result.get("spot_latency_ms"),
                error=result.get("spot_error"),
                banned_until=result.get("spot_banned_until"),
            )
            record_api_status(
                "futures",
                ok=result["futures_ok"],
                latency_ms=result.get("futures_latency_ms"),
                error=result.get("futures_error"),
                banned_until=result.get("futures_banned_until"),
            )
        except Exception:
            pass  # never let logging break the main response

        return result
    except Exception as exc:
        logger.warning("binance_status_check_error", error=str(exc)[:80])
        return {
            "spot_ok": False, "futures_ok": False,
            "spot_error": str(exc)[:80], "futures_error": None,
            "checked_at": int(time.time()),
        }
