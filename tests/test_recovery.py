from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from aura.domain.models import Fill, OrderRequest, OrderStatus, Side
from aura.persistence.recovery import FinancialEventJournal, RecoveryError, recover_financial_state
from aura.persistence.wal import JsonlWriteAheadLog


def test_recovery_rebuilds_orders_portfolio_and_kill_switch(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    order = OrderRequest(
        order_id="o-1",
        client_order_id="c-o-1",
        symbol="BTC-USD",
        venue="TEST",
        side=Side.BUY,
        quantity=Decimal(2),
    )
    journal.record_order_created(order, correlation_id="decision-1")
    journal.record_order_submitted(order.order_id, correlation_id="decision-1")
    journal.record_fill(
        Fill(
            fill_id="f-1",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=Decimal("0.5"),
            price=Decimal(100),
            fee=Decimal(1),
        ),
        correlation_id="decision-1",
    )
    journal.record_fill(
        Fill(
            fill_id="f-2",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=Decimal("1.5"),
            price=Decimal(110),
            fee=Decimal(1),
        ),
        correlation_id="decision-1",
    )
    journal.record_kill_switch_engaged("operator emergency", correlation_id="risk-1")

    reopened = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    recovered = recover_financial_state(reopened, starting_cash=Decimal(1000))

    state = recovered.orders[order.order_id]
    assert state.status == OrderStatus.FILLED
    assert state.filled_quantity == Decimal(2)
    assert state.average_fill_price == Decimal("107.5")
    assert recovered.ledger.positions[order.symbol].quantity == Decimal(2)
    assert recovered.ledger.positions[order.symbol].average_price == Decimal("107.5")
    assert recovered.ledger.cash == Decimal(783)
    assert recovered.kill_switch
    assert recovered.kill_switch_reason == "operator emergency"
    assert recovered.unique_fills_applied == 2
    assert recovered.open_orders == {}


def test_duplicate_fill_event_is_idempotent_during_replay(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    order = OrderRequest(
        order_id="o-1",
        client_order_id="c-o-1",
        symbol="X",
        venue="TEST",
        side=Side.BUY,
        quantity=Decimal(1),
    )
    fill = Fill(
        fill_id="same-fill",
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=Decimal(1),
        price=Decimal(100),
    )
    journal.record_order_created(order, correlation_id="c-1")
    journal.record_order_submitted(order.order_id, correlation_id="c-1")
    journal.record_fill(fill, correlation_id="c-1")
    journal.record_fill(fill, correlation_id="c-1")

    recovered = recover_financial_state(wal, starting_cash=Decimal(1000))
    assert recovered.unique_fills_applied == 1
    assert recovered.ledger.positions["X"].quantity == Decimal(1)
    assert recovered.ledger.cash == Decimal(900)


def test_recovery_rejects_fill_for_unknown_order(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    journal.record_fill(
        Fill(
            fill_id="f-1",
            order_id="missing",
            symbol="X",
            side=Side.BUY,
            quantity=Decimal(1),
            price=Decimal(100),
        ),
        correlation_id="c-1",
    )

    with pytest.raises(RecoveryError, match="unknown order"):
        recover_financial_state(wal, starting_cash=Decimal(1000))


def test_kill_switch_reset_is_restored(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    journal.record_kill_switch_engaged("test", correlation_id="risk-1")
    journal.record_kill_switch_reset(correlation_id="risk-2")

    recovered = recover_financial_state(wal, starting_cash=Decimal(1000))
    assert not recovered.kill_switch
    assert recovered.kill_switch_reason == ""
