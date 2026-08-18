from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from aura.data.public_history import (
    BybitSpotHistoryClient,
    CoinbaseExchangeHistoryClient,
    HistoricalCandleArchive,
    PublicHistoryError,
)
from aura.domain.models import NormalizedCandle


@pytest.mark.asyncio
async def test_coinbase_history_normalizes_sorts_and_excludes_open_bucket() -> None:
    captured: list[str] = []

    def transport(url: str):
        captured.append(url)
        return [
            [120, "99", "103", "100", "102", "4"],
            [0, "98", "101", "99", "100", "2"],
            [180, "101", "104", "102", "103", "3"],
        ]

    end = datetime(1970, 1, 1, 0, 3, tzinfo=UTC)
    candles = await CoinbaseExchangeHistoryClient(transport).fetch_candles(
        symbol="btc-usd",
        timeframe="1m",
        limit=3,
        end=end,
    )

    assert [item.open_time.timestamp() for item in candles] == [0, 120]
    assert candles[-1].close == Decimal(102)
    assert candles[-1].venue == "COINBASE_PUBLIC"
    query = parse_qs(urlparse(captured[0]).query)
    assert query["granularity"] == ["60"]


@pytest.mark.asyncio
async def test_bybit_history_normalizes_reverse_sorted_rows() -> None:
    def transport(url: str):
        assert "category=spot" in url
        assert "symbol=BTCUSDT" in url
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    ["60000", "100", "103", "99", "102", "4", "400"],
                    ["0", "99", "101", "98", "100", "2", "200"],
                ]
            },
        }

    candles = await BybitSpotHistoryClient(transport).fetch_candles(
        symbol="BTCUSDT",
        timeframe="1m",
        limit=2,
        end=datetime(1970, 1, 1, 0, 2, tzinfo=UTC),
    )

    assert [item.open_time.timestamp() for item in candles] == [0, 60]
    assert candles[1].high == Decimal(103)
    assert candles[1].venue == "BYBIT_PUBLIC"


@pytest.mark.asyncio
async def test_bybit_provider_error_is_failure_not_fake_data() -> None:
    client = BybitSpotHistoryClient(
        lambda _url: {"retCode": 10001, "retMsg": "invalid symbol"}
    )
    with pytest.raises(PublicHistoryError, match="invalid symbol"):
        await client.fetch_candles(
            symbol="NOPE",
            timeframe="1m",
            limit=2,
            end=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_historical_archive_merges_atomically_and_deduplicates(tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def candle(offset: int, close: str) -> NormalizedCandle:
        opened = start + timedelta(minutes=offset)
        parsed = Decimal(close)
        return NormalizedCandle(
            symbol="BTC-USD",
            venue="COINBASE_PUBLIC",
            timeframe="1m",
            open_time=opened,
            close_time=opened + timedelta(minutes=1),
            open=parsed,
            high=parsed,
            low=parsed,
            close=parsed,
            volume=Decimal(1),
        )

    archive = HistoricalCandleArchive(tmp_path)
    assert archive.merge((candle(0, "100"), candle(1, "101"))) == 2
    assert archive.merge((candle(1, "102"), candle(2, "103"))) == 1

    stored = archive.read(symbol="BTC-USD", timeframe="1m")
    assert [item.close for item in stored] == [Decimal(100), Decimal(102), Decimal(103)]
    assert not archive.path_for(symbol="BTC-USD", timeframe="1m").with_suffix(".tmp").exists()
