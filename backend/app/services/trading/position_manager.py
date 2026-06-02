"""Position lifecycle management: open, track, close."""

import time
from decimal import Decimal

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position, Order
from app.schemas.position import PositionCreate, PositionResponse
from app.services.trading.futures_client import FuturesClient

logger = structlog.get_logger(__name__)


class PositionManager:
    """Manages position lifecycle with database persistence."""

    def __init__(self, client: FuturesClient) -> None:
        self._client = client

    async def open_position(
        self,
        session: AsyncSession,
        req: PositionCreate,
    ) -> PositionResponse:
        """Open a new futures position and persist to DB."""

        # Execute on Binance
        order_result = await self._client.open_position(
            pair=req.pair,
            side=req.side,
            quantity=req.quantity,
            leverage=req.leverage,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
        )

        filled_price = Decimal(str(order_result.get("average", order_result.get("price", 0))))
        margin = (filled_price * req.quantity) / req.leverage
        now = int(time.time() * 1000)

        # Save position
        position = Position(
            pair=req.pair,
            side=req.side,
            status="open",
            entry_price=filled_price,
            current_price=filled_price,
            quantity=req.quantity,
            leverage=req.leverage,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            unrealized_pnl=Decimal("0"),
            realized_pnl=None,
            margin=margin,
            opened_at=now,
            signal_id=req.signal_id,
        )
        session.add(position)

        # Save order
        order = Order(
            pair=req.pair,
            side="BUY" if req.side == "LONG" else "SELL",
            order_type="MARKET",
            status="filled",
            price=filled_price,
            quantity=req.quantity,
            filled_price=filled_price,
            filled_quantity=req.quantity,
            binance_order_id=str(order_result.get("id", "")),
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()
        await session.refresh(position)

        # Link order to position
        order.position_id = position.id
        await session.commit()

        logger.info(
            "position_opened",
            position_id=position.id,
            pair=req.pair,
            side=req.side,
            entry_price=str(filled_price),
        )
        return PositionResponse.model_validate(position)

    async def close_position(
        self,
        session: AsyncSession,
        position_id: int,
        reason: str = "manual",
    ) -> PositionResponse:
        """Close an open position."""

        result = await session.execute(
            select(Position).where(Position.id == position_id, Position.status == "open")
        )
        position = result.scalar_one_or_none()
        if position is None:
            raise ValueError(f"Open position {position_id} not found")

        # Execute close on Binance
        order_result = await self._client.close_position(
            pair=position.pair,
            side=position.side,
            quantity=position.quantity,
        )

        close_price = Decimal(str(order_result.get("average", order_result.get("price", 0))))
        now = int(time.time() * 1000)

        # Calculate realized PnL
        if position.side == "LONG":
            realized_pnl = (close_price - position.entry_price) * position.quantity * position.leverage
        else:
            realized_pnl = (position.entry_price - close_price) * position.quantity * position.leverage

        position.status = "closed"
        position.current_price = close_price
        position.realized_pnl = realized_pnl
        position.unrealized_pnl = Decimal("0")
        position.closed_at = now
        position.close_reason = reason

        # Save close order
        order = Order(
            position_id=position.id,
            pair=position.pair,
            side="SELL" if position.side == "LONG" else "BUY",
            order_type="MARKET",
            status="filled",
            price=close_price,
            quantity=position.quantity,
            filled_price=close_price,
            filled_quantity=position.quantity,
            binance_order_id=str(order_result.get("id", "")),
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()
        await session.refresh(position)

        logger.info(
            "position_closed",
            position_id=position.id,
            pair=position.pair,
            realized_pnl=str(realized_pnl),
            reason=reason,
        )
        return PositionResponse.model_validate(position)

    async def get_open_positions(self, session: AsyncSession) -> list[PositionResponse]:
        """Get all open positions from DB."""

        result = await session.execute(
            select(Position).where(Position.status == "open").order_by(Position.opened_at.desc())
        )
        positions = result.scalars().all()
        return [PositionResponse.model_validate(p) for p in positions]

    async def get_all_positions(self, session: AsyncSession) -> list[PositionResponse]:
        """Get all positions (open + closed)."""

        result = await session.execute(
            select(Position).order_by(Position.opened_at.desc()).limit(50)
        )
        positions = result.scalars().all()
        return [PositionResponse.model_validate(p) for p in positions]

    async def update_prices(self, session: AsyncSession) -> list[PositionResponse]:
        """Update current prices and PnL for all open positions."""

        result = await session.execute(
            select(Position).where(Position.status == "open")
        )
        positions = result.scalars().all()
        updated: list[PositionResponse] = []

        for position in positions:
            try:
                ticker = await self._client.get_ticker(position.pair)
                current_price = Decimal(str(ticker["last"]))
                position.current_price = current_price

                if position.side == "LONG":
                    position.unrealized_pnl = (
                        (current_price - position.entry_price) * position.quantity * position.leverage
                    )
                else:
                    position.unrealized_pnl = (
                        (position.entry_price - current_price) * position.quantity * position.leverage
                    )

                updated.append(PositionResponse.model_validate(position))
            except Exception as e:
                logger.error("price_update_failed", pair=position.pair, error=str(e))

        await session.commit()
        return updated
