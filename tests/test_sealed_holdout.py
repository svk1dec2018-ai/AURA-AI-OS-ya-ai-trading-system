import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aura.persistence.wal import CorruptWalError
from aura.research.holdout import (
    HoldoutError,
    SealedHoldoutPlan,
    SealedHoldoutRegistry,
    SealedHoldoutResult,
)
from aura.research.manifest import DatasetArtifact, ExperimentManifest


def _manifest(*, strategy_hash: str = "s" * 64) -> ExperimentManifest:
    dataset = DatasetArtifact(
        dataset_id="xauusd-1m-2020-2024",
        source="licensed-historical-store",
        content_hash="d" * 64,
        symbols=("XAUUSD",),
        timeframes=("1m",),
        start_at=datetime(2020, 1, 1, tzinfo=UTC),
        end_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    return ExperimentManifest.build(
        experiment_id=f"experiment-{strategy_hash[0]}",
        strategy_id="xau-scalper",
        strategy_version="1.0.0",
        strategy_content_hash=strategy_hash,
        datasets=(dataset,),
        configuration={"fast_ema": 8, "slow_ema": 21},
        execution_assumptions={"fee_bps": 2, "slippage_bps": 5},
        code_revision="git:abc123",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _plan(
    manifest: ExperimentManifest,
    *,
    plan_id: str = "holdout-001",
    declared_at: datetime = datetime(2026, 1, 2, tzinfo=UTC),
) -> SealedHoldoutPlan:
    return SealedHoldoutPlan.build(
        plan_id=plan_id,
        manifest=manifest,
        dataset_id="xauusd-1m-2020-2024",
        calibration_end_at=datetime(2023, 1, 1, tzinfo=UTC),
        holdout_start_at=datetime(2023, 2, 1, tzinfo=UTC),
        holdout_end_at=datetime(2025, 1, 1, tzinfo=UTC),
        evaluation_protocol={
            "max_drawdown_pct": 20.0,
            "min_observations": 100,
            "primary_metric": "net_return_pct",
        },
        declared_at=declared_at,
    )


def _result(
    plan: SealedHoldoutPlan,
    *,
    artifact_hash: str = "a" * 64,
    evaluated_at: datetime = datetime(2026, 1, 3, tzinfo=UTC),
) -> SealedHoldoutResult:
    return SealedHoldoutResult.build(
        plan,
        artifact_hash=artifact_hash,
        observations=500,
        metrics={"max_drawdown_pct": 8.5, "net_return_pct": 12.3},
        evaluated_at=evaluated_at,
    )


def test_seal_and_single_result_survive_restart(tmp_path: Path) -> None:
    manifest = _manifest()
    plan = _plan(manifest)
    result = _result(plan)
    journal = tmp_path / "sealed-holdout.jsonl"
    registry = SealedHoldoutRegistry(journal)

    assert registry.seal(plan)
    assert not registry.seal(plan)
    assert registry.record_result(result)
    assert not registry.record_result(result)
    assert registry.is_consumed(plan.seal_hash)

    recovered = SealedHoldoutRegistry(journal)
    assert recovered.recovered_events == 2
    assert recovered.get_plan(plan.plan_id) == plan
    assert recovered.get_result(plan.seal_hash) == result

    artifact = result.to_research_artifact()
    assert artifact.belongs_to(manifest)
    assert artifact.metadata["historical_research_only"] is True
    assert artifact.metadata["paper_validated"] is False
    assert artifact.metadata["live_approved"] is False
    assert artifact.metadata["live_money_enabled"] is False


def test_same_chronological_slice_cannot_be_reused_for_another_candidate(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "sealed-holdout.jsonl"
    registry = SealedHoldoutRegistry(journal)
    first = _plan(_manifest(strategy_hash="a" * 64), plan_id="candidate-a")
    second = _plan(_manifest(strategy_hash="b" * 64), plan_id="candidate-b")

    assert registry.seal(first)
    recovered = SealedHoldoutRegistry(journal)
    with pytest.raises(HoldoutError, match="slice is already claimed"):
        recovered.seal(second)


def test_consumed_holdout_rejects_a_different_second_result(tmp_path: Path) -> None:
    registry = SealedHoldoutRegistry(tmp_path / "sealed-holdout.jsonl")
    plan = _plan(_manifest())
    first = _result(plan)
    second = _result(plan, artifact_hash="b" * 64)
    registry.seal(plan)
    registry.record_result(first)

    with pytest.raises(HoldoutError, match="already been consumed"):
        registry.record_result(second)


def test_result_must_match_seal_and_be_evaluated_after_declaration(tmp_path: Path) -> None:
    registry = SealedHoldoutRegistry(tmp_path / "sealed-holdout.jsonl")
    plan = _plan(_manifest())
    registry.seal(plan)

    wrong_strategy = _result(plan).model_copy(update={"strategy_content_hash": "f" * 64})
    with pytest.raises(HoldoutError, match="does not match"):
        registry.record_result(wrong_strategy)

    premature = SealedHoldoutResult.build(
        plan,
        artifact_hash="a" * 64,
        observations=500,
        metrics={"net_return_pct": 12.3},
        evaluated_at=plan.declared_at - timedelta(seconds=1),
    )
    with pytest.raises(HoldoutError, match="does not match"):
        registry.record_result(premature)

    future_plan = _plan(
        _manifest(strategy_hash="f" * 64),
        plan_id="future-plan",
        declared_at=datetime.now(UTC) + timedelta(days=1),
    )
    with pytest.raises(HoldoutError, match="declaration cannot be in the future"):
        registry.seal(future_plan)

    future_result = _result(plan, evaluated_at=datetime.now(UTC) + timedelta(days=1))
    with pytest.raises(HoldoutError, match="evaluation cannot be in the future"):
        registry.record_result(future_result)


def test_invalid_boundaries_and_non_numeric_metrics_fail_closed() -> None:
    manifest = _manifest()
    tampered_manifest = manifest.model_copy(
        update={"configuration": {"fast_ema": 99, "slow_ema": 100}}
    )
    with pytest.raises(HoldoutError, match="invalid experiment manifest"):
        _plan(tampered_manifest)

    with pytest.raises(HoldoutError, match="boundaries"):
        SealedHoldoutPlan.build(
            plan_id="leaky-plan",
            manifest=manifest,
            dataset_id="xauusd-1m-2020-2024",
            calibration_end_at=datetime(2024, 1, 1, tzinfo=UTC),
            holdout_start_at=datetime(2023, 1, 1, tzinfo=UTC),
            holdout_end_at=datetime(2025, 1, 1, tzinfo=UTC),
            evaluation_protocol={"metric": "return"},
            declared_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    with pytest.raises(HoldoutError, match="dataset tail"):
        SealedHoldoutPlan.build(
            plan_id="cherry-picked-window",
            manifest=manifest,
            dataset_id="xauusd-1m-2020-2024",
            calibration_end_at=datetime(2023, 1, 1, tzinfo=UTC),
            holdout_start_at=datetime(2023, 2, 1, tzinfo=UTC),
            holdout_end_at=datetime(2024, 12, 1, tzinfo=UTC),
            evaluation_protocol={"metric": "return"},
            declared_at=datetime(2026, 1, 2, tzinfo=UTC),
        )

    plan = _plan(manifest)
    with pytest.raises(TypeError, match="numeric"):
        SealedHoldoutResult.build(
            plan,
            artifact_hash="a" * 64,
            observations=500,
            metrics={"net_return_pct": "12.3"},  # type: ignore[dict-item]
            evaluated_at=datetime(2026, 1, 3, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="finite"):
        SealedHoldoutResult.build(
            plan,
            artifact_hash="a" * 64,
            observations=500,
            metrics={"net_return_pct": float("nan")},
            evaluated_at=datetime(2026, 1, 3, tzinfo=UTC),
        )


def test_corrupt_or_semantically_rewritten_journal_cannot_recover(tmp_path: Path) -> None:
    checksum_journal = tmp_path / "checksum.jsonl"
    checksum_registry = SealedHoldoutRegistry(checksum_journal)
    checksum_registry.seal(_plan(_manifest()))
    records = [json.loads(line) for line in checksum_journal.read_text().splitlines()]
    records[-1]["checksum"] = "0" * 64
    checksum_journal.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    with pytest.raises(CorruptWalError, match="checksum mismatch"):
        SealedHoldoutRegistry(checksum_journal)

    semantic_journal = tmp_path / "semantic.jsonl"
    semantic_registry = SealedHoldoutRegistry(semantic_journal)
    semantic_registry.seal(_plan(_manifest()))
    records = [json.loads(line) for line in semantic_journal.read_text().splitlines()]
    plan_record = records[-1]
    plan_record["event"]["payload"]["plan"]["dataset_id"] = "rewritten-dataset"
    canonical_event = json.dumps(
        plan_record["event"],
        separators=(",", ":"),
        sort_keys=True,
    )
    plan_record["checksum"] = hashlib.sha256(canonical_event.encode()).hexdigest()
    semantic_journal.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    with pytest.raises(HoldoutError, match="invalid holdout plan event"):
        SealedHoldoutRegistry(semantic_journal)
