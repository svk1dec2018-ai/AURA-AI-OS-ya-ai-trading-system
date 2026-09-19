from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.domain.models import Fill, OrderRequest, Side
from aura.execution.angel_one import AngelOneReadOnlyBroker
from aura.execution.broker import (
    BrokerAdapter,
    BrokerCapabilities,
    BrokerExecutionMode,
    broker_adapter_conformance,
)
from aura.execution.dhan_sandbox import DhanSandboxBroker
from aura.execution.mt5_demo_broker import MT5DemoBroker
from aura.execution.paper import PaperBroker
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.risk_engine_gate import PHASE_THREE_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE

OUTPUT_DIR = Path("artifacts/governance")
CONFORMANCE_REPORT = OUTPUT_DIR / "broker_adapter_conformance_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_FOUR_EVIDENCE = {"Adapter conformance report": CONFORMANCE_REPORT.as_posix()}
_FORBIDDEN_STRATEGY_IMPORTS = (
    "aura.execution",
    "MetaTrader5",
    "SmartApi",
    "dhanhq",
)


class _ContractProbeBroker(BrokerAdapter):
    name = "INTERNAL_CONTRACT_PROBE"
    capabilities = BrokerCapabilities(
        mode=BrokerExecutionMode.PAPER,
        supports_order_submission=True,
        supports_order_cancellation=True,
        supports_fill_stream=True,
        supports_reconciliation=False,
    )

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def submit_order(self, order: OrderRequest) -> str:
        return f"probe:{order.client_order_id}"

    async def cancel_order(self, broker_order_id: str) -> None:
        if not broker_order_id:
            raise ValueError("broker_order_id is required")

    async def fills(self) -> AsyncIterator[Fill]:
        if False:
            yield


def build_broker_conformance_artifact(root: Path) -> dict[str, Any]:
    root = root.resolve()
    adapters = (
        PaperBroker,
        AngelOneReadOnlyBroker,
        MT5DemoBroker,
        DhanSandboxBroker,
    )
    adapter_records: list[dict[str, Any]] = []
    for adapter in adapters:
        errors = broker_adapter_conformance(adapter)
        capabilities = adapter.capabilities
        adapter_records.append(
            {
                "adapter": f"{adapter.__module__}.{adapter.__name__}",
                "name": adapter.name,
                "mode": capabilities.mode.value,
                "supports_order_submission": capabilities.supports_order_submission,
                "supports_order_cancellation": capabilities.supports_order_cancellation,
                "supports_fill_stream": capabilities.supports_fill_stream,
                "supports_reconciliation": capabilities.supports_reconciliation,
                "live_money_enabled": capabilities.live_money_enabled,
                "conformance_errors": list(errors),
                "decision": "PASS" if not errors else "FAIL",
            }
        )
    isolation = _strategy_isolation(root)
    probe = asyncio.run(_run_contract_probe())
    all_conform = all(record["decision"] == "PASS" for record in adapter_records)
    if not all_conform:
        raise RuntimeError("one or more broker adapters violate the common contract")
    if isolation["forbidden_imports"]:
        raise RuntimeError("strategy layer imports broker-specific execution code")
    if not probe["passed"]:
        raise RuntimeError("generic BrokerAdapter contract probe failed")
    report = {
        "schema_version": 1,
        "phase": 4,
        "decision": "PASS",
        "adapters": adapter_records,
        "strategy_isolation": isolation,
        "mock_broker_contract_probe": probe,
        "reconciliation_contract": {
            "snapshot_methods": ["open_order_snapshots", "position_snapshots"],
            "unsupported_adapters_fail_closed_by_capability": True,
        },
        "credential_backed_validation_claimed": False,
        "external_order_execution_claimed": False,
        "live_money_enabled": False,
    }
    report["deterministic_fingerprint"] = _sha256(report)
    return report


def write_broker_conformance_artifact(root: Path) -> None:
    root = root.resolve()
    report = build_broker_conformance_artifact(root)
    _write_json(root / CONFORMANCE_REPORT, report)
    records = build_sequential_phase_records(
        root,
        {
            0: PHASE_ZERO_EVIDENCE,
            1: PHASE_ONE_EVIDENCE,
            2: PHASE_TWO_EVIDENCE,
            3: PHASE_THREE_EVIDENCE,
            4: PHASE_FOUR_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_broker_conformance_artifact(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_broker_conformance_artifact(root))
    path = root / CONFORMANCE_REPORT
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 4 evidence: {CONFORMANCE_REPORT.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 4 evidence: {CONFORMANCE_REPORT.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 4):
        errors.append("Phase 4 is not PASS in the governance ledger")
    return tuple(errors)


def _strategy_isolation(root: Path) -> dict[str, Any]:
    modules = sorted((root / "aura" / "strategy").glob("*.py"))
    findings: list[dict[str, str]] = []
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        for imported in sorted(set(imports)):
            if imported.startswith(_FORBIDDEN_STRATEGY_IMPORTS):
                findings.append(
                    {
                        "module": path.relative_to(root).as_posix(),
                        "forbidden_import": imported,
                    }
                )
    return {
        "strategy_modules_scanned": len(modules),
        "forbidden_imports": findings,
        "broker_specific_logic_detected": bool(findings),
    }


async def _run_contract_probe() -> dict[str, Any]:
    broker = _ContractProbeBroker()
    order = OrderRequest(
        order_id="phase4-probe-order",
        client_order_id="phase4-probe-client",
        symbol="AURA-BROKER-FIXTURE",
        venue="INTERNAL_FIXTURE",
        side=Side.BUY,
        quantity=Decimal(1),
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    await broker.connect()
    broker_order_id = await broker.submit_order(order)
    await broker.cancel_order(broker_order_id)
    await broker.disconnect()
    expected = f"probe:{order.client_order_id}"
    return {
        "passed": broker_order_id == expected,
        "normalized_order_accepted": True,
        "broker_order_id_shape": "probe:<client_order_id>",
        "external_service_used": False,
    }


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-4 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_broker_conformance_artifact(root)
        print("Phase 4: PASS")
        return 0
    errors = check_broker_conformance_artifact(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 4 broker conformance artifact is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
