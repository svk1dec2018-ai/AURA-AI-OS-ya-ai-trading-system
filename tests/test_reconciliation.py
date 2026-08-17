from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from aura.domain.models import Fill, OrderRequest, OrderStatus, Side
from aura.execution.reconciliation import (
    BrokerOrderSnapshot,
    BrokerPositionSnapshot,
    ReconciliationEngine,
    ReconciliationIssueType,
    ReconciliationSupervisor,
)
from aura.persistence.recovery import FinancialEventJournal, recover_financial_state
from aura.persistence.wal import JsonlWriteAheadLog
from aura.risk.engine import RiskEngine, RiskLimits


def _recovered_with_partial_fill(tmp_path: Path):
    wal = JsonlWriteAheadLog(tmp_path / "financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    order = OrderRequest(
        order_id="o-1",
        client_order_id="client-1",
        symbol="X",
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
            quantity=Decimal(1),
            price=Decimal(100),
        ),
        correlation_id="decision-1",
    )
    return recover_financial_state(wal, starting_cash=Decimal(1000)), order


def test_matching_broker_state_is_safe(tmp_path: Path) -> None:
    recovered, order = _recovered_with_partial_fill(tmp_path)
    report = ReconciliationEngine().compare(
        recovered,
        broker_orders=[
            BrokerOrderSnapshot(
                broker_order_id="b-1",
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                filled_quantity=Decimal(1),
                status=OrderStatus.PARTIALLY_FILLED,
            )
        ],
        broker_positions=[BrokerPositionSnapshot(symbol="X", quantity=Decimal(1))],
    )

    assert report.safe_for_new_risk
    assert not report.should_freeze_new_orders
    assert report.issues == ()


def test_missing_broker_order_freezes_new_risk(tmp_path: Path) -> None:
    recovered, _ = _recovered_with_partial_fill(tmp_path)
    report = ReconciliationEngine().compare(
        recovered,
        broker_orders=[],
        broker_positions=[BrokerPositionSnapshot(symbol="X", quantity=Decimal(1))],
    )

    assert report.should_freeze_new_orders
    assert report.issues[0].issue_type == ReconciliationIssueType.LOCAL_OPEN_ORDER_MISSING_AT_BROKER


def test_unknown_broker_order_freezes_new_risk(tmp_path: Path) -> None:
    recovered, _ = _recovered_with_partial_fill(tmp_path)
    report = ReconciliationEngine().compare(
        recovered,
        broker_orders=[
            BrokerOrderSnapshot(
                broker_order_id="b-unknown",
                client_order_id="unknown-client",
                symbol="X",
                side=Side.SELL,
                quantity=Decimal(1),
                status=OrderStatus.SUBMITTED,
            )
        ],
        broker_positions=[BrokerPositionSnapshot(symbol="X", quantity=Decimal(1))],
    )

    issue_types = {issue.issue_type for issue in report.issues}
    assert ReconciliationIssueType.LOCAL_OPEN_ORDER_MISSING_AT_BROKER in issue_types
    assert ReconciliationIssueType.BROKER_OPEN_ORDER_MISSING_LOCALLY in issue_types
    assert report.should_freeze_new_orders


def test_position_mismatch_freezes_new_risk(tmp_path: Path) -> None:
    recovered, order = _recovered_with_partial_fill(tmp_path)
    report = ReconciliationEngine().compare(
        recovered,
        broker_orders=[
            BrokerOrderSnapshot(
                broker_order_id="b-1",
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                filled_quantity=Decimal(1),
                status=OrderStatus.PARTIALLY_FILLED,
            )
        ],
        broker_positions=[BrokerPositionSnapshot(symbol="X", quantity=Decimal("1.5"))],
    )

    assert report.should_freeze_new_orders
    assert any(
        issue.issue_type == ReconciliationIssueType.POSITION_QUANTITY_MISMATCH
        for issue in report.issues
    )


def test_supervisor_engages_kill_switch_and_never_auto_resets(tmp_path: Path) -> None:
    recovered, _ = _recovered_with_partial_fill(tmp_path)
    engine = ReconciliationEngine()
    bad_report = engine.compare(
        recovered,
        broker_orders=[],
        broker_positions=[BrokerPositionSnapshot(symbol="X", quantity=Decimal(1))],
    )
    risk = RiskEngine(RiskLimits())
    supervisor = ReconciliationSupervisor()

    assert supervisor.enforce(bad_report, risk)
    assert risk.kill_switch
    assert "reconciliation divergence" in risk.kill_switch_reason

    clean_report = engine.compare(
        recovered,
        broker_orders=[
            BrokerOrderSnapshot(
                broker_order_id="b-1",
                client_order_id="client-1",
                symbol="X",
                side=Side.BUY,
                quantity=Decimal(2),
                filled_quantity=Decimal(1),
                status=OrderStatus.PARTIALLY_FILLED,
            )
        ],
        broker_positions=[BrokerPositionSnapshot(symbol="X", quantity=Decimal(1))],
    )
    assert not supervisor.enforce(clean_report, risk)
    assert risk.kill_switch
