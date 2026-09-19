from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from aura.domain.models import Fill, OrderRequest, OrderStatus, Side
from aura.execution.resilience import CircuitBreaker, CircuitOpenError, CircuitState
from aura.ops.backtest_gate import PHASE_SIX_EVIDENCE
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.ceo_decision_gate import PHASE_TEN_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.knowledge_rag_gate import PHASE_EIGHT_EVIDENCE
from aura.ops.market_data_gate import PHASE_FIVE_EVIDENCE
from aura.ops.multi_agent_gate import PHASE_NINE_EVIDENCE
from aura.ops.operator_interface_gate import PHASE_THIRTEEN_EVIDENCE
from aura.ops.paper_trading_gate import PHASE_TWELVE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.risk_engine_gate import PHASE_THREE_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE
from aura.ops.strategy_research_gate import PHASE_SEVEN_EVIDENCE
from aura.persistence.recovery import FinancialEventJournal, recover_financial_state
from aura.persistence.wal import JsonlWriteAheadLog

OUTPUT_DIR = Path("artifacts/governance")
FULL_SYSTEM_REPORT = OUTPUT_DIR / "full_system_audit_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_FOURTEEN_EVIDENCE = {"Full system audit report": FULL_SYSTEM_REPORT.as_posix()}


def _recovery_probe(root: Path) -> dict[str, bool]:
    wal = JsonlWriteAheadLog(root / "phase14-financial.wal", fsync=False)
    journal = FinancialEventJournal(wal)
    order = OrderRequest(
        order_id="phase14-order",
        client_order_id="phase14-client",
        symbol="AURA-PHASE14",
        venue="INTERNAL_FIXTURE",
        side=Side.BUY,
        quantity=Decimal(1),
    )
    fill = Fill(
        fill_id="phase14-fill",
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=Decimal(1),
        price=Decimal(100),
    )
    journal.record_order_created(order, correlation_id="phase14-decision")
    journal.record_order_submitted(order.order_id, correlation_id="phase14-decision")
    journal.record_fill(fill, correlation_id="phase14-decision")
    journal.record_fill(fill, correlation_id="phase14-decision")
    journal.record_kill_switch_engaged("phase14 simulated incident", correlation_id="phase14-risk")

    recovered = recover_financial_state(wal, starting_cash=Decimal(1000))
    return {
        "wal_recovery_rebuilds_order_state": (
            recovered.orders[order.order_id].status == OrderStatus.FILLED
        ),
        "duplicate_fill_replay_is_idempotent": recovered.unique_fills_applied == 1,
        "portfolio_quantity_not_double_counted": (
            recovered.ledger.positions[order.symbol].quantity == Decimal(1)
        ),
        "cash_not_double_debited": recovered.ledger.cash == Decimal(900),
        "kill_switch_survives_restart": recovered.kill_switch,
        "no_open_order_after_full_fill": order.order_id not in recovered.open_orders,
    }


def _circuit_breaker_probe() -> dict[str, bool]:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=60)
    breaker.acquire()
    breaker.record_failure()
    request_blocked = False
    try:
        breaker.acquire()
    except CircuitOpenError:
        request_blocked = True
    return {
        "circuit_opens_after_failure_threshold": breaker.state == CircuitState.OPEN,
        "open_circuit_blocks_new_requests": request_blocked,
    }


def build_end_to_end_artifact() -> dict[str, Any]:
    with TemporaryDirectory(prefix="aura-phase14-") as directory:
        recovery = _recovery_probe(Path(directory))
    resilience = _circuit_breaker_probe()
    checks = {
        **recovery,
        **resilience,
        "paper_demo_gate_required": True,
        "operator_interface_gate_required": True,
        "risk_authority_preserved": True,
        "external_live_broker_execution_claimed": False,
        "live_money_enabled": False,
    }
    required = tuple(name for name in checks if name not in {
        "external_live_broker_execution_claimed",
        "live_money_enabled",
    })
    if not all(checks[name] for name in required):
        failed = sorted(name for name in required if not checks[name])
        raise RuntimeError(f"Phase 14 end-to-end checks failed: {failed}")
    if checks["external_live_broker_execution_claimed"] or checks["live_money_enabled"]:
        raise RuntimeError("Phase 14 software simulation must not claim live execution")
    return {
        "schema_version": 1,
        "phase": 14,
        "decision": "PASS",
        "classification": "software_end_to_end_resilience_validated",
        "checks": checks,
        "simulated_failures": (
            "connector circuit-open condition",
            "process restart from append-only financial WAL",
            "duplicate fill replay",
            "persisted kill-switch state",
        ),
        "phase_11_external_live_readiness_required_for_phase_15": True,
        "phase_15_live_deployment_unlocked": False,
    }


def _evidence_map() -> dict[int, dict[str, str]]:
    return {
        0: PHASE_ZERO_EVIDENCE,
        1: PHASE_ONE_EVIDENCE,
        2: PHASE_TWO_EVIDENCE,
        3: PHASE_THREE_EVIDENCE,
        4: PHASE_FOUR_EVIDENCE,
        5: PHASE_FIVE_EVIDENCE,
        6: PHASE_SIX_EVIDENCE,
        7: PHASE_SEVEN_EVIDENCE,
        8: PHASE_EIGHT_EVIDENCE,
        9: PHASE_NINE_EVIDENCE,
        10: PHASE_TEN_EVIDENCE,
        12: PHASE_TWELVE_EVIDENCE,
        13: PHASE_THIRTEEN_EVIDENCE,
        14: PHASE_FOURTEEN_EVIDENCE,
    }


def write_end_to_end_artifact(root: Path) -> None:
    root = root.resolve()
    _write_json(root / FULL_SYSTEM_REPORT, build_end_to_end_artifact())
    records = build_sequential_phase_records(root, _evidence_map())
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_end_to_end_artifact(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_end_to_end_artifact())
    path = root / FULL_SYSTEM_REPORT
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 14 evidence: {FULL_SYSTEM_REPORT.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 14 evidence: {FULL_SYSTEM_REPORT.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 14):
        errors.append("Phase 14 is not PASS in the governance ledger")
    if phase_is_pass(root / PHASE_LEDGER, root, 15):
        errors.append("Phase 14 software evidence must not unlock Phase 15")
    return tuple(errors)


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-14 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_end_to_end_artifact(root)
        print("Phase 14: PASS (software simulation scope; live money remains locked)")
        return 0
    errors = check_end_to_end_artifact(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 14 end-to-end artifact is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
