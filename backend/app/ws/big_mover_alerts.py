"""
G12 — Big Mover Push Notification WebSocket.

Clients connect to /ws/big-movers and receive JSON alerts when a coin
crosses the ±20% threshold. Throttle: 1 alert per coin per hour.
"""
import asyncio
import time

import structlog
from fastapi import WebSocket, WebSocketDisconnect

logger = structlog.get_logger(__name__)

# ── State ──────────────────────────────────────────────────────────────────────

# Connected WebSocket clients
_clients: list[WebSocket] = []

# Throttle: symbol → last broadcast timestamp
_last_notif: dict[str, float] = {}

NOTIF_THROTTLE_SEC  = 3600      # 1 alert per coin per hour
BIG_MOVER_THRESHOLD = 20.0      # abs(change_24h) ≥ 20% triggers alert
HEARTBEAT_SEC       = 30


# ── Public API ─────────────────────────────────────────────────────────────────

async def broadcast_big_mover(
    symbol: str,
    change_24h: float,
    price: float,
    volume_usdt: float = 0.0,
) -> None:
    """
    Broadcast a big mover alert to all connected clients.
    Throttled to once per coin per hour.
    Called by ws_big_mover_feed.py when a new extreme mover is detected.
    """
    if abs(change_24h) < BIG_MOVER_THRESHOLD:
        return
    now = time.time()
    if now - _last_notif.get(symbol, 0) < NOTIF_THROTTLE_SEC:
        return   # throttled — already sent this coin recently

    _last_notif[symbol] = now
    payload = {
        "type":        "big_mover",
        "symbol":      symbol,
        "change_24h":  round(change_24h, 2),
        "price":       price,
        "volume_usdt": round(volume_usdt / 1_000_000, 2),   # in millions
        "ts":          now,
    }
    dead: list[WebSocket] = []
    for ws in list(_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard_safe(ws)   # handled via regular disconnect


def _remove_client(ws: WebSocket) -> None:
    try:
        _clients.remove(ws)
    except ValueError:
        pass


# ── WebSocket handler ──────────────────────────────────────────────────────────

async def big_mover_alert_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint: push big mover alerts to subscribed clients."""
    await websocket.accept()
    _clients.append(websocket)
    logger.info("big_mover_ws_connected", total_clients=len(_clients))

    try:
        # Send recent state snapshot immediately so client knows current movers
        try:
            from agents.futures.ws_big_mover_feed import get_live_movers
            movers = get_live_movers()
            if movers:
                await websocket.send_json({
                    "type":   "snapshot",
                    "movers": [
                        {
                            "symbol":     m.get("symbol"),
                            "change_24h": round(float(m.get("priceChangePercent", 0)), 2),
                            "price":      float(m.get("lastPrice", 0)),
                        }
                        for m in movers
                        if abs(float(m.get("priceChangePercent", 0))) >= BIG_MOVER_THRESHOLD
                    ][:20],
                })
        except Exception:
            pass

        # Heartbeat loop — keep connection alive; alerts are pushed via broadcast_big_mover
        while True:
            await asyncio.sleep(HEARTBEAT_SEC)
            try:
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("big_mover_ws_error", error=str(exc)[:80])
    finally:
        _remove_client(websocket)
        logger.info("big_mover_ws_disconnected", total_clients=len(_clients))
