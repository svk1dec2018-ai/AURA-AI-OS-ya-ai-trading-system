from decimal import Decimal

import pytest

from aura.domain.models import Fill, OrderRequest, OrderStatus, Side
from aura.execution.state import OrderState, OverfillError


def test_partial_fill_is_idempotent_and_computes_vwap() -> None:
    request = OrderRequest(symbol="BTC/USD", venue="TEST", side=Side.BUY, quantity=Decimal(2))
    state = OrderState(request)
    state.submit()

    first = Fill(
        fill_id="f1",
        order_id=request.order_id,
        symbol=request.symbol,
        side=Side.BUY,
        quantity=Decimal("0.5"),
        price=Decimal(100),
    )
    second = Fill(
        fill_id="f2",
        order_id=request.order_id,
        symbol=request.symbol,
        side=Side.BUY,
        quantity=Decimal("1.5"),
        price=Decimal(110),
    )

    assert state.apply_fill(first) is True
    assert state.status == OrderStatus.PARTIALLY_FILLED
    assert state.apply_fill(first) is False
    assert state.apply_fill(second) is True
    assert state.status == OrderStatus.FILLED
    assert state.average_fill_price == Decimal("107.5")


def test_overfill_is_rejected() -> None:
    request = OrderRequest(symbol="BTC/USD", venue="TEST", side=Side.BUY, quantity=Decimal(1))
    state = OrderState(request)
    state.submit()
    fill = Fill(
        fill_id="too-much",
        order_id=request.order_id,
        symbol=request.symbol,
        side=Side.BUY,
        quantity=Decimal("1.1"),
        price=Decimal(100),
    )
    with pytest.raises(OverfillError):
        state.apply_fill(fill)
