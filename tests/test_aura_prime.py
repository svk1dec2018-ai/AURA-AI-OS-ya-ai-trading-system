from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aura.domain.models import SignalIntent
from aura.prime.contracts import PrimeEvent, PrimeEventKind
from aura.prime.ensemble import ModelVote, PrimeModelEnsemble, VoteQuality
from aura.prime.memory import DuckDBUnavailable, PrimeTradeMemory
from aura.prime.model_artifacts import (
    ModelArtifact,
    ModelArtifactStage,
    ModelArtifactStore,
)
from aura.prime.providers import PRIME_PROVIDERS, ProviderReadiness, provider_matrix
from aura.prime.repair import RepairAction, SafeAutoRepair
from aura.prime.status import prime_status


def test_prime_event_rejects_future_observation() -> None:
    received = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="received before observation"):
        PrimeEvent(
            kind=PrimeEventKind.MARKET,
            source="fixture",
            observed_at=received + timedelta(seconds=1),
            received_at=received,
        )


def test_prime_event_restricts_financial_authority() -> None:
    now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="financial authority"):
        PrimeEvent(
            kind=PrimeEventKind.MODEL,
            source="model",
            observed_at=now,
            received_at=now,
            execution_authority=True,
        )


def test_provider_matrix_never_exposes_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("AURA_DHAN_CLIENT_ID", "private-client")
    monkeypatch.setenv("AURA_DHAN_ACCESS_TOKEN", "private-token")
    matrix = provider_matrix()
    rendered = repr(matrix)
    assert "private-client" not in rendered
    assert "private-token" not in rendered
    dhan = next(item for item in matrix if item["provider_id"] == "dhan")
    assert dhan["configured"] is True
    assert dhan["missing_env"] == []
    assert PRIME_PROVIDERS["coinbase"].readiness() is ProviderReadiness.PUBLIC_READY


def test_model_artifact_store_is_append_only_and_collision_safe(tmp_path: Path) -> None:
    store = ModelArtifactStore(tmp_path / "models")
    artifact = ModelArtifact(
        model_key="xgb:gold",
        version="v1",
        stage=ModelArtifactStage.CHALLENGER,
        framework="xgboost",
        task="setup_probability",
        markets=("XAUUSD",),
        training_data_fingerprint="1" * 64,
        feature_schema_fingerprint="2" * 64,
        artifact_sha256="3" * 64,
        metrics={"brier": 0.18},
    )
    store.register(artifact)
    store.register(artifact)
    assert store.all() == (artifact,)
    assert store.latest("xgb:gold") == artifact

    changed = artifact.model_copy(update={"metrics": {"brier": 0.15}})
    with pytest.raises(ValueError, match="collision"):
        store.register(changed)


def test_prime_ensemble_is_weighted_and_fail_closed() -> None:
    ensemble = PrimeModelEnsemble(min_models=2, min_directional_margin=0.1)
    result = ensemble.decide(
        (
            ModelVote(
                model_key="xgb",
                intent=SignalIntent.LONG,
                confidence=0.85,
                reliability=0.9,
                calibration=0.9,
            ),
            ModelVote(
                model_key="lgbm",
                intent=SignalIntent.LONG,
                confidence=0.70,
                reliability=0.8,
                calibration=0.8,
            ),
            ModelVote(
                model_key="research-lstm",
                intent=SignalIntent.SHORT,
                confidence=0.99,
                reliability=0.9,
                calibration=0.9,
                research_only=True,
            ),
        )
    )
    assert result.intent is SignalIntent.LONG
    assert result.quality is VoteQuality.READY
    assert result.execution_authority is False

    conflicted = ensemble.decide(
        (
            ModelVote(model_key="a", intent=SignalIntent.LONG, confidence=0.5),
            ModelVote(model_key="b", intent=SignalIntent.SHORT, confidence=0.5),
        )
    )
    assert conflicted.intent is SignalIntent.FLAT
    assert conflicted.quality is VoteQuality.CONFLICTED


def test_safe_auto_repair_never_mutates_financial_components() -> None:
    repair = SafeAutoRepair()
    result = repair.plan(component="risk", error_type="runtime")
    assert result.action is RepairAction.OPEN_MAINTENANCE_PROPOSAL
    assert result.requires_owner_approval is True
    assert result.repaired is False


def test_prime_status_keeps_live_money_gated() -> None:
    root = Path(__file__).resolve().parents[1]
    status = prime_status(root)
    assert status["architecture"] == "AURA_PRIME_V1"
    assert status["software_production_ready"] is True
    assert status["live_money_eligible"] is False
    assert status["hard_boundaries"]["fund_movement"] is False
    assert status["hard_boundaries"]["risk_bypass"] is False


def test_trade_memory_fails_with_clear_message_without_optional_dependency(
    tmp_path: Path,
) -> None:
    try:
        memory = PrimeTradeMemory(tmp_path / "events.duckdb")
    except DuckDBUnavailable as exc:
        assert "analytics optional dependency" in str(exc)
    else:
        memory.close()


def test_trade_memory_roundtrip_when_duckdb_is_installed(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    memory = PrimeTradeMemory(tmp_path / "events.duckdb")
    now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    event = PrimeEvent(
        event_id="prime-event-1",
        correlation_id="corr-1",
        kind=PrimeEventKind.MARKET,
        source="test",
        market="FOREX",
        symbol="XAUUSD",
        observed_at=now,
        received_at=now,
        payload={"price": 2600.0},
    )
    memory.append(event)
    memory.append(event)
    assert memory.count() == 1
    recent = memory.recent(limit=10)
    assert recent[0]["event_id"] == "prime-event-1"
    assert recent[0]["payload"]["price"] == 2600.0
    memory.close()
