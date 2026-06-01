from decimal import Decimal

from app.services.data_pipeline.kline_fetcher import KlineFetcher


def test_ccxt_ohlcv_row_maps_to_kline_schema() -> None:
    raw = [
        1717200000000,
        "100.1",
        "110.2",
        "99.3",
        "105.4",
        "1234.5",
        1717286399999,
        "129999.1",
        456,
        "789.1",
    ]

    kline = KlineFetcher._to_schema("btcusdt", "1d", raw)

    assert kline.pair == "BTCUSDT"
    assert kline.timeframe == "1d"
    assert kline.open_time == 1717200000000
    assert kline.close == Decimal("105.4")
    assert kline.volume == Decimal("1234.5")
    assert kline.close_time == 1717286399999
    assert kline.number_of_trades == 456
    assert kline.taker_buy_volume == Decimal("789.1")
