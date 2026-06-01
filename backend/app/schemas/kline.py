from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class KlineBase(BaseModel):
    """Shared kline fields."""

    pair: str = Field(..., examples=["BTCUSDT"])
    timeframe: str = Field(..., examples=["1d"])
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: int | None = None
    taker_buy_volume: Decimal | None = None
    number_of_trades: int | None = None


class KlineCreate(KlineBase):
    """Payload used to insert or update a kline."""


class KlineRead(KlineBase):
    """Kline response returned by the REST API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
