import pytest

from aura.data.binance_transport import BinanceStreamConfig, BinanceStreamEnvironment


def test_testnet_raw_stream_uses_current_official_endpoint_and_lowercase_symbol() -> None:
    config = BinanceStreamConfig(BinanceStreamEnvironment.TESTNET)
    assert (
        config.raw_stream_url("BTCUSDT@trade")
        == "wss://stream.testnet.binance.vision/ws/btcusdt@trade"
    )


def test_production_combined_stream_builds_multiple_streams() -> None:
    config = BinanceStreamConfig(BinanceStreamEnvironment.PRODUCTION)
    url = config.combined_stream_url(("BTCUSDT@trade", "BTCUSDT@depth@100ms"))
    assert url.startswith("wss://stream.binance.com:9443/stream?streams=")
    assert "btcusdt@trade/btcusdt@depth@100ms" in url


def test_market_data_only_endpoint_is_supported() -> None:
    config = BinanceStreamConfig(BinanceStreamEnvironment.MARKET_DATA_ONLY)
    assert config.raw_stream_url("ETHUSDT@bookTicker") == (
        "wss://data-stream.binance.vision/ws/ethusdt@bookticker"
    )


def test_subscription_messages_are_normalized_and_have_id() -> None:
    message = BinanceStreamConfig.subscription_message(
        ("BTCUSDT@aggTrade", "ETHUSDT@kline_1m"),
        request_id=42,
    )
    assert message == {
        "method": "SUBSCRIBE",
        "params": ["btcusdt@aggtrade", "ethusdt@kline_1m"],
        "id": 42,
    }


def test_unsafe_stream_delimiters_are_rejected() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        BinanceStreamConfig().raw_stream_url("btcusdt@trade/evil")
