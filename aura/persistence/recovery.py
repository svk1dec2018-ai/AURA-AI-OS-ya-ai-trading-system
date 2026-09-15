from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from aura.domain.models import Fill, OrderRequest
from aura.execution.state import (
    InvalidOrderTransition,
    OrderState,
    OverfillError,
    is_terminal_order_status,
)
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent
from aura.portfolio.instruments import InstrumentLedgerSpec
from aura.portfolio.ledger import PortfolioLedger


class RecoveryError(RuntimeError):
    pass


class FinancialEventType(str, Enum):
    ORDER_CREATED = "order.created"
    ORDER_SUBMITTED = "order.submitted"
    ORDER_ACKNOWLEDGED = "order.acknowledged"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_REJECTED = "order.rejected"
    ORDER_EXPIRED = "order.expired"
    FILL_APPLIED = "fill.applied"
    KILL_SWITCH_ENGAGED = "risk.kill_switch.engaged"
    KILL_SWITCH_RESET = "risk.kill_switch.reset"


class KillSwitchPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str = ""


class FinancialEventJournal:
    """Typed financial event facade over AURA's append-only WAL."""

    def __init__(self, wal: JsonlWriteAheadLog) -> None:
        self.wal = wal

    def record_order_created(self, order: OrderRequest, *, correlation_id: str) -> WalEvent:
        return self.wal.append(
            event_type=FinancialEventType.ORDER_CREATED.value,
            payload={"order": order.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def record_order_submitted(self, order_id: str, *, correlation_id: str) -> WalEvent:
        return self._record_order_transition(
            FinancialEventType.ORDER_SUBMITTED, order_id, correlation_id
        )

    def record_order_cancelled(self, order_id: str, *, correlation_id: str) -> WalEvent:
        return self._record_order_transition(
            FinancialEventType.ORDER_CANCELLED, order_id, correlation_id
        )

    def record_order_acknowledged(self, order_id: str, *, correlation_id: str) -> WalEvent:
        return self._record_order_transition(
            FinancialEventType.ORDER_ACKNOWLEDGED, order_id, correlation_id
        )

    def record_order_rejected(self, order_id: str, *, correlation_id: str) -> WalEvent:
        return self._record_order_transition(
            FinancialEventType.ORDER_REJECTED, order_id, correlation_id
        )

    def record_order_expired(self, order_id: str, *, correlation_id: str) -> WalEvent:
        return self._record_order_transition(
            FinancialEventType.ORDER_EXPIRED, order_id, correlation_id
        )

    def _record_order_transition(
        self,
        event_type: FinancialEventType,
        order_id: str,
        correlation_id: str,
    ) -> WalEvent:
        if not order_id:
            raise ValueError("order_id is required")
        return self.wal.append(
            event_type=event_type.value,
            payload={"order_id": order_id},
            correlation_id=correlation_id,
        )

    def record_fill(self, fill: Fill, *, correlation_id: str) -> WalEvent:
        return self.wal.append(
            event_type=FinancialEventType.FILL_APPLIED.value,
            payload={"fill": fill.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def record_kill_switch_engaged(self, reason: str, *, correlation_id: str) -> WalEvent:
        return self.wal.append(
            event_type=FinancialEventType.KILL_SWITCH_ENGAGED.value,
            payload=KillSwitchPayload(reason=reason).model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def record_kill_switch_reset(self, *, correlation_id: str) -> WalEvent:
        return self.wal.append(
            event_type=FinancialEventType.KILL_SWITCH_RESET.value,
            payload={},
            correlation_id=correlation_id,
        )


@dataclass(slots=True)
class RecoveredFinancialState:
    ledger: PortfolioLedger
    orders: dict[str, OrderState]
    kill_switch: bool
    kill_switch_reason: str
    last_sequence: int
    replayed_events: int
    unique_fills_applied: int

    @property
    def open_orders(self) -> dict[str, OrderState]:
        return {
            order_id: state
            for order_id, state in self.orders.items()
            if not is_terminal_order_status(state.status)
        }


def recover_financial_state(
    wal: JsonlWriteAheadLog,
    *,
    starting_cash: Decimal,
    instrument_specs: dict[str, InstrumentLedgerSpec] | None = None,
) -> RecoveredFinancialState:
    ledger = PortfolioLedger(starting_cash, instrument_specs=instrument_specs)
    orders: dict[str, OrderState] = {}
    kill_switch = False
    kill_switch_reason = ""
    unique_fills = 0

    events = wal.read_all()
    for event in events:
        try:
            event_type = FinancialEventType(event.event_type)
        except ValueError as exc:
            raise RecoveryError(
                f"unsupported financial event type at sequence {event.sequence}: {event.event_type}"
            ) from exc

        try:
            if event_type == FinancialEventType.ORDER_CREATED:
                order = OrderRequest.model_validate(_required(event.payload, "order"))
                if order.order_id in orders:
                    raise RecoveryError(f"duplicate order creation: {order.order_id}")
                orders[order.order_id] = OrderState(order)
            elif event_type == FinancialEventType.ORDER_SUBMITTED:
                _order_state(orders, event).submit()
            elif event_type == FinancialEventType.ORDER_ACKNOWLEDGED:
                _order_state(orders, event).acknowledge()
            elif event_type == FinancialEventType.ORDER_CANCELLED:
                _order_state(orders, event).cancel()
            elif event_type == FinancialEventType.ORDER_REJECTED:
                _order_state(orders, event).reject()
            elif event_type == FinancialEventType.ORDER_EXPIRED:
                _order_state(orders, event).expire()
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
                if state_applied:
                    unique_fills += 1
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

    return RecoveredFinancialState(
        ledger=ledger,
        orders=orders,
        kill_switch=kill_switch,
        kill_switch_reason=kill_switch_reason,
        last_sequence=wal.last_sequence,
        replayed_events=len(events),
        unique_fills_applied=unique_fills,
    )


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
