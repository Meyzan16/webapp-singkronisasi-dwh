"""WebSocket endpoint for real-time position & price streaming."""

import asyncio
import json
from decimal import Decimal

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.trading.futures_client import FuturesClient
from app.services.trading.position_manager import PositionManager

logger = structlog.get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""

    def default(self, obj: object) -> object:
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class ConnectionManager:
    """Manage active WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("ws_connected", total=len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket."""
        self.active_connections.remove(websocket)
        logger.info("ws_disconnected", total=len(self.active_connections))

    async def broadcast(self, data: dict) -> None:
        """Send data to all connected clients."""
        message = json.dumps(data, cls=DecimalEncoder)
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except WebSocketDisconnect:
                self.disconnect(connection)


manager = ConnectionManager()


async def position_stream(websocket: WebSocket) -> None:
    """Stream real-time position updates every 2 seconds."""

    await manager.connect(websocket)
    settings = get_settings()

    if not settings.binance_api_key:
        await websocket.send_json({"error": "API key not configured"})
        await websocket.close()
        return

    client = FuturesClient(settings)
    pos_manager = PositionManager(client)

    try:
        while True:
            async with AsyncSessionLocal() as session:
                # Update prices for open positions
                positions = await pos_manager.update_prices(session)

                # Get account balance
                try:
                    balance = await client.get_balance()
                    usdt = balance.get("USDT", {})
                    balance_data = {
                        "total_balance": float(usdt.get("total", 0)),
                        "available_balance": float(usdt.get("free", 0)),
                        "margin_used": float(usdt.get("used", 0)),
                    }
                except Exception:
                    balance_data = None

                # Get current prices for all pairs
                prices = {}
                for pair in settings.trading_pairs:
                    try:
                        ticker = await client.get_ticker(pair)
                        prices[pair] = {
                            "price": float(ticker["last"]),
                            "change_24h": float(ticker.get("percentage", 0)),
                        }
                    except Exception:
                        pass

                payload = {
                    "type": "update",
                    "positions": [p.model_dump() for p in positions],
                    "prices": prices,
                    "balance": balance_data,
                    "open_count": len(positions),
                }

                await websocket.send_text(json.dumps(payload, cls=DecimalEncoder))

            await asyncio.sleep(2)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("ws_error", error=str(e))
        manager.disconnect(websocket)
    finally:
        await client.close()
