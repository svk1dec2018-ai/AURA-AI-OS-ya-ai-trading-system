from urllib.parse import parse_qs, urlparse

import pytest

from aura.data.dhan_transport import (
    DhanCredentials,
    DhanFeedMode,
    DhanInstrumentSubscription,
    DhanMarketFeedConfig,
)


def test_websocket_url_contains_runtime_credentials_and_v2_auth_parameters() -> None:
    url = DhanMarketFeedConfig.websocket_url(
        DhanCredentials(client_id="1000000001", access_token="secret-token")
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "wss"
    assert parsed.netloc == "api-feed.dhan.co"
    assert query["version"] == ["2"]
    assert query["token"] == ["secret-token"]
    assert query["clientId"] == ["1000000001"]
    assert query["authType"] == ["2"]


def test_subscription_batches_at_official_100_instrument_message_limit() -> None:
    instruments = tuple(
        DhanInstrumentSubscription(exchange_segment="NSE_EQ", security_id=str(index))
        for index in range(205)
    )
    messages = DhanMarketFeedConfig.subscription_messages(instruments, mode=DhanFeedMode.FULL)
    assert [message["InstrumentCount"] for message in messages] == [100, 100, 5]
    assert all(message["RequestCode"] == 21 for message in messages)


def test_more_than_connection_capacity_is_rejected() -> None:
    instruments = tuple(
        DhanInstrumentSubscription(exchange_segment="NSE_EQ", security_id=str(index))
        for index in range(5001)
    )
    with pytest.raises(ValueError, match="at most 5000"):
        DhanMarketFeedConfig.subscription_messages(instruments)


def test_disconnect_message_uses_documented_request_code() -> None:
    assert DhanMarketFeedConfig.disconnect_message() == {"RequestCode": 12}
