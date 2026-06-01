from app.schemas.kline import KlineCreate
from app.services.data_pipeline.kline_repository import KlineRepository


async def test_upsert_many_returns_zero_for_empty_input() -> None:
    repository = KlineRepository(session=None)  # type: ignore[arg-type]

    assert await repository.upsert_many([]) == 0


def test_kline_create_requires_ohlcv_fields() -> None:
    kline = KlineCreate(
        pair="BTCUSDT",
        timeframe="1d",
        open_time=1717200000000,
        open="100.1",
        high="110.2",
        low="99.3",
        close="105.4",
        volume="1234.5",
    )

    assert kline.pair == "BTCUSDT"
