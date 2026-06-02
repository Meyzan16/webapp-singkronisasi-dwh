from decimal import Decimal

from sqlalchemy import BigInteger, Integer, Numeric, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Position(Base):
    """Tracks open and closed futures positions."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pair: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(5), nullable=False)  # LONG or SHORT
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open", index=True)  # open, closed, liquidated
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    margin: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    opened_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closed_at: Mapped[int | None] = mapped_column(BigInteger)
    signal_id: Mapped[int | None] = mapped_column(Integer)  # Reference to the signal that triggered this
    close_reason: Mapped[str | None] = mapped_column(String(20))  # tp, sl, manual, liquidated


class Order(Base):
    """Individual orders placed on Binance Futures."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, index=True)
    pair: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(5), nullable=False)  # BUY or SELL
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)  # MARKET, LIMIT, STOP_MARKET
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="pending")  # pending, filled, cancelled, failed
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    filled_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    binance_order_id: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int | None] = mapped_column(BigInteger)
