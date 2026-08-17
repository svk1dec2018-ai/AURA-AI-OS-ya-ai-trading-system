from __future__ import annotations

from datetime import UTC, datetime

from aura.research.manifest import DatasetArtifact, ExperimentManifest, ResearchArtifact


def _dataset() -> DatasetArtifact:
    return DatasetArtifact(
        dataset_id="gold-1m-2020-2024",
        source="trusted-historical-store",
        content_hash="d" * 64,
        symbols=("XAUUSD",),
        timeframes=("1m",),
        start_at=datetime(2020, 1, 1, tzinfo=UTC),
        end_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def _manifest(*, slippage_bps: int = 5) -> ExperimentManifest:
    return ExperimentManifest.build(
        experiment_id="experiment-001",
        strategy_id="xau-scalper",
        strategy_version="1.0.0",
        strategy_content_hash="s" * 64,
        datasets=(_dataset(),),
        configuration={"fast_ema": 8, "slow_ema": 21},
        execution_assumptions={"fee_bps": 2, "slippage_bps": slippage_bps},
        code_revision="git:abc123",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_identical_experiment_inputs_produce_same_manifest_hash() -> None:
    first = _manifest()
    second = _manifest()
    assert first.verify()
    assert second.verify()
    assert first.manifest_hash == second.manifest_hash


def test_execution_assumption_change_changes_experiment_identity() -> None:
    baseline = _manifest(slippage_bps=5)
    stressed = _manifest(slippage_bps=15)
    assert baseline.manifest_hash != stressed.manifest_hash


def test_research_artifact_is_bound_to_exact_manifest() -> None:
    manifest = _manifest()
    artifact = ResearchArtifact(
        artifact_type="walk_forward",
        content_hash="w" * 64,
        experiment_manifest_hash=manifest.manifest_hash,
        metadata={"folds": 12},
    )
    assert artifact.belongs_to(manifest)
    assert not artifact.belongs_to(_manifest(slippage_bps=20))
