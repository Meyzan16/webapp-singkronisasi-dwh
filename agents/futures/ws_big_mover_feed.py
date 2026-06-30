"""
WebSocket Real-Time Big Mover Feed — PLAN-BIG-MOVERS Phase 2 BM4 / G21.

Subscribe Binance Futures `!ticker@arr` stream (1s update, all symbols).
Filter symbols dengan abs(price_change_1m) ≥ 1% (or change_24h ≥ 5%) → push ke store.

Latency target: market move → store cache < 2 detik (vs 2 min scan cycle).

Heartbeat tiap 10s; fallback ke REST polling kalau no msg > 30s (EC3).
Auto-reconnect dengan exponential backoff.
"""

import asyncio
import json
import time
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Binance Futures WebSocket — combined stream
WS_URL = "wss://fstream.binance.com/ws/!ticker@arr"

# Filter thresholds
MIN_ABS_CHANGE_24H = 5.0    # show coins with ≥5% move (catches early moves)
MIN_ABS_CHANGE_1M  = 1.0    # spike: ≥1% in 1 min

# Heartbeat / fallback
HEARTBEAT_SEC      = 10
STALE_FALLBACK_SEC = 30
RECONNECT_BASE_SEC = 5
RECONNECT_MAX_SEC  = 60

# State
_running:        bool                       = False
_last_msg_ts:    float                      = 0.0
_last_error:     Optional[str]              = None
_msg_count:      int                        = 0
_movers_live:    dict[str, dict]            = {}   # symbol -> ticker snapshot
_prev_prices:    dict[str, tuple[float, float]] = {}  # symbol -> (price, ts) for 1m delta
_subscribers:    list[asyncio.Queue]        = []


def get_state() -> dict:
    """Public state for /health and dashboards."""
    age = round(time.time() - _last_msg_ts, 1) if _last_msg_ts else None
    return {
        "running":         _running,
        "last_msg_ts":     _last_msg_ts,
        "age_sec":         age,
        "last_error":      _last_error,
        "msg_count":       _msg_count,
        "movers_tracked":  len(_movers_live),
        "is_stale":        bool(age and age > STALE_FALLBACK_SEC),
    }


def get_live_movers(limit: int = 50) -> list[dict]:
    """
    Return current snapshot of live big movers, sorted by abs(change_1m) desc.
    Returns [] if feed is stale (age > STALE_FALLBACK_SEC) — caller falls back to REST.
    """
    if not _last_msg_ts or (time.time() - _last_msg_ts) > STALE_FALLBACK_SEC:
        return []
    movers = sorted(
        _movers_live.values(),
        key=lambda m: abs(m.get("change_1m_pct", 0)),
        reverse=True,
    )
    return movers[:limit]


def subscribe() -> asyncio.Queue:
    """Subscribe to per-coin alert events (spike crossings)."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
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


# ── Processing ─────────────────────────────────────────────────────────────────

def _process_tickers(tickers: list[dict]) -> None:
    """Parse one `!ticker@arr` batch — update internal state, emit spike events."""
    global _last_msg_ts, _msg_count
    now = time.time()
    _last_msg_ts = now
    _msg_count  += 1

    for t in tickers:
        sym = t.get("s", "")
        if not sym.endswith("USDT"):
            continue
        try:
            price       = float(t.get("c", 0))   # last price
            change_24h  = float(t.get("P", 0))   # percent change 24h
            quote_vol   = float(t.get("q", 0))   # quote volume
        except (TypeError, ValueError):
            continue

        # 1-minute delta
        change_1m = 0.0
        prev = _prev_prices.get(sym)
        if prev:
            prev_price, prev_ts = prev
            if (now - prev_ts) >= 50 and prev_price > 0:   # ≥50s — close enough to "1m"
                change_1m = (price - prev_price) / prev_price * 100
                _prev_prices[sym] = (price, now)
            # else: keep old reference until 1m elapses
        else:
            _prev_prices[sym] = (price, now)

        # Filter: keep coins above either threshold
        if abs(change_24h) < MIN_ABS_CHANGE_24H and abs(change_1m) < MIN_ABS_CHANGE_1M:
            _movers_live.pop(sym, None)
            _prev_prices.pop(sym, None)  # prune stale price ref when symbol leaves tracking
            continue

        prev_state = _movers_live.get(sym, {})
        _movers_live[sym] = {
            "symbol":          sym,
            "price":           price,
            "change_24h":      round(change_24h, 2),
            "change_1m_pct":   round(change_1m, 3),
            "quote_vol":       round(quote_vol, 0),
            "ts":              now,
        }

        # Emit spike crossing event (change_1m crosses threshold)
        was_spike = abs(prev_state.get("change_1m_pct", 0)) >= MIN_ABS_CHANGE_1M
        is_spike  = abs(change_1m) >= MIN_ABS_CHANGE_1M
        if is_spike and not was_spike:
            _broadcast({
                "type":          "spike",
                "symbol":        sym,
                "price":         price,
                "change_1m_pct": round(change_1m, 3),
                "change_24h":    round(change_24h, 2),
                "ts":            now,
            })

        # G12: broadcast push notification when coin crosses ±20% 24h threshold
        was_big = abs(prev_state.get("change_24h", 0)) >= 20.0
        is_big  = abs(change_24h) >= 20.0
        if is_big and not was_big:
            try:
                from app.ws.big_mover_alerts import broadcast_big_mover as _bma
                asyncio.create_task(_bma(sym, change_24h, price, quote_vol))
            except Exception:
                pass


# ── EC3: REST fallback + heartbeat watchdog ────────────────────────────────────

_REST_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"


async def _rest_fallback_poll() -> None:
    """EC3: Populate _movers_live via REST when WS feed has been silent >30s.

    Uses the same field names as _process_tickers so consumers see consistent data.
    change_1m_pct is unknown from REST → set to 0.0.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_REST_URL)
            if r.status_code != 200:
                return
            now  = time.time()
            kept = 0
            for t in r.json():
                sym = t.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                try:
                    change_24h = float(t.get("priceChangePercent", 0))
                    price      = float(t.get("lastPrice", 0))
                    quote_vol  = float(t.get("quoteVolume", 0))
                except (TypeError, ValueError):
                    continue
                if abs(change_24h) >= MIN_ABS_CHANGE_24H:
                    _movers_live[sym] = {
                        "symbol":        sym,
                        "price":         price,
                        "change_24h":    round(change_24h, 2),
                        "change_1m_pct": 0.0,
                        "quote_vol":     round(quote_vol, 0),
                        "ts":            now,
                    }
                    kept += 1
            logger.info("ws_rest_fallback_done", movers=kept)
    except Exception as exc:
        logger.warning("ws_rest_fallback_error", error=str(exc)[:80])


async def _heartbeat_watchdog() -> None:
    """EC3: Every 10s check WS message age; trigger REST fallback when stale >30s."""
    while True:
        await asyncio.sleep(HEARTBEAT_SEC)
        if not _last_msg_ts:
            continue
        age = time.time() - _last_msg_ts
        if age > STALE_FALLBACK_SEC:
            logger.warning("ws_feed_stale", age_sec=round(age, 1),
                           msg="no WS message — falling back to REST poll")
            await _rest_fallback_poll()


# ── Connection loop ────────────────────────────────────────────────────────────

async def _connect_once() -> None:
    """One connection lifetime — yields when disconnected."""
    import websockets  # local import to avoid module-load failure if not installed

    async with websockets.connect(
        WS_URL,
        ping_interval=HEARTBEAT_SEC,
        ping_timeout=HEARTBEAT_SEC * 2,
        max_size=None,
    ) as ws:
        logger.info("ws_big_mover_connected", url=WS_URL)
        async for raw in ws:
            try:
                data = json.loads(raw)
                # Combined `!ticker@arr` returns a LIST of ticker dicts
                if isinstance(data, list):
                    _process_tickers(data)
                elif isinstance(data, dict) and "data" in data:
                    # Stream-wrapped form (combined endpoint shape)
                    inner = data["data"]
                    if isinstance(inner, list):
                        _process_tickers(inner)
            except json.JSONDecodeError:
                continue


async def run_ws_big_mover_feed() -> None:
    """Main loop with exponential backoff reconnect + EC3 heartbeat watchdog."""
    global _running, _last_error
    _running = True
    backoff  = RECONNECT_BASE_SEC
    logger.info("ws_big_mover_feed_started")

    # EC3: start watchdog as a sibling task so it survives individual reconnects
    _watchdog = asyncio.create_task(_heartbeat_watchdog())

    try:
        while True:
            try:
                await _connect_once()
                # Clean disconnect — small wait then reconnect
                backoff = RECONNECT_BASE_SEC
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _last_error = str(exc)[:120]
                logger.warning("ws_big_mover_reconnect", error=_last_error, backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_SEC)
    except asyncio.CancelledError:
        _running = False
        _watchdog.cancel()
        try:
            await _watchdog
        except asyncio.CancelledError:
            pass
        logger.info("ws_big_mover_feed_stopped")
        raise
