from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from aura.domain.models import Fill, OrderRequest, OrderStatus


class InvalidOrderTransition(RuntimeError):
    pass


class OverfillError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
    },
    OrderStatus.ACKNOWLEDGED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.EXPIRED: set(),
}


def allowed_order_transitions(status: OrderStatus) -> frozenset[OrderStatus]:
    """Return the immutable transition contract for a lifecycle state."""
    return frozenset(_ALLOWED_TRANSITIONS[status])


def is_terminal_order_status(status: OrderStatus) -> bool:
    return not _ALLOWED_TRANSITIONS[status]


@dataclass(slots=True)
class OrderState:
    request: OrderRequest
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: Decimal = Decimal(0)
    average_fill_price: Decimal = Decimal(0)
    fill_ids: set[str] = field(default_factory=set)

    @property
    def remaining_quantity(self) -> Decimal:
        return self.request.quantity - self.filled_quantity

    def transition(self, target: OrderStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidOrderTransition(f"illegal transition {self.status} -> {target}")
        self.status = target

    def submit(self) -> None:
        self.transition(OrderStatus.SUBMITTED)

    def acknowledge(self) -> None:
        self.transition(OrderStatus.ACKNOWLEDGED)

    def cancel(self) -> None:
        self.transition(OrderStatus.CANCELLED)

    def reject(self) -> None:
        self.transition(OrderStatus.REJECTED)

    def expire(self) -> None:
        self.transition(OrderStatus.EXPIRED)

    def apply_fill(self, fill: Fill) -> bool:
        """Apply a fill once. Returns False for an already-seen fill id."""
        if fill.fill_id in self.fill_ids:
            return False
        if self.status not in {
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
        }:
            raise InvalidOrderTransition(f"cannot fill an order in {self.status}")
        if fill.order_id != self.request.order_id:
            raise ValueError("fill order_id does not match order")
        if fill.symbol != self.request.symbol or fill.side != self.request.side:
            raise ValueError("fill instrument/side does not match order")
        if fill.quantity > self.remaining_quantity:
            raise OverfillError(
                f"fill quantity {fill.quantity} exceeds remaining {self.remaining_quantity}"
            )

        previous_notional = self.average_fill_price * self.filled_quantity
        new_quantity = self.filled_quantity + fill.quantity
        self.average_fill_price = (previous_notional + fill.price * fill.quantity) / new_quantity
        self.filled_quantity = new_quantity
        self.fill_ids.add(fill.fill_id)

        target = (
            OrderStatus.FILLED
            if self.filled_quantity == self.request.quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        self.transition(target)
        return True
