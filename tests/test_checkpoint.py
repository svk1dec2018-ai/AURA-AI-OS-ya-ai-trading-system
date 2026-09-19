from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from aura.domain.models import Fill, OrderRequest, OrderStatus, Side
from aura.persistence.checkpoint import (
    CheckpointError,
    FinancialCheckpointStore,
    recover_financial_state_from_checkpoint,
)
from aura.persistence.recovery import FinancialEventJournal, recover_financial_state
from aura.persistence.wal import JsonlWriteAheadLog


def _order(order_id: str, client_id: str, quantity: str = "2") -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        client_order_id=client_id,
        symbol="X",
        venue="TEST",
        side=Side.BUY,
        quantity=Decimal(quantity),
    )


def _fill(order: OrderRequest, fill_id: str, quantity: str, price: str) -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=Decimal(quantity),
        price=Decimal(price),
    )


def test_checkpoint_plus_tail_matches_full_wal_recovery(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    first = _order("o-1", "client-1")
    journal.record_order_created(first, correlation_id="decision-1")
    journal.record_order_submitted(first.order_id, correlation_id="decision-1")
    journal.record_fill(_fill(first, "f-1", "1", "100"), correlation_id="decision-1")
    journal.record_kill_switch_engaged("checkpointed freeze", correlation_id="risk-1")

    checkpoint_state = recover_financial_state(wal, starting_cash=Decimal(1000))
    store = FinancialCheckpointStore(tmp_path / "financial.checkpoint", fsync=False)
    checkpoint = store.write(checkpoint_state)
    assert checkpoint.wal_sequence == 4

    journal.record_fill(_fill(first, "f-2", "1", "110"), correlation_id="decision-1")
    journal.record_kill_switch_reset(correlation_id="risk-2")
    second = _order("o-2", "client-2", quantity="1")
    journal.record_order_created(second, correlation_id="decision-2")
    journal.record_order_submitted(second.order_id, correlation_id="decision-2")

    full = recover_financial_state(wal, starting_cash=Decimal(1000))
    restored = recover_financial_state_from_checkpoint(
        wal,
        store,
        starting_cash=Decimal(1000),
    )

    assert restored.replayed_events == 4
    assert restored.last_sequence == full.last_sequence
    assert restored.kill_switch == full.kill_switch
    assert restored.kill_switch_reason == full.kill_switch_reason
    assert restored.unique_fills_applied == full.unique_fills_applied
    assert restored.ledger.cash == full.ledger.cash
    assert restored.ledger.realized_pnl == full.ledger.realized_pnl
    assert restored.ledger.fees_paid == full.ledger.fees_paid
    assert restored.ledger.positions["X"].quantity == full.ledger.positions["X"].quantity
    assert restored.ledger.positions["X"].average_price == full.ledger.positions["X"].average_price
    assert restored.orders["o-1"].status == OrderStatus.FILLED
    assert restored.orders["o-2"].status == OrderStatus.SUBMITTED
    assert restored.orders["o-1"].fill_ids == full.orders["o-1"].fill_ids


def test_duplicate_fill_after_checkpoint_remains_idempotent(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    order = _order("o-1", "client-1", quantity="1")
    fill = _fill(order, "f-1", "1", "100")
    journal.record_order_created(order, correlation_id="d-1")
    journal.record_order_submitted(order.order_id, correlation_id="d-1")
    journal.record_fill(fill, correlation_id="d-1")

    store = FinancialCheckpointStore(tmp_path / "financial.checkpoint", fsync=False)
    store.write(recover_financial_state(wal, starting_cash=Decimal(1000)))
    journal.record_fill(fill, correlation_id="duplicate-delivery")

    restored = recover_financial_state_from_checkpoint(
        wal,
        store,
        starting_cash=Decimal(1000),
    )
    assert restored.unique_fills_applied == 1
    assert restored.ledger.cash == Decimal(900)
    assert restored.ledger.positions["X"].quantity == Decimal(1)


def test_checkpoint_checksum_tampering_is_detected(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    store = FinancialCheckpointStore(tmp_path / "financial.checkpoint", fsync=False)
    store.write(recover_financial_state(wal, starting_cash=Decimal(1000)))

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["checkpoint"]["cash"] = "999999"
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(CheckpointError, match="checksum mismatch"):
        store.load()


def test_checkpoint_rejects_wrong_starting_cash(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    store = FinancialCheckpointStore(tmp_path / "financial.checkpoint", fsync=False)
    store.write(recover_financial_state(wal, starting_cash=Decimal(1000)))

    with pytest.raises(CheckpointError, match="starting_cash"):
        recover_financial_state_from_checkpoint(
            wal,
            store,
            starting_cash=Decimal(2000),
        )


def test_checkpoint_tail_replays_expiry(tmp_path: Path) -> None:
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    order = _order("o-expire", "client-expire", quantity="1")
    journal.record_order_created(order, correlation_id="decision")
    journal.record_order_submitted(order.order_id, correlation_id="decision")
    journal.record_order_acknowledged(order.order_id, correlation_id="decision")
    store = FinancialCheckpointStore(tmp_path / "financial.checkpoint", fsync=False)
    store.write(recover_financial_state(wal, starting_cash=Decimal(1000)))
    journal.record_order_expired(order.order_id, correlation_id="decision")

    restored = recover_financial_state_from_checkpoint(
        wal, store, starting_cash=Decimal(1000)
    )
    assert restored.orders[order.order_id].status == OrderStatus.EXPIRED
    assert restored.open_orders == {}
