from decimal import Decimal

from sqlalchemy import BigInteger, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Kline(Base):
    """OHLCV candle stored per pair, timeframe, and open time."""

    __tablename__ = "klines"
    __table_args__ = (UniqueConstraint("pair", "timeframe", "open_time", name="uq_klines_pair_tf_open"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pair: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close_time: Mapped[int | None] = mapped_column(BigInteger)
    taker_buy_volume: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    number_of_trades: Mapped[int | None] = mapped_column(Integer)
