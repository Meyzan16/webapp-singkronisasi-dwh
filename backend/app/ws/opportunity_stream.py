"""WebSocket endpoint for real-time opportunity scanner streaming."""
import asyncio
import time
from typing import Optional

import structlog
from fastapi import WebSocket, WebSocketDisconnect

logger = structlog.get_logger(__name__)

HEARTBEAT_SEC = 5
INTERVAL_SEC  = 3 * 60   # must match agents/opportunity/scheduler.py INTERVAL_SEC


def _next_scan_in(last_ts: Optional[float]) -> Optional[int]:
    if last_ts is None:
        return None
    return max(0, int(INTERVAL_SEC - (time.time() - last_ts)))


async def opportunity_stream(websocket: WebSocket) -> None:
    """Push opportunity scan results to clients in real-time."""
    await websocket.accept()
    logger.info("opportunity_ws_connected")

    from agents.opportunity import store as opp_store

    queue = opp_store.subscribe()
    try:
        # Send current data immediately so the client doesn't wait up to 15 min
        cached = opp_store.get_result()
        if cached:
            await websocket.send_json({
                "type": "snapshot",
                **cached,
                "next_scan_in": _next_scan_in(opp_store.last_scan_ts()),
            })
        else:
            await websocket.send_json({
                "type": "status",
                "scanning": opp_store.is_scanning(),
                "has_data": False,
            })

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SEC)

                if msg["type"] == "snapshot":
                    await websocket.send_json({
                        **msg,
                        "next_scan_in": _next_scan_in(opp_store.last_scan_ts()),
                    })
                else:
                    # "scanning" state change
                    await websocket.send_json(msg)

            except asyncio.TimeoutError:
                await websocket.send_json({
                    "type": "heartbeat",
                    "scanning": opp_store.is_scanning(),
                    "next_scan_in": _next_scan_in(opp_store.last_scan_ts()),
                    "ts": time.time(),
                })

    except WebSocketDisconnect:
        logger.info("opportunity_ws_disconnected")
    except Exception as exc:
        logger.error("opportunity_ws_error", error=str(exc))
    finally:
        opp_store.unsubscribe(queue)
