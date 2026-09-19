from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from aura.domain.models import OrderStatus, Side
from aura.execution.state import is_terminal_order_status
from aura.persistence.recovery import RecoveredFinancialState
from aura.risk.engine import RiskEngine


class ReconciliationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ReconciliationIssueType(str, Enum):
    LOCAL_OPEN_ORDER_MISSING_AT_BROKER = "local_open_order_missing_at_broker"
    BROKER_OPEN_ORDER_MISSING_LOCALLY = "broker_open_order_missing_locally"
    ORDER_STATUS_MISMATCH = "order_status_mismatch"
    ORDER_FILLED_QUANTITY_MISMATCH = "order_filled_quantity_mismatch"
    POSITION_QUANTITY_MISMATCH = "position_quantity_mismatch"


class BrokerOrderSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker_order_id: str
    client_order_id: str
    symbol: str
    side: Side
    quantity: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(default=Decimal(0), ge=0)
    status: OrderStatus


class BrokerPositionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    quantity: Decimal


class ReconciliationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    issue_type: ReconciliationIssueType
    severity: ReconciliationSeverity
    key: str
    detail: str


@dataclass(slots=True, frozen=True)
class ReconciliationReport:
    issues: tuple[ReconciliationIssue, ...]
    local_open_orders: int
    broker_open_orders: int
    compared_positions: int

    @property
    def safe_for_new_risk(self) -> bool:
        return not any(issue.severity == ReconciliationSeverity.CRITICAL for issue in self.issues)

    @property
    def should_freeze_new_orders(self) -> bool:
        return not self.safe_for_new_risk


class ReconciliationEngine:
    """Compare recovered AURA financial state with broker truth.

    This engine deliberately does not mutate or "repair" financial state. Any
    critical divergence freezes new risk until an explicit reconciliation
    workflow resolves the discrepancy. Silent healing can hide duplicate fills,
    lost orders, or broker-side positions and is therefore forbidden.
    """

    def compare(
        self,
        recovered: RecoveredFinancialState,
        *,
        broker_orders: list[BrokerOrderSnapshot],
        broker_positions: list[BrokerPositionSnapshot],
    ) -> ReconciliationReport:
        issues: list[ReconciliationIssue] = []

        local_open = {
            state.request.client_order_id: state for state in recovered.open_orders.values()
        }
        broker_open = {
            order.client_order_id: order
            for order in broker_orders
            if not is_terminal_order_status(order.status)
        }

        for client_order_id, state in local_open.items():
            broker = broker_open.get(client_order_id)
            if broker is None:
                issues.append(
                    ReconciliationIssue(
                        issue_type=ReconciliationIssueType.LOCAL_OPEN_ORDER_MISSING_AT_BROKER,
                        severity=ReconciliationSeverity.CRITICAL,
                        key=client_order_id,
                        detail=f"local {state.status.value} order is not present in broker open orders",
                    )
                )
                continue
            if broker.status != state.status:
                issues.append(
                    ReconciliationIssue(
                        issue_type=ReconciliationIssueType.ORDER_STATUS_MISMATCH,
                        severity=ReconciliationSeverity.CRITICAL,
                        key=client_order_id,
                        detail=(
                            f"local status {state.status.value} != broker status "
                            f"{broker.status.value}"
                        ),
                    )
                )
            if broker.filled_quantity != state.filled_quantity:
                issues.append(
                    ReconciliationIssue(
                        issue_type=ReconciliationIssueType.ORDER_FILLED_QUANTITY_MISMATCH,
                        severity=ReconciliationSeverity.CRITICAL,
                        key=client_order_id,
                        detail=(
                            f"local filled {state.filled_quantity} != broker filled "
                            f"{broker.filled_quantity}"
                        ),
                    )
                )

        for client_order_id, broker in broker_open.items():
            if client_order_id not in local_open:
                issues.append(
                    ReconciliationIssue(
                        issue_type=ReconciliationIssueType.BROKER_OPEN_ORDER_MISSING_LOCALLY,
                        severity=ReconciliationSeverity.CRITICAL,
                        key=client_order_id,
                        detail=(
                            f"broker has open {broker.status.value} order "
                            "that is absent from recovered AURA state"
                        ),
                    )
                )

        local_positions = {
            symbol: position.quantity
            for symbol, position in recovered.ledger.positions.items()
            if position.quantity != 0
        }
        broker_position_map = {
            position.symbol: position.quantity
            for position in broker_positions
            if position.quantity != 0
        }
        symbols = sorted(set(local_positions) | set(broker_position_map))
        for symbol in symbols:
            local_qty = local_positions.get(symbol, Decimal(0))
            broker_qty = broker_position_map.get(symbol, Decimal(0))
            if local_qty != broker_qty:
                issues.append(
                    ReconciliationIssue(
                        issue_type=ReconciliationIssueType.POSITION_QUANTITY_MISMATCH,
                        severity=ReconciliationSeverity.CRITICAL,
                        key=symbol,
                        detail=f"local position {local_qty} != broker position {broker_qty}",
                    )
                )

        return ReconciliationReport(
            issues=tuple(issues),
            local_open_orders=len(local_open),
            broker_open_orders=len(broker_open),
            compared_positions=len(symbols),
        )


class ReconciliationSupervisor:
    """Enforce reconciliation safety by freezing new risk on critical divergence.

    A clean report never auto-resets an existing kill switch. Recovery from a
    reconciliation incident must be explicit so an unrelated/manual risk freeze
    cannot be cleared accidentally.
    """

    def enforce(self, report: ReconciliationReport, risk_engine: RiskEngine) -> bool:
        if not report.should_freeze_new_orders:
            return False

        critical = [
            issue for issue in report.issues if issue.severity == ReconciliationSeverity.CRITICAL
        ]
        summary = "; ".join(f"{issue.issue_type.value}:{issue.key}" for issue in critical[:3])
        if len(critical) > 3:
            summary = f"{summary}; +{len(critical) - 3} more"
        risk_engine.engage_kill_switch(f"reconciliation divergence: {summary}")
        return True
