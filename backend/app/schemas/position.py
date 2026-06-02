from decimal import Decimal

from pydantic import BaseModel


class PositionCreate(BaseModel):
    """Request to open a new futures position."""

    pair: str
    side: str  # LONG or SHORT
    leverage: int = 5
    quantity: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    signal_id: int | None = None


class PositionResponse(BaseModel):
    """Single position response."""

    id: int
    pair: str
    side: str
    status: str
    entry_price: Decimal
    current_price: Decimal | None
    quantity: Decimal
    leverage: int
    stop_loss: Decimal | None
    take_profit: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal | None
    margin: Decimal | None
    opened_at: int
    closed_at: int | None
    close_reason: str | None
    pnl_percent: float | None = None

    model_config = {"from_attributes": True}


class PositionClose(BaseModel):
    """Request to close a position."""

    reason: str = "manual"  # manual, tp, sl


class PositionListResponse(BaseModel):
    """List of positions."""

    positions: list[PositionResponse]
    total: int


class OrderCreate(BaseModel):
    """Request to place an order."""

    pair: str
    side: str  # BUY or SELL
    order_type: str = "MARKET"  # MARKET, LIMIT, STOP_MARKET
    quantity: Decimal
    price: Decimal | None = None


class OrderResponse(BaseModel):
    """Single order response."""

    id: int
    position_id: int | None
    pair: str
    side: str
    order_type: str
    status: str
    price: Decimal | None
    quantity: Decimal
    filled_price: Decimal | None
    filled_quantity: Decimal | None
    binance_order_id: str | None
    created_at: int
    updated_at: int | None

    model_config = {"from_attributes": True}


class AccountBalance(BaseModel):
    """Futures account balance summary."""

    total_balance: Decimal
    available_balance: Decimal
    unrealized_pnl: Decimal
    margin_used: Decimal
