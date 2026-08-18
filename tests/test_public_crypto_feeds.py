from datetime import UTC, datetime
from decimal import Decimal

from aura.data.public_crypto_feeds import (
    parse_bybit_ticker,
    parse_coinbase_ticker,
    parse_okx_ticker,
)


def test_coinbase_public_ticker_normalizes_without_auth() -> None:
    received = datetime(2026, 8, 18, 5, 0, 1, tzinfo=UTC)
    quotes = parse_coinbase_ticker(
        {
            "channel": "ticker",
            "timestamp": "2026-08-18T05:00:00.500000Z",
            "events": [
                {
                    "tickers": [
                        {
                            "product_id": "BTC-USD",
                            "price": "60000.1",
                            "best_bid": "60000.0",
                            "best_ask": "60000.2",
                        }
                    ]
                }
            ],
        },
        received_at=received,
    )
    assert len(quotes) == 1
    assert quotes[0].provider == "COINBASE_PUBLIC"
    assert quotes[0].symbol == "BTC-USD"
    assert quotes[0].last == Decimal("60000.1")


def test_bybit_public_ticker_normalizes_without_auth() -> None:
    received = datetime(2026, 8, 18, 5, 0, 1, tzinfo=UTC)
    quotes = parse_bybit_ticker(
        {
            "topic": "tickers.BTCUSDT",
            "type": "snapshot",
            "ts": 1787029200500,
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "60000.1",
                "bid1Price": "60000.0",
                "ask1Price": "60000.2",
            },
        },
        received_at=received,
    )
    assert len(quotes) == 1
    assert quotes[0].provider == "BYBIT_PUBLIC"
    assert quotes[0].symbol == "BTCUSDT"
    assert quotes[0].ask == Decimal("60000.2")


def test_okx_public_ticker_normalizes_without_auth() -> None:
    received = datetime(2026, 8, 18, 5, 0, 1, tzinfo=UTC)
    quotes = parse_okx_ticker(
        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT"},
            "data": [
                {
                    "instId": "BTC-USDT",
                    "last": "60000.1",
                    "bidPx": "60000.0",
                    "askPx": "60000.2",
                    "ts": "1787029200500",
                }
            ],
        },
        received_at=received,
    )
    assert len(quotes) == 1
    assert quotes[0].provider == "OKX_PUBLIC"
    assert quotes[0].symbol == "BTC-USDT"
    assert quotes[0].bid == Decimal("60000.0")


def test_future_provider_timestamp_is_rejected() -> None:
    received = datetime(2026, 8, 18, 5, 0, 0, tzinfo=UTC)
    quotes = parse_coinbase_ticker(
        {
            "channel": "ticker",
            "timestamp": "2026-08-18T05:00:00.500000Z",
            "events": [
                {
                    "tickers": [
                        {
                            "product_id": "BTC-USD",
                            "price": "60000.1",
                        }
                    ]
                }
            ],
        },
        received_at=received,
    )
    assert quotes == ()
