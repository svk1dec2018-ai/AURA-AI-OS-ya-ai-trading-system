from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.domain.models import NormalizedCandle, OrderRequest, OrderType, Side
from aura.execution.paper import PaperBroker, PaperExecutionConfig


def _candle(
    *,
    minute: int,
    open_price: str,
    high: str,
    low: str,
    close: str,
) -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    return NormalizedCandle(
        symbol="X",
        venue="PAPER",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(1000),
        closed=True,
    )


@pytest.mark.asyncio
async def test_market_order_fills_next_supplied_candle_with_costs() -> None:
    broker = PaperBroker(
        PaperExecutionConfig(fee_bps=Decimal(10), slippage_bps=Decimal(10))
    )
    await broker.connect()
    order = OrderRequest(
        order_id="o-1",
        client_order_id="client-1",
        symbol="X",
        venue="PAPER",
        side=Side.BUY,
        quantity=Decimal(2),
    )
    await broker.submit_order(order)

    fills = await broker.on_candle(
        _candle(minute=1, open_price="100", high="105", low="99", close="104")
    )

    assert len(fills) == 1
    fill = fills[0]
    assert fill.price == Decimal("100.100")
    assert fill.quantity == Decimal(2)
    assert fill.fee == Decimal("0.200200")
    assert broker.open_order_snapshots() == []
    assert broker.position_snapshots()[0].quantity == Decimal(2)


@pytest.mark.asyncio
async def test_duplicate_submit_is_idempotent() -> None:
    broker = PaperBroker()
    await broker.connect()
    order = OrderRequest(
        order_id="o-1",
        client_order_id="client-1",
        symbol="X",
        venue="PAPER",
        side=Side.BUY,
        quantity=Decimal(1),
    )

    first = await broker.submit_order(order)
    second = await broker.submit_order(order)
    assert first == second
    assert len(broker.open_order_snapshots()) == 1


@pytest.mark.asyncio
async def test_cancelled_order_does_not_fill() -> None:
    broker = PaperBroker()
    await broker.connect()
    order = OrderRequest(
        order_id="o-1",
        client_order_id="client-1",
        symbol="X",
        venue="PAPER",
        side=Side.BUY,
        quantity=Decimal(1),
    )
    broker_order_id = await broker.submit_order(order)
    await broker.cancel_order(broker_order_id)

    fills = await broker.on_candle(
        _candle(minute=1, open_price="100", high="105", low="99", close="104")
    )
    assert fills == ()


@pytest.mark.asyncio
async def test_limit_and_stop_use_deterministic_gap_rules() -> None:
    broker = PaperBroker()
    await broker.connect()
    buy_limit = OrderRequest(
        order_id="limit",
        client_order_id="limit-client",
        symbol="X",
        venue="PAPER",
        side=Side.BUY,
        quantity=Decimal(1),
        order_type=OrderType.LIMIT,
        limit_price=Decimal(100),
    )
    buy_stop = OrderRequest(
        order_id="stop",
        client_order_id="stop-client",
        symbol="X",
        venue="PAPER",
        side=Side.BUY,
        quantity=Decimal(1),
        order_type=OrderType.STOP,
        stop_price=Decimal(105),
    )
    await broker.submit_order(buy_limit)
    await broker.submit_order(buy_stop)

    fills = await broker.on_candle(
        _candle(minute=1, open_price="98", high="108", low="97", close="106")
    )
    prices = {fill.order_id: fill.price for fill in fills}
    assert prices == {"limit": Decimal(98), "stop": Decimal(105)}
