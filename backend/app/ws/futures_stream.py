"""WebSocket endpoint — real-time Futures Scanner streaming."""
import asyncio
import time
from typing import Optional

import structlog
from fastapi import WebSocket, WebSocketDisconnect

logger = structlog.get_logger(__name__)

HEARTBEAT_SEC = 5
INTERVAL_SEC  = 15 * 60


def _next_scan_in(last_ts: Optional[float]) -> Optional[int]:
    if last_ts is None:
        return None
    return max(0, int(INTERVAL_SEC - (time.time() - last_ts)))


async def futures_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("futures_ws_connected")

    from agents.futures import store as fs

    queue = fs.subscribe()
    try:
        # Send current cached data on connect
        cached = fs.get_all_results()
        if cached:
            await websocket.send_json({
                "type":     "snapshot",
                "agent1":   cached.get("agent1", {}),
                "agent2":   cached.get("agent2", {}),
                "next_scan_in": _next_scan_in(
                    max((fs.last_scan_ts(a) or 0) for a in ["agent1", "agent2"]) or None
                ),
            })
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
                    # Re-bundle both agents' latest data on any snapshot update
                    all_data = fs.get_all_results()
                    await websocket.send_json({
                        "type":     "snapshot",
                        "agent1":   all_data.get("agent1", {}),
                        "agent2":   all_data.get("agent2", {}),
                        "next_scan_in": _next_scan_in(
                            max((fs.last_scan_ts(a) or 0) for a in ["agent1", "agent2"]) or None
                        ),
                    })
                else:
                    await websocket.send_json(msg)

            except asyncio.TimeoutError:
                await websocket.send_json({
                    "type":     "heartbeat",
                    "scanning": fs.is_scanning(),
                    "next_scan_in": _next_scan_in(
                        max((fs.last_scan_ts(a) or 0) for a in ["agent1", "agent2"]) or None
                    ),
                    "ts": time.time(),
                })

    except WebSocketDisconnect:
        logger.info("futures_ws_disconnected")
    except Exception as exc:
        logger.error("futures_ws_error", error=str(exc))
    finally:
        fs.unsubscribe(queue)
