from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.domain.models import OrderRequest, PortfolioSnapshot, Side
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE
from aura.risk.engine import RiskEngine, RiskLimits
from aura.risk.overlays import StatisticalRiskLimits, StatisticalRiskOverlay
from aura.risk.statistics import StressScenario, evaluate_stress_scenarios

OUTPUT_DIR = Path("artifacts/governance")
STRESS_REPORT = OUTPUT_DIR / "risk_stress_test_report.json"
VIOLATION_LOGS = OUTPUT_DIR / "risk_violation_simulation_logs.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_THREE_EVIDENCE = {
    "Risk stress test report": STRESS_REPORT.as_posix(),
    "Violation simulation logs": VIOLATION_LOGS.as_posix(),
}
_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def build_risk_engine_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    stress_results = evaluate_stress_scenarios(
        position_values={
            "AURA-XAU-FIXTURE": Decimal(50000),
            "AURA-BTC-FIXTURE": Decimal(-20000),
        },
        equity=Decimal(100000),
        scenarios=(
            StressScenario(
                name="cross_asset_adverse",
                shocks_pct={
                    "AURA-XAU-FIXTURE": Decimal(-10),
                    "AURA-BTC-FIXTURE": Decimal(20),
                },
            ),
            StressScenario(
                name="gold_gap",
                shocks_pct={"AURA-XAU-FIXTURE": Decimal(-12)},
            ),
        ),
    )
    stress_report = {
        "schema_version": 1,
        "phase": 3,
        "decision": "PASS",
        "fixture_type": "deterministic_internal_risk_fixture",
        "market_data_claimed": False,
        "equity": "100000",
        "results": [result.model_dump(mode="json") for result in stress_results],
        "worst_loss_pct": str(max(result.loss_pct_of_equity for result in stress_results)),
        "deterministic_fingerprint": _sha256(
            [result.model_dump(mode="json") for result in stress_results]
        ),
        "live_money_enabled": False,
    }
    violations = _violation_cases(stress_results)
    replayed = _violation_cases(stress_results)
    if violations != replayed:
        raise RuntimeError("risk engine outputs changed across identical evaluations")
    violation_logs = {
        "schema_version": 1,
        "phase": 3,
        "decision": "PASS",
        "policy": {
            "max_risk_per_trade_pct": "1.5",
            "max_daily_loss_pct": "3",
            "max_drawdown_pct": "6",
            "max_gross_exposure_pct": "100",
            "max_symbol_exposure_pct": "30",
        },
        "cases": violations,
        "all_new_risk_violations_vetoed": all(
            not item["approved"] for item in violations if item["expected"] == "VETO"
        ),
        "risk_reduction_preserved_under_kill_switch": any(
            item["case"] == "kill_switch_allows_flattening" and item["approved"]
            for item in violations
        ),
        "deterministic_replay_matches": True,
        "ai_override_authority": False,
        "strategy_promotion_authority": False,
        "live_money_enabled": False,
    }
    if not violation_logs["all_new_risk_violations_vetoed"]:
        raise RuntimeError("a mandatory risk violation bypassed the risk engine")
    return stress_report, violation_logs


def write_risk_engine_artifacts(root: Path) -> None:
    root = root.resolve()
    stress, violations = build_risk_engine_artifacts()
    _write_json(root / STRESS_REPORT, stress)
    _write_json(root / VIOLATION_LOGS, violations)
    records = build_sequential_phase_records(
        root,
        {
            0: PHASE_ZERO_EVIDENCE,
            1: PHASE_ONE_EVIDENCE,
            2: PHASE_TWO_EVIDENCE,
            3: PHASE_THREE_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_risk_engine_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    stress, violations = build_risk_engine_artifacts()
    expected = {
        STRESS_REPORT: _pretty_json(stress),
        VIOLATION_LOGS: _pretty_json(violations),
    }
    errors: list[str] = []
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing Phase 3 evidence: {relative.as_posix()}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"stale Phase 3 evidence: {relative.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 3):
        errors.append("Phase 3 is not PASS in the governance ledger")
    return tuple(errors)


def _violation_cases(stress_results: tuple[Any, ...]) -> list[dict[str, Any]]:
    limits = RiskLimits(
        max_order_notional_pct=Decimal(100),
        max_risk_per_trade_pct=Decimal("1.5"),
        max_gross_exposure_pct=Decimal(100),
        max_symbol_exposure_pct=Decimal(30),
        max_drawdown_pct=Decimal(6),
        max_daily_loss_pct=Decimal(3),
    )
    opening = _order("opening", Side.BUY, "1000")
    cases: list[dict[str, Any]] = []

    sized = RiskEngine(limits).evaluate(
        opening,
        Decimal(100),
        _portfolio(equity="100000"),
        Decimal(100000),
        protective_stop_price=Decimal(95),
    )
    cases.append(_case("stop_risk_sizes_quantity", "SIZE", sized))

    missing_stop = RiskEngine(limits).evaluate(
        opening, Decimal(100), _portfolio(), Decimal(100000)
    )
    cases.append(_case("missing_protective_stop", "VETO", missing_stop))

    drawdown = RiskEngine(limits).evaluate(
        opening,
        Decimal(100),
        _portfolio(drawdown="6"),
        Decimal(100000),
        protective_stop_price=Decimal(95),
    )
    cases.append(_case("drawdown_limit", "VETO", drawdown))

    daily = RiskEngine(limits).evaluate(
        opening,
        Decimal(100),
        _portfolio(equity="97000", peak="100000", drawdown="3"),
        Decimal(100000),
        protective_stop_price=Decimal(95),
    )
    cases.append(_case("daily_loss_limit", "VETO", daily))

    gross = RiskEngine(limits).evaluate(
        opening,
        Decimal(100),
        _portfolio(gross="100000"),
        Decimal(100000),
        protective_stop_price=Decimal(95),
    )
    cases.append(_case("gross_exposure_limit", "VETO", gross))

    symbol = RiskEngine(limits).evaluate(
        opening,
        Decimal(100),
        _portfolio(position_values={opening.symbol: Decimal(30000)}),
        Decimal(100000),
        protective_stop_price=Decimal(95),
    )
    cases.append(_case("symbol_exposure_limit", "VETO", symbol))

    killed = RiskEngine(limits)
    killed.engage_kill_switch("phase-3 validation")
    kill_veto = killed.evaluate(
        opening,
        Decimal(100),
        _portfolio(),
        Decimal(100000),
        protective_stop_price=Decimal(95),
    )
    cases.append(_case("kill_switch_veto", "VETO", kill_veto))
    flatten = killed.evaluate(
        _order("flatten", Side.SELL, "5"),
        Decimal(100),
        _portfolio(gross="500", position_values={opening.symbol: Decimal(500)}),
        Decimal(100000),
        current_position_quantity=Decimal(5),
    )
    cases.append(_case("kill_switch_allows_flattening", "ALLOW_REDUCTION", flatten))

    overlay = StatisticalRiskOverlay(StatisticalRiskLimits(max_stress_loss_pct=6.0))
    from aura.risk.statistics import StatisticalRiskMetrics

    overlay.update(
        StatisticalRiskMetrics(
            observed_at=_NOW,
            samples=100,
            confidence=0.95,
            historical_var_pct=1,
            historical_cvar_pct=2,
            parametric_var_pct=1,
            annualized_volatility_pct=20,
            max_drawdown_pct=3,
        ),
        stress_results=stress_results,
    )
    stress_veto = RiskEngine(limits, overlays=(overlay,)).evaluate(
        opening,
        Decimal(100),
        _portfolio(),
        Decimal(100000),
        protective_stop_price=Decimal(95),
    )
    cases.append(_case("stress_overlay_veto", "VETO", stress_veto))
    return cases


def _case(name: str, expected: str, decision: Any) -> dict[str, Any]:
    return {
        "case": name,
        "expected": expected,
        "approved": decision.approved,
        "requested_quantity": str(decision.requested_quantity),
        "approved_quantity": str(decision.approved_quantity),
        "reason": decision.reason,
    }


def _order(order_id: str, side: Side, quantity: str) -> OrderRequest:
    return OrderRequest(
        order_id=order_id,
        client_order_id=f"client-{order_id}",
        symbol="AURA-RISK-FIXTURE",
        venue="INTERNAL_FIXTURE",
        side=side,
        quantity=Decimal(quantity),
        created_at=_NOW,
    )


def _portfolio(
    *,
    equity: str = "100000",
    gross: str = "0",
    peak: str | None = None,
    drawdown: str = "0",
    position_values: dict[str, Decimal] | None = None,
) -> PortfolioSnapshot:
    equity_value = Decimal(equity)
    peak_value = Decimal(peak) if peak is not None else equity_value
    return PortfolioSnapshot(
        cash=equity_value,
        equity=equity_value,
        gross_exposure=Decimal(gross),
        net_exposure=Decimal(0),
        realized_pnl=Decimal(0),
        unrealized_pnl=Decimal(0),
        peak_equity=peak_value,
        drawdown_pct=Decimal(drawdown),
        position_values=position_values or {},
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-3 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_risk_engine_artifacts(root)
        print("Phase 3: PASS")
        return 0
    errors = check_risk_engine_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 3 risk-engine artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
