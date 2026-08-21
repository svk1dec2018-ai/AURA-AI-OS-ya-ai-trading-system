from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aura.evolution.core import CandidateEvaluation, FitnessPolicy, PerformanceSlice, StrategyGenome
from aura.ops.backtest_gate import PHASE_SIX_EVIDENCE
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.market_data_gate import PHASE_FIVE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.risk_engine_gate import PHASE_THREE_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE
from aura.research.hypothesis_generator import (
    DeterministicHypothesisGenerator,
    HypothesisRequest,
)
from aura.research.lifecycle import ActorType, GovernanceError, StrategyGovernance, StrategyStage
from aura.research.strategy_factory import AutonomousStrategyFactory, StrategyFreedomPolicy

OUTPUT_DIR = Path("artifacts/governance")
STRATEGY_REPORT = OUTPUT_DIR / "strategy_evaluation_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_SEVEN_EVIDENCE = {"Strategy evaluation report": STRATEGY_REPORT.as_posix()}

_EVALUATED_AT = datetime(2026, 1, 31, tzinfo=UTC)


def build_strategy_evaluation_report() -> dict[str, Any]:
    request = HypothesisRequest(
        thesis="A closed-candle trend hypothesis should remain stable out of sample.",
        market_scope=("INTERNAL_FIXTURE",),
        timeframe_scope=("15m",),
        provenance="phase-7 deterministic internal fixture",
        source_content_hash=hashlib.sha256(b"phase-7-fixture").hexdigest(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    generator = DeterministicHypothesisGenerator()
    first_hypothesis = generator.generate(request)
    second_hypothesis = generator.generate(request)

    policy = StrategyFreedomPolicy(random_seed=7007)
    first_factory = AutonomousStrategyFactory(policy)
    second_factory = AutonomousStrategyFactory(policy)
    first_strategy = first_factory.register_blueprint(
        first_factory.propose(first_hypothesis, candidate_index=0), candidate_index=0
    )
    second_strategy = second_factory.register_blueprint(
        second_factory.propose(second_hypothesis, candidate_index=0), candidate_index=0
    )
    reproducibility = {
        "hypothesis_id_equal": first_hypothesis.hypothesis_id == second_hypothesis.hypothesis_id,
        "strategy_identity_equal": first_strategy.identity == second_strategy.identity,
        "strategy_content_hash_equal": first_strategy.content_hash == second_strategy.content_hash,
    }
    if not all(reproducibility.values()):
        raise RuntimeError("Phase 7 research generation is not reproducible")

    fitness = FitnessPolicy()
    stable_failures = fitness.research_failures(_evaluation(overfit=False))
    overfit_failures = fitness.research_failures(_evaluation(overfit=True))
    overfit_rejected = bool(overfit_failures) and "unstable_walk_forward" in overfit_failures
    if stable_failures or not overfit_rejected:
        raise RuntimeError("Phase 7 overfitting policy probe failed")

    untested_promotion_blocked = _untested_promotion_is_blocked(first_strategy)
    if not untested_promotion_blocked:
        raise RuntimeError("Phase 7 allowed an untested strategy promotion")

    report: dict[str, Any] = {
        "schema_version": 1,
        "phase": 7,
        "decision": "PASS",
        "fixture_type": "deterministic_internal_research_fixture",
        "components": {
            "hypothesis_generator": (
                "aura.research.hypothesis_generator.DeterministicHypothesisGenerator"
            ),
            "strategy_factory": "aura.research.strategy_factory.AutonomousStrategyFactory",
            "evaluation_policy": "aura.evolution.core.FitnessPolicy",
            "promotion_governance": "aura.research.lifecycle.StrategyGovernance",
        },
        "reproducibility": reproducibility,
        "overfitting_controls": {
            "stable_fixture_failures": list(stable_failures),
            "deliberately_overfit_fixture_failures": list(overfit_failures),
            "overfit_candidate_rejected": overfit_rejected,
        },
        "promotion_controls": {
            "untested_promotion_blocked": untested_promotion_blocked,
            "automatic_paper_promotion_performed": False,
            "automatic_live_promotion_performed": False,
        },
        "claims": {
            "external_market_data_used": False,
            "strategy_performance_claimed": False,
            "broker_execution_claimed": False,
            "live_money_enabled": False,
        },
    }
    report["deterministic_fingerprint"] = _sha256(report)
    return report


def _evaluation(*, overfit: bool) -> CandidateEvaluation:
    in_sample = _slice("in_sample", trades=120, net_return=40.0, expectancy=0.8)
    if overfit:
        folds = (
            _slice("oos_1", trades=30, net_return=-4.0, expectancy=-0.2),
            _slice("oos_2", trades=30, net_return=-2.0, expectancy=-0.1),
            _slice("oos_3", trades=30, net_return=0.5, expectancy=0.02),
        )
    else:
        folds = tuple(
            _slice(f"oos_{index}", trades=30, net_return=2.0 + index, expectancy=0.1)
            for index in range(1, 4)
        )
    return CandidateEvaluation(
        genome=StrategyGenome(
            family="phase7-fixture",
            parameters={"closed_candle_only": 1, "lookback": 20},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        in_sample=in_sample,
        walk_forward=folds,
        monte_carlo_p05_return_pct=-1.0,
        monte_carlo_p95_drawdown_pct=10.0,
        evaluated_at=_EVALUATED_AT,
    )


def _slice(
    label: str, *, trades: int, net_return: float, expectancy: float
) -> PerformanceSlice:
    return PerformanceSlice(
        label=label,
        trades=trades,
        net_return_pct=net_return,
        expectancy_pct=expectancy,
        profit_factor=1.2 if expectancy > 0 else 0.8,
        max_drawdown_pct=8.0,
        sharpe=1.0 if expectancy > 0 else -0.5,
        win_rate=0.55 if expectancy > 0 else 0.4,
        avg_slippage_bps=2.0,
    )


def _untested_promotion_is_blocked(strategy) -> bool:
    try:
        StrategyGovernance().promote(
            strategy, StrategyStage.BACKTEST_VALIDATED, ActorType.SYSTEM
        )
    except GovernanceError as exc:
        return "missing passed evidence" in str(exc)
    return False


def write_strategy_research_artifacts(root: Path) -> None:
    root = root.resolve()
    _write_json(root / STRATEGY_REPORT, build_strategy_evaluation_report())
    records = build_sequential_phase_records(
        root,
        {
            0: PHASE_ZERO_EVIDENCE,
            1: PHASE_ONE_EVIDENCE,
            2: PHASE_TWO_EVIDENCE,
            3: PHASE_THREE_EVIDENCE,
            4: PHASE_FOUR_EVIDENCE,
            5: PHASE_FIVE_EVIDENCE,
            6: PHASE_SIX_EVIDENCE,
            7: PHASE_SEVEN_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_strategy_research_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_strategy_evaluation_report())
    path = root / STRATEGY_REPORT
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 7 evidence: {STRATEGY_REPORT.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 7 evidence: {STRATEGY_REPORT.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 7):
        errors.append("Phase 7 is not PASS in the governance ledger")
    return tuple(errors)


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-7 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_strategy_research_artifacts(root)
        print("Phase 7: PASS")
        return 0
    errors = check_strategy_research_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 7 strategy research artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
