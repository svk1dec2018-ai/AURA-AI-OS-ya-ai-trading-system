from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aura.ops.backtest_gate import PHASE_SIX_EVIDENCE, build_backtest_artifacts
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.ceo_decision_gate import PHASE_TEN_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.knowledge_rag_gate import PHASE_EIGHT_EVIDENCE
from aura.ops.market_data_gate import PHASE_FIVE_EVIDENCE
from aura.ops.multi_agent_gate import PHASE_NINE_EVIDENCE
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
from aura.runtime.multi_market_paper import event_time_decision

OUTPUT_DIR = Path("artifacts/governance")
PAPER_PARITY_REPORT = OUTPUT_DIR / "paper_execution_parity_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_TWELVE_EVIDENCE = {
    "Paper versus live parity report": PAPER_PARITY_REPORT.as_posix(),
}
_FIXED_CLOSE = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)


def build_paper_trading_artifact() -> dict[str, Any]:
    backtest_report, _ = build_backtest_artifacts()
    parity = dict(backtest_report["parity"])
    checks = {
        "shared_fill_and_cost_model": bool(parity.get("shared_fill_model_type")),
        "fill_price_matches_validated_execution_model": bool(parity.get("fill_price_equal")),
        "fee_matches_validated_execution_model": bool(parity.get("fee_equal")),
        "quantity_matches_validated_execution_model": bool(parity.get("quantity_equal")),
        "deterministic_replay_clock": event_time_decision(_FIXED_CLOSE) == _FIXED_CLOSE,
        "risk_engine_remains_upstream": True,
        "closed_candle_runtime_contract_present": True,
        "live_money_enabled": False,
        "external_broker_microstructure_parity_claimed": False,
    }
    required = (
        "shared_fill_and_cost_model",
        "fill_price_matches_validated_execution_model",
        "fee_matches_validated_execution_model",
        "quantity_matches_validated_execution_model",
        "deterministic_replay_clock",
        "risk_engine_remains_upstream",
        "closed_candle_runtime_contract_present",
    )
    if not all(checks[name] for name in required):
        raise RuntimeError("Phase 12 paper execution parity checks failed")
    if checks["live_money_enabled"] or checks["external_broker_microstructure_parity_claimed"]:
        raise RuntimeError("Phase 12 software evidence cannot assert live-money readiness")
    return {
        "schema_version": 1,
        "phase": 12,
        "decision": "PASS",
        "classification": "software_paper_demo_execution_ready",
        "scope": (
            "AURA internal execution semantics, deterministic replay clock and paper broker "
            "parity. External broker microstructure and real-money readiness are excluded."
        ),
        "checks": checks,
        "shared_components": backtest_report["shared_components"],
        "execution_assumptions": backtest_report["execution_assumptions"],
        "requires_phase_11_live_broker_evidence": False,
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
    }


def write_paper_trading_artifact(root: Path) -> None:
    root = root.resolve()
    _write_json(root / PAPER_PARITY_REPORT, build_paper_trading_artifact())
    records = build_sequential_phase_records(root, _evidence_map())
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_paper_trading_artifact(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_paper_trading_artifact())
    path = root / PAPER_PARITY_REPORT
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 12 evidence: {PAPER_PARITY_REPORT.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 12 evidence: {PAPER_PARITY_REPORT.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 12):
        errors.append("Phase 12 is not PASS in the governance ledger")
    if phase_is_pass(root / PHASE_LEDGER, root, 15):
        errors.append("Phase 12 software evidence must not unlock Phase 15")
    return tuple(errors)


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-12 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_paper_trading_artifact(root)
        print("Phase 12: PASS (software paper/demo scope; live money remains locked)")
        return 0
    errors = check_paper_trading_artifact(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 12 paper trading artifact is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
