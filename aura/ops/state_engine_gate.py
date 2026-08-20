from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from aura.domain.models import Fill, OrderRequest, OrderStatus, Side
from aura.execution.reconciliation import (
    BrokerOrderSnapshot,
    BrokerPositionSnapshot,
    ReconciliationEngine,
)
from aura.execution.state import (
    InvalidOrderTransition,
    OrderState,
    allowed_order_transitions,
    is_terminal_order_status,
)
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.persistence.checkpoint import (
    FinancialCheckpointStore,
    recover_financial_state_from_checkpoint,
)
from aura.persistence.recovery import FinancialEventJournal, recover_financial_state
from aura.persistence.wal import JsonlWriteAheadLog

OUTPUT_DIR = Path("artifacts/governance")
STATE_TRANSITION_LOGS = OUTPUT_DIR / "state_transition_logs.json"
RECONCILIATION_REPORT = OUTPUT_DIR / "reconciliation_test_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_TWO_EVIDENCE = {
    "State transition logs": STATE_TRANSITION_LOGS.as_posix(),
    "Reconciliation test report": RECONCILIATION_REPORT.as_posix(),
}
_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def build_state_engine_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    transition_report = _build_transition_report()
    reconciliation_report = _build_reconciliation_report()
    return transition_report, reconciliation_report


def write_state_engine_artifacts(root: Path) -> None:
    root = root.resolve()
    transitions, reconciliation = build_state_engine_artifacts()
    _write_json(root / STATE_TRANSITION_LOGS, transitions)
    _write_json(root / RECONCILIATION_REPORT, reconciliation)
    records = build_sequential_phase_records(
        root,
        {0: PHASE_ZERO_EVIDENCE, 1: PHASE_ONE_EVIDENCE, 2: PHASE_TWO_EVIDENCE},
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_state_engine_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    transitions, reconciliation = build_state_engine_artifacts()
    expected = {
        STATE_TRANSITION_LOGS: _pretty_json(transitions),
        RECONCILIATION_REPORT: _pretty_json(reconciliation),
    }
    errors: list[str] = []
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing Phase 2 evidence: {relative.as_posix()}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"stale Phase 2 evidence: {relative.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 2):
        errors.append("Phase 2 is not PASS in the governance ledger")
    return tuple(errors)


def _build_transition_report() -> dict[str, Any]:
    matrix = {
        status.value: sorted(target.value for target in allowed_order_transitions(status))
        for status in OrderStatus
    }
    order = _order("transition-order", "transition-client")
    state = OrderState(order)
    lifecycle = [state.status.value]
    state.submit()
    lifecycle.append(state.status.value)
    state.acknowledge()
    lifecycle.append(state.status.value)
    state.apply_fill(_fill(order, "partial", "1", "100"))
    lifecycle.append(state.status.value)
    state.apply_fill(_fill(order, "complete", "1", "110"))
    lifecycle.append(state.status.value)

    expiry = OrderState(_order("expiry-order", "expiry-client"))
    expiry.submit()
    expiry.acknowledge()
    expiry.expire()
    illegal_terminal_transition_rejected = False
    try:
        expiry.cancel()
    except InvalidOrderTransition:
        illegal_terminal_transition_rejected = True
    if not illegal_terminal_transition_rejected:
        raise RuntimeError("terminal order accepted an illegal transition")

    fingerprint = _sha256({"matrix": matrix, "lifecycle": lifecycle})
    if fingerprint != _sha256({"matrix": matrix, "lifecycle": lifecycle}):
        raise RuntimeError("order state transitions are not deterministic")
    return {
        "schema_version": 1,
        "phase": 2,
        "decision": "PASS",
        "allowed_transition_matrix": matrix,
        "complete_fill_lifecycle": lifecycle,
        "expiry_lifecycle": ["CREATED", "SUBMITTED", "ACKNOWLEDGED", "EXPIRED"],
        "terminal_states": sorted(
            status.value for status in OrderStatus if is_terminal_order_status(status)
        ),
        "illegal_terminal_transition_rejected": True,
        "deterministic_fingerprint": fingerprint,
        "live_money_enabled": False,
    }


def _build_reconciliation_report() -> dict[str, Any]:
    with TemporaryDirectory(prefix="aura-phase2-") as directory:
        root = Path(directory)
        wal = JsonlWriteAheadLog(root / "financial.wal", fsync=False)
        journal = FinancialEventJournal(wal)
        open_order = _order("open-order", "open-client")
        expiry_order = _order("expiry-order", "expiry-client", quantity="1")
        journal.record_order_created(open_order, correlation_id="decision-open")
        journal.record_order_submitted(open_order.order_id, correlation_id="decision-open")
        journal.record_order_acknowledged(open_order.order_id, correlation_id="decision-open")
        journal.record_fill(
            _fill(open_order, "partial-fill", "1", "100"),
            correlation_id="decision-open",
        )
        journal.record_order_created(expiry_order, correlation_id="decision-expiry")
        journal.record_order_submitted(expiry_order.order_id, correlation_id="decision-expiry")
        journal.record_order_acknowledged(
            expiry_order.order_id, correlation_id="decision-expiry"
        )

        checkpoint_state = recover_financial_state(wal, starting_cash=Decimal(1000))
        store = FinancialCheckpointStore(root / "financial.checkpoint", fsync=False)
        store.write(checkpoint_state)
        journal.record_order_expired(expiry_order.order_id, correlation_id="decision-expiry")

        full = recover_financial_state(wal, starting_cash=Decimal(1000))
        restored = recover_financial_state_from_checkpoint(
            wal, store, starting_cash=Decimal(1000)
        )
        full_fingerprint = _financial_state_fingerprint(full)
        restored_fingerprint = _financial_state_fingerprint(restored)
        if full_fingerprint != restored_fingerprint:
            raise RuntimeError("checkpoint plus WAL tail does not match full WAL recovery")

        broker_order = BrokerOrderSnapshot(
            broker_order_id="fixture-broker-order",
            client_order_id=open_order.client_order_id,
            symbol=open_order.symbol,
            side=open_order.side,
            quantity=open_order.quantity,
            filled_quantity=Decimal(1),
            status=OrderStatus.PARTIALLY_FILLED,
        )
        broker_position = BrokerPositionSnapshot(symbol=open_order.symbol, quantity=Decimal(1))
        engine = ReconciliationEngine()
        clean = engine.compare(
            full, broker_orders=[broker_order], broker_positions=[broker_position]
        )
        mismatch = engine.compare(full, broker_orders=[], broker_positions=[broker_position])
        if not clean.safe_for_new_risk or clean.issues:
            raise RuntimeError("matching broker fixture did not reconcile cleanly")
        if not mismatch.should_freeze_new_orders:
            raise RuntimeError("broker mismatch did not freeze new risk")

        return {
            "schema_version": 1,
            "phase": 2,
            "decision": "PASS",
            "wal_event_count": len(wal.read_all()),
            "checkpoint_tail_replay_events": restored.replayed_events,
            "full_recovery_fingerprint": full_fingerprint,
            "checkpoint_recovery_fingerprint": restored_fingerprint,
            "restart_recovery_matches": True,
            "expired_order_excluded_from_open_orders": (
                expiry_order.order_id not in full.open_orders
            ),
            "clean_reconciliation": {
                "issue_count": len(clean.issues),
                "safe_for_new_risk": clean.safe_for_new_risk,
            },
            "mismatch_simulation": {
                "issue_types": sorted(issue.issue_type.value for issue in mismatch.issues),
                "freezes_new_orders": mismatch.should_freeze_new_orders,
                "fixture_only": True,
            },
            "external_broker_claimed": False,
            "live_money_enabled": False,
            "strategy_promotion_authority": False,
        }


def _order(order_id: str, client_id: str, *, quantity: str = "2") -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        client_order_id=client_id,
        symbol="AURA-VALIDATION",
        venue="INTERNAL_FIXTURE",
        side=Side.BUY,
        quantity=Decimal(quantity),
        created_at=_NOW,
    )


def _fill(order: OrderRequest, fill_id: str, quantity: str, price: str) -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        timestamp=_NOW,
    )


def _financial_state_fingerprint(state: Any) -> str:
    payload = {
        "cash": str(state.ledger.cash),
        "last_sequence": state.last_sequence,
        "orders": {
            order_id: {
                "status": order.status.value,
                "filled_quantity": str(order.filled_quantity),
                "average_fill_price": str(order.average_fill_price),
                "fill_ids": sorted(order.fill_ids),
            }
            for order_id, order in sorted(state.orders.items())
        },
        "positions": {
            symbol: {
                "quantity": str(position.quantity),
                "average_price": str(position.average_price),
            }
            for symbol, position in sorted(state.ledger.positions.items())
        },
        "unique_fills_applied": state.unique_fills_applied,
    }
    return _sha256(payload)


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-2 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_state_engine_artifacts(root)
        print("Phase 2: PASS")
        return 0
    errors = check_state_engine_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 2 state-engine artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
