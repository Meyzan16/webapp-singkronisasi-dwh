"""WebSocket endpoint — real-time Futures Scanner streaming."""
import asyncio
import time
from typing import Optional

import structlog
from fastapi import WebSocket, WebSocketDisconnect

logger = structlog.get_logger(__name__)

HEARTBEAT_SEC = 5
# F29: single source of truth — import instead of duplicating the value
from agents.futures.scheduler import INTERVAL_SEC

# BUG-L20: all lanes streamed (agent3 was dropped → momentum wiped from the live UI each tick)
_WS_AGENTS = ["agent1", "agent2", "agent3"]


def _next_scan_in(last_ts: Optional[float]) -> Optional[int]:
    if last_ts is None:
        return None
    return max(0, int(INTERVAL_SEC - (time.time() - last_ts)))


def _build_snapshot(fs) -> dict:
    """BUG-L20: bundle ALL lanes (agent1/2/3) into one snapshot payload."""
    data = fs.get_all_results()
    last_ts = max((fs.last_scan_ts(a) or 0) for a in _WS_AGENTS) or None
    return {
        "type": "snapshot",
        **{a: data.get(a, {}) for a in _WS_AGENTS},
        "next_scan_in": _next_scan_in(last_ts),
    }


async def futures_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("futures_ws_connected")

    from agents.futures import store as fs

    queue = fs.subscribe()
    try:
        # Send current cached data on connect
        if fs.get_all_results():
            await websocket.send_json(_build_snapshot(fs))
        else:
            await websocket.send_json({
                "type":     "status",
                "scanning": fs.is_scanning(),
                "has_data": False,
            })

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SEC)

                if msg["type"] == "snapshot":
                    # Re-bundle ALL lanes' latest data on any snapshot update (BUG-L20)
                    await websocket.send_json(_build_snapshot(fs))
                else:
                    await websocket.send_json(msg)

            except asyncio.TimeoutError:
                last_ts = max((fs.last_scan_ts(a) or 0) for a in _WS_AGENTS) or None
                await websocket.send_json({
                    "type":     "heartbeat",
                    "scanning": fs.is_scanning(),
                    "next_scan_in": _next_scan_in(last_ts),
                    "ts": time.time(),
                })

    except WebSocketDisconnect:
        logger.info("futures_ws_disconnected")
    except Exception as exc:
        logger.error("futures_ws_error", error=str(exc))
    finally:
        fs.unsubscribe(queue)
