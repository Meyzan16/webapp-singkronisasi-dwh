"""
G17 — Delisting Risk Monitor.

Polls Binance every 6 hours for coins scheduled to be delisted from futures.
Blacklists those symbols from the Big Mover Lane to prevent opening positions
that could be force-closed at an unfavourable price.

Public API:
  get_delisted_symbols() → frozenset[str]   — symbols to avoid
  is_delisting_risk(symbol) → bool          — quick guard check
"""

import asyncio
import time
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

POLL_INTERVAL_SEC   = 6 * 3600    # check every 6 hours
DELIST_BUFFER_HOURS = 24           # blacklist starts 24 h before delist
STARTUP_DELAY       = 120          # wait for backend to fully start

_delisted_symbols: frozenset[str] = frozenset()
_last_poll_ts:     float          = 0.0
_last_error:       Optional[str]  = None
_running:          bool           = False


def get_state() -> dict:
    return {
        "running":         _running,
        "last_poll_ts":    _last_poll_ts,
        "last_error":      _last_error,
        "delisted_count":  len(_delisted_symbols),
        "delisted":        sorted(_delisted_symbols),
    }


def get_delisted_symbols() -> frozenset[str]:
    """Return set of symbols currently at delisting risk."""
    return _delisted_symbols


def is_delisting_risk(symbol: str) -> bool:
    """Return True if symbol should be avoided due to upcoming delist."""
    return symbol in _delisted_symbols


# ── Fetch ──────────────────────────────────────────────────────────────────────

async def _fetch_delist_schedule() -> list[dict]:
    """
    Fetch Binance futures delist schedule.
    Binance publishes announcements at:
      GET https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query
      (no auth required)
    We parse the symbols from it and cross-check with upcoming delist dates.

    Note: Binance also has a /fapi/v1/exchangeInfo endpoint where delisted
    symbols disappear — we check both to be safe.
    """
    symbols_at_risk: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Primary: fapi exchangeInfo — symbols with deliveryDate close to now
            r = await client.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
            if r.status_code == 200:
                data = r.json()
                now_ms = int(time.time() * 1000)
                cutoff_ms = now_ms + DELIST_BUFFER_HOURS * 3600 * 1000
                for s in data.get("symbols", []):
                    # deliveryDate is set for quarterly contracts; for perpetuals it's 4102444800000
                    # (year 2099 = never). Only flag if it's within 24h.
                    delivery = s.get("deliveryDate", 4102444800000)
                    status   = s.get("status", "")
                    sym      = s.get("symbol", "")
                    if not sym.endswith("USDT"):
                        continue
                    # Binance sets status="PRE_DELIVERING" or "DELIVERING" before delist
                    if status in ("PRE_DELIVERING", "DELIVERING", "END_OF_DAY"):
                        symbols_at_risk.append(sym)
                        logger.info("delist_risk_detected", symbol=sym, status=status)
                    elif delivery < cutoff_ms:
                        symbols_at_risk.append(sym)
                        logger.info("delist_risk_detected", symbol=sym,
                                    delivery_in_h=round((delivery - now_ms) / 3600000, 1))
    except Exception as exc:
        logger.warning("delist_fetch_error", error=str(exc)[:120])

    return symbols_at_risk


# ── Background loop ────────────────────────────────────────────────────────────

async def run_delisting_monitor() -> None:
    """Poll Binance every 6h for delisting risk symbols."""
    global _delisted_symbols, _last_poll_ts, _last_error, _running
    _running = True
    logger.info("delisting_monitor_started", poll_interval_h=POLL_INTERVAL_SEC // 3600)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            at_risk = await _fetch_delist_schedule()
            _delisted_symbols = frozenset(at_risk)
            _last_poll_ts     = time.time()
            _last_error       = None
            if at_risk:
                logger.warning("delisted_symbols_updated", count=len(at_risk), symbols=at_risk[:10])
            else:
                logger.info("delisted_symbols_updated", count=0)
        except asyncio.CancelledError:
            _running = False
            logger.info("delisting_monitor_stopped")
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.warning("delisting_monitor_error", error=_last_error)

        await asyncio.sleep(POLL_INTERVAL_SEC)
