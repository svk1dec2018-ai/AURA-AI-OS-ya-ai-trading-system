from __future__ import annotations

from decimal import Decimal

import pytest

from aura.domain.models import OrderRequest, OrderStatus, OrderType, Side, TimeInForce
from aura.execution.angel_one import (
    AngelOneReadOnlyBroker,
    AngelOneRoute,
    AngelOneSessionCredentials,
    load_angel_one_session_from_env,
)
from aura.execution.demo_guard import LiveTradingDisabledError


class FakeSmartApi:
    def __init__(self) -> None:
        self.profile = {"status": True, "data": {"clientcode": "A123"}}
        self.order_book = {"status": True, "data": []}
        self.trade_book = {"status": True, "data": []}
        self.positions = {"status": True, "data": []}
        self.ltp = {"status": True, "data": {"ltp": "2450.25"}}
        self.profile_refresh_token = None
        self.ltp_args = None

    def getProfile(self, refresh_token):
        self.profile_refresh_token = refresh_token
        return self.profile

    def orderBook(self):
        return self.order_book

    def tradeBook(self):
        return self.trade_book

    def position(self):
        return self.positions

    def ltpData(self, exchange, trading_symbol, symbol_token):
        self.ltp_args = (exchange, trading_symbol, symbol_token)
        return self.ltp


def credentials() -> AngelOneSessionCredentials:
    return AngelOneSessionCredentials(
        api_key="api-secret",
        client_code="A123",
        jwt_token="jwt-secret",
        refresh_token="refresh-secret",
        feed_token="feed-secret",
    )


def routes() -> dict[str, AngelOneRoute]:
    return {
        "RELIANCE": AngelOneRoute(
            symbol_token="2885",
            trading_symbol="RELIANCE-EQ",
            exchange="NSE",
            product_type="INTRADAY",
        )
    }


def order(**updates) -> OrderRequest:
    values = {
        "order_id": "aura-order-1",
        "client_order_id": "client-order-123456789012345",
        "symbol": "RELIANCE",
        "venue": "ANGEL_ONE_SMARTAPI",
        "side": Side.BUY,
        "quantity": Decimal(2),
    }
    values.update(updates)
    return OrderRequest(**values)


def test_session_loader_is_explicit_and_secret_repr_is_redacted(monkeypatch) -> None:
    for name in (
        "AURA_ANGEL_ONE_API_KEY",
        "AURA_ANGEL_ONE_CLIENT_CODE",
        "AURA_ANGEL_ONE_JWT_TOKEN",
        "AURA_ANGEL_ONE_REFRESH_TOKEN",
        "AURA_ANGEL_ONE_FEED_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="AURA_ANGEL_ONE_API_KEY"):
        load_angel_one_session_from_env()

    monkeypatch.setenv("AURA_ANGEL_ONE_API_KEY", "api-secret")
    monkeypatch.setenv("AURA_ANGEL_ONE_CLIENT_CODE", "A123")
    monkeypatch.setenv("AURA_ANGEL_ONE_JWT_TOKEN", "jwt-secret")
    monkeypatch.setenv("AURA_ANGEL_ONE_REFRESH_TOKEN", "refresh-secret")
    loaded = load_angel_one_session_from_env()
    assert loaded.client_code == "A123"
    assert "api-secret" not in repr(loaded)
    assert "jwt-secret" not in repr(loaded)
    assert "refresh-secret" not in repr(loaded)


@pytest.mark.asyncio
async def test_connect_verifies_profile_identity_and_quote() -> None:
    client = FakeSmartApi()
    broker = AngelOneReadOnlyBroker(client, credentials(), routes())
    await broker.connect()
    assert client.profile_refresh_token == "refresh-secret"
    assert await broker.ltp("RELIANCE") == Decimal("2450.25")
    assert client.ltp_args == ("NSE", "RELIANCE-EQ", "2885")
    await broker.disconnect()

    mismatch = FakeSmartApi()
    mismatch.profile["data"]["clientcode"] = "OTHER"
    with pytest.raises(RuntimeError, match="session client mismatch"):
        await AngelOneReadOnlyBroker(mismatch, credentials(), routes()).connect()


def test_order_payload_translation_is_deterministic() -> None:
    broker = AngelOneReadOnlyBroker(FakeSmartApi(), credentials(), routes())
    market = broker.prepare_order_payload(order(time_in_force=TimeInForce.IOC))
    assert market == {
        "variety": "NORMAL",
        "tradingsymbol": "RELIANCE-EQ",
        "symboltoken": "2885",
        "transactiontype": "BUY",
        "exchange": "NSE",
        "ordertype": "MARKET",
        "producttype": "INTRADAY",
        "duration": "IOC",
        "price": "0",
        "triggerprice": "0",
        "squareoff": "0",
        "stoploss": "0",
        "quantity": "2",
        "ordertag": "client-order-123456",
    }

    limit = broker.prepare_order_payload(
        order(order_type=OrderType.LIMIT, limit_price=Decimal("2450.50"))
    )
    assert limit["ordertype"] == "LIMIT"
    assert limit["price"] == "2450.50"
    stop = broker.prepare_order_payload(
        order(order_type=OrderType.STOP, stop_price=Decimal(2400))
    )
    assert stop["ordertype"] == "STOPLOSS_MARKET"
    assert stop["triggerprice"] == "2400"


def test_order_payload_rejects_wrong_venue_route_and_fractional_quantity() -> None:
    broker = AngelOneReadOnlyBroker(FakeSmartApi(), credentials(), routes())
    with pytest.raises(ValueError, match="venue is not Angel One"):
        broker.prepare_order_payload(order(venue="DHAN"))
    with pytest.raises(KeyError, match="missing Angel One route"):
        broker.prepare_order_payload(order(symbol="NIFTY"))
    with pytest.raises(ValueError, match="integer"):
        broker.prepare_order_payload(order(quantity=Decimal("1.5")))


@pytest.mark.asyncio
async def test_execution_and_cancellation_are_unconditionally_locked() -> None:
    broker = AngelOneReadOnlyBroker(FakeSmartApi(), credentials(), routes())
    await broker.connect()
    with pytest.raises(LiveTradingDisabledError, match="order submission is locked"):
        await broker.submit_order(order())
    with pytest.raises(LiveTradingDisabledError, match="cancellation is locked"):
        await broker.cancel_order("broker-1")


@pytest.mark.asyncio
async def test_reconciliation_snapshots_preserve_external_divergence() -> None:
    client = FakeSmartApi()
    client.order_book = {
        "status": True,
        "data": [
            {
                "orderid": "broker-1",
                "tradingsymbol": "RELIANCE-EQ",
                "exchange": "NSE",
                "transactiontype": "BUY",
                "quantity": "2",
                "filledshares": "1",
                "orderstatus": "partially filled",
            },
            {
                "orderid": "external-2",
                "tradingsymbol": "SBIN-EQ",
                "exchange": "NSE",
                "transactiontype": "SELL",
                "quantity": "1",
                "filledshares": "0",
                "orderstatus": "open",
            },
            {
                "orderid": "done-3",
                "tradingsymbol": "RELIANCE-EQ",
                "exchange": "NSE",
                "transactiontype": "BUY",
                "quantity": "2",
                "filledshares": "2",
                "orderstatus": "complete",
            },
        ],
    }
    client.positions = {
        "status": True,
        "data": [
            {
                "tradingsymbol": "RELIANCE-EQ",
                "exchange": "NSE",
                "netqty": "2",
            },
            {
                "tradingsymbol": "SBIN-EQ",
                "exchange": "NSE",
                "netqty": "-1",
            },
        ],
    }
    broker = AngelOneReadOnlyBroker(
        client,
        credentials(),
        routes(),
        recovered_orders={"broker-1": order()},
    )
    await broker.connect()
    snapshots = broker.open_order_snapshots()
    assert len(snapshots) == 2
    assert snapshots[0].client_order_id == order().client_order_id
    assert snapshots[0].status == OrderStatus.PARTIALLY_FILLED
    assert snapshots[0].filled_quantity == Decimal(1)
    assert snapshots[1].client_order_id == "external-angel-one:external-2"
    positions = broker.position_snapshots()
    assert positions[0].symbol == "RELIANCE"
    assert positions[0].quantity == Decimal(2)
    assert positions[1].symbol == "external-angel-one:NSE:SBIN-EQ"
    assert positions[1].quantity == Decimal(-1)


@pytest.mark.asyncio
async def test_trade_fills_are_normalized_and_deduplicated() -> None:
    client = FakeSmartApi()
    client.trade_book = {
        "status": True,
        "data": [
            {
                "tradeid": "trade-1",
                "orderid": "broker-1",
                "transactiontype": "BUY",
                "fillsize": "2",
                "fillprice": "2450.25",
                "filltime": "19-Aug-2026 15:20:01",
            }
        ],
    }
    broker = AngelOneReadOnlyBroker(
        client,
        credentials(),
        routes(),
        recovered_orders={"broker-1": order()},
        poll_interval_seconds=0.001,
    )
    await broker.connect()
    stream = broker.fills()
    fill = await anext(stream)
    assert fill.fill_id == "angel-one:trade-1"
    assert fill.order_id == "aura-order-1"
    assert fill.quantity == Decimal(2)
    assert fill.price == Decimal("2450.25")
    assert fill.timestamp.utcoffset() is not None
    await stream.aclose()


@pytest.mark.asyncio
async def test_response_failure_and_mapping_conflict_fail_closed() -> None:
    client = FakeSmartApi()
    client.order_book = {"status": False, "message": "Token invalid", "errorcode": "AG8001"}
    broker = AngelOneReadOnlyBroker(client, credentials(), routes())
    await broker.connect()
    with pytest.raises(RuntimeError, match="Token invalid.*AG8001"):
        broker.open_order_snapshots()
    first = order()
    assert broker.register_recovered_order("broker-1", first)
    assert not broker.register_recovered_order("broker-1", first)
    with pytest.raises(RuntimeError, match="mapping conflict"):
        broker.register_recovered_order(
            "broker-1",
            order(order_id="different-order"),
        )


@pytest.mark.asyncio
async def test_broker_overfill_is_never_silently_clamped() -> None:
    client = FakeSmartApi()
    client.order_book = {
        "status": True,
        "data": [
            {
                "orderid": "broker-1",
                "tradingsymbol": "RELIANCE-EQ",
                "exchange": "NSE",
                "transactiontype": "BUY",
                "quantity": "2",
                "filledshares": "3",
                "orderstatus": "partially filled",
            }
        ],
    }
    broker = AngelOneReadOnlyBroker(client, credentials(), routes())
    await broker.connect()
    with pytest.raises(RuntimeError, match="invalid filled quantity"):
        broker.open_order_snapshots()
