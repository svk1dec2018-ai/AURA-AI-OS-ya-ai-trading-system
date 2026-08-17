from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from pydantic import BaseModel, ConfigDict

from aura.domain.models import Fill, OrderRequest, OrderStatus
from aura.execution.state import InvalidOrderTransition, OrderState, OverfillError
from aura.persistence.recovery import (
    FinancialEventType,
    KillSwitchPayload,
    RecoveredFinancialState,
    RecoveryError,
)
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent
from aura.portfolio.ledger import PortfolioLedger, Position


class CheckpointError(RuntimeError):
    pass


class PositionCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal


class OrderCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: OrderRequest
    status: OrderStatus
    filled_quantity: Decimal
    average_fill_price: Decimal
    fill_ids: tuple[str, ...]


class FinancialCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    wal_sequence: int
    starting_cash: Decimal
    cash: Decimal
    realized_pnl: Decimal
    fees_paid: Decimal
    peak_equity: Decimal
    positions: tuple[PositionCheckpoint, ...]
    applied_fill_ids: tuple[str, ...]
    orders: tuple[OrderCheckpoint, ...]
    kill_switch: bool
    kill_switch_reason: str
    unique_fills_applied: int


@dataclass(slots=True, frozen=True)
class CheckpointEnvelope:
    checkpoint: FinancialCheckpoint
    checksum: str


class FinancialCheckpointStore:
    """Atomic, checksum-protected financial state checkpoints.

    A checkpoint accelerates state restoration but never replaces or truncates
    the append-only WAL. The WAL remains the immutable audit source of truth.
    """

    def __init__(self, path: str | Path, *, fsync: bool = True) -> None:
        self.path = Path(path)
        self.fsync = fsync
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, state: RecoveredFinancialState) -> FinancialCheckpoint:
        checkpoint = self._from_recovered_state(state)
        payload = checkpoint.model_dump(mode="json")
        checksum = _checksum(payload)
        record = {"checkpoint": payload, "checksum": checksum}

        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(record, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())

        try:
            os.replace(temp_path, self.path)
            if self.fsync:
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return checkpoint

    def load(self) -> FinancialCheckpoint:
        if not self.path.exists():
            raise CheckpointError(f"checkpoint does not exist: {self.path}")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            payload = raw["checkpoint"]
            supplied_checksum = str(raw["checksum"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CheckpointError("checkpoint is malformed or truncated") from exc

        expected_checksum = _checksum(payload)
        if supplied_checksum != expected_checksum:
            raise CheckpointError("checkpoint checksum mismatch")
        try:
            return FinancialCheckpoint.model_validate(payload)
        except ValueError as exc:
            raise CheckpointError("checkpoint payload validation failed") from exc

    @staticmethod
    def _from_recovered_state(state: RecoveredFinancialState) -> FinancialCheckpoint:
        positions = tuple(
            PositionCheckpoint(
                symbol=position.symbol,
                quantity=position.quantity,
                average_price=position.average_price,
                realized_pnl=position.realized_pnl,
            )
            for position in sorted(state.ledger.positions.values(), key=lambda item: item.symbol)
        )
        orders = tuple(
            OrderCheckpoint(
                request=order_state.request,
                status=order_state.status,
                filled_quantity=order_state.filled_quantity,
                average_fill_price=order_state.average_fill_price,
                fill_ids=tuple(sorted(order_state.fill_ids)),
            )
            for _, order_state in sorted(state.orders.items())
        )
        return FinancialCheckpoint(
            wal_sequence=state.last_sequence,
            starting_cash=state.ledger.starting_cash,
            cash=state.ledger.cash,
            realized_pnl=state.ledger.realized_pnl,
            fees_paid=state.ledger.fees_paid,
            peak_equity=state.ledger.peak_equity,
            positions=positions,
            applied_fill_ids=tuple(sorted(state.ledger._applied_fills)),
            orders=orders,
            kill_switch=state.kill_switch,
            kill_switch_reason=state.kill_switch_reason,
            unique_fills_applied=state.unique_fills_applied,
        )


def recover_financial_state_from_checkpoint(
    wal: JsonlWriteAheadLog,
    checkpoint_store: FinancialCheckpointStore,
    *,
    starting_cash: Decimal,
) -> RecoveredFinancialState:
    checkpoint = checkpoint_store.load()
    if checkpoint.starting_cash != starting_cash:
        raise CheckpointError(
            f"checkpoint starting_cash {checkpoint.starting_cash} != requested {starting_cash}"
        )

    events = wal.read_all()
    if checkpoint.wal_sequence > wal.last_sequence:
        raise CheckpointError(
            f"checkpoint WAL sequence {checkpoint.wal_sequence} is ahead of WAL {wal.last_sequence}"
        )
    if checkpoint.wal_sequence > 0 and not any(
        event.sequence == checkpoint.wal_sequence for event in events
    ):
        raise CheckpointError("checkpoint WAL anchor sequence is missing from the current WAL")

    ledger = _restore_ledger(checkpoint)
    orders = _restore_orders(checkpoint)
    kill_switch = checkpoint.kill_switch
    kill_switch_reason = checkpoint.kill_switch_reason
    unique_fills = checkpoint.unique_fills_applied

    tail_events = [event for event in events if event.sequence > checkpoint.wal_sequence]
    for event in tail_events:
        kill_switch, kill_switch_reason, fill_added = _apply_tail_event(
            event,
            ledger=ledger,
            orders=orders,
            kill_switch=kill_switch,
            kill_switch_reason=kill_switch_reason,
        )
        if fill_added:
            unique_fills += 1

    return RecoveredFinancialState(
        ledger=ledger,
        orders=orders,
        kill_switch=kill_switch,
        kill_switch_reason=kill_switch_reason,
        last_sequence=wal.last_sequence,
        replayed_events=len(tail_events),
        unique_fills_applied=unique_fills,
    )


def _restore_ledger(checkpoint: FinancialCheckpoint) -> PortfolioLedger:
    ledger = PortfolioLedger(checkpoint.starting_cash)
    ledger.cash = checkpoint.cash
    ledger.realized_pnl = checkpoint.realized_pnl
    ledger.fees_paid = checkpoint.fees_paid
    ledger.peak_equity = checkpoint.peak_equity
    ledger.positions = {
        item.symbol: Position(
            symbol=item.symbol,
            quantity=item.quantity,
            average_price=item.average_price,
            realized_pnl=item.realized_pnl,
        )
        for item in checkpoint.positions
    }
    ledger._applied_fills = set(checkpoint.applied_fill_ids)
    return ledger


def _restore_orders(checkpoint: FinancialCheckpoint) -> dict[str, OrderState]:
    orders: dict[str, OrderState] = {}
    for item in checkpoint.orders:
        state = OrderState(
            request=item.request,
            status=item.status,
            filled_quantity=item.filled_quantity,
            average_fill_price=item.average_fill_price,
            fill_ids=set(item.fill_ids),
        )
        orders[state.request.order_id] = state
    return orders


def _apply_tail_event(
    event: WalEvent,
    *,
    ledger: PortfolioLedger,
    orders: dict[str, OrderState],
    kill_switch: bool,
    kill_switch_reason: str,
) -> tuple[bool, str, bool]:
    try:
        event_type = FinancialEventType(event.event_type)
    except ValueError as exc:
        raise RecoveryError(
            f"unsupported financial event type at sequence {event.sequence}: {event.event_type}"
        ) from exc

    fill_added = False
    try:
        if event_type == FinancialEventType.ORDER_CREATED:
            order = OrderRequest.model_validate(_required(event.payload, "order"))
            if order.order_id in orders:
                raise RecoveryError(f"duplicate order creation: {order.order_id}")
            orders[order.order_id] = OrderState(order)

        elif event_type == FinancialEventType.ORDER_SUBMITTED:
            _order_state(orders, event).submit()

        elif event_type == FinancialEventType.ORDER_CANCELLED:
            _order_state(orders, event).cancel()

        elif event_type == FinancialEventType.ORDER_REJECTED:
            _order_state(orders, event).reject()

        elif event_type == FinancialEventType.FILL_APPLIED:
            fill = Fill.model_validate(_required(event.payload, "fill"))
            state = orders.get(fill.order_id)
            if state is None:
                raise RecoveryError(f"fill references unknown order: {fill.order_id}")
            state_applied = state.apply_fill(fill)
            ledger_applied = ledger.apply_fill(fill)
            if state_applied != ledger_applied:
                raise RecoveryError(
                    f"fill idempotency divergence between order and ledger: {fill.fill_id}"
                )
            fill_added = state_applied

        elif event_type == FinancialEventType.KILL_SWITCH_ENGAGED:
            payload = KillSwitchPayload.model_validate(event.payload)
            kill_switch = True
            kill_switch_reason = payload.reason or "restored kill switch"

        elif event_type == FinancialEventType.KILL_SWITCH_RESET:
            kill_switch = False
            kill_switch_reason = ""

    except RecoveryError:
        raise
    except (InvalidOrderTransition, OverfillError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryError(
            f"invalid financial state transition at WAL sequence {event.sequence}"
        ) from exc

    return kill_switch, kill_switch_reason, fill_added


def _order_state(orders: dict[str, OrderState], event: WalEvent) -> OrderState:
    order_id = str(_required(event.payload, "order_id"))
    try:
        return orders[order_id]
    except KeyError as exc:
        raise RecoveryError(f"event references unknown order: {order_id}") from exc


def _required(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise RecoveryError(f"missing required event payload field: {key}")
    return payload[key]


def _checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
