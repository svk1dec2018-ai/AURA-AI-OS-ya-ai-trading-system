import json
import sys

import pytest
from pydantic import ValidationError

from aura.aura2.external_artifact import ExternalResearchArtifact, ExternalResearchIntake
from aura.aura2.sidecar import ResearchSidecarRunner, SidecarRequest, SidecarSpec


def _artifact_payload(*, source: str = "qlib", profit_factor: float = 1.6) -> dict:
    return {
        "schema_version": 1,
        "source": source,
        "candidate_id": "xau-mtf-001",
        "hypothesis": "M1/M5 execution aligned with H1/H4 trend",
        "metrics": {
            "trades": 640,
            "profit_factor": profit_factor,
            "max_drawdown": 0.08,
            "expectancy_r": 0.17,
        },
        "out_of_sample": True,
        "walk_forward": True,
        "research_only": True,
        "live_approved": False,
        "execution_authority": False,
        "risk_authority": False,
        "metadata": {"dataset": "sealed-oos"},
    }


def test_external_artifact_enters_validation_without_execution_authority() -> None:
    artifact, decision = ExternalResearchIntake().ingest(_artifact_payload())
    assert artifact.source == "qlib"
    assert len(artifact.artifact_hash) == 64
    assert decision.accepted_for_aura_validation is True
    assert decision.granted_execution_authority is False
    assert decision.granted_risk_authority is False
    assert decision.stage == "RESEARCH"


def test_external_artifact_cannot_claim_live_or_execution_authority() -> None:
    payload = _artifact_payload()
    payload["execution_authority"] = True
    with pytest.raises(ValidationError):
        ExternalResearchArtifact.model_validate(payload)

    payload = _artifact_payload()
    payload["live_approved"] = True
    with pytest.raises(ValidationError):
        ExternalResearchArtifact.model_validate(payload)


def test_weak_external_artifact_is_valid_but_rejected_by_evidence_gate() -> None:
    payload = _artifact_payload(profit_factor=0.85)
    artifact, decision = ExternalResearchIntake().ingest(payload)
    assert artifact.candidate_id == "xau-mtf-001"
    assert decision.accepted_for_aura_validation is False
    assert "profit_factor_below_gate" in decision.reasons


def test_sidecar_spec_rejects_broker_credential_environment_names() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        SidecarSpec(
            project_key="qlib",
            command=(sys.executable, "-c", "print('{}')"),
            allowed_env_keys=("PATH", "AURA_MT5_LOGIN"),
        )


def test_sidecar_runner_accepts_normalized_free_research_process() -> None:
    script = """
import json
import sys

request = json.load(sys.stdin)
result = {
    "schema_version": 1,
    "source": request["project"],
    "candidate_id": request["request_id"],
    "hypothesis": request["objective"],
    "metrics": {
        "trades": 500,
        "profit_factor": 1.45,
        "max_drawdown": 0.09,
        "expectancy_r": 0.12
    },
    "out_of_sample": True,
    "walk_forward": True,
    "research_only": True,
    "live_approved": False,
    "execution_authority": False,
    "risk_authority": False,
    "metadata": {"engine": "test-sidecar"}
}
json.dump(result, sys.stdout)
"""
    spec = SidecarSpec(
        project_key="qlib",
        command=(sys.executable, "-c", script),
        timeout_seconds=10.0,
    )
    request = SidecarRequest(
        request_id="candidate-500",
        objective="Research a robust XAUUSD multi-timeframe trend setup",
        symbol="XAUUSD",
        timeframe="M5",
        context={"market": "MT5_CFD"},
    )
    result = ResearchSidecarRunner().run(spec, request)
    assert result.artifact.candidate_id == "candidate-500"
    assert result.decision.accepted_for_aura_validation is True
    assert result.decision.granted_execution_authority is False
    assert result.decision.granted_risk_authority is False


def test_sidecar_request_never_grants_financial_authority() -> None:
    request = SidecarRequest(
        request_id="authority-check",
        objective="research",
        symbol="EURUSD",
        timeframe="M15",
        context={},
    )
    payload = json.loads(request.to_json("finrl_x"))
    assert payload["research_only"] is True
    assert payload["live_approved"] is False
    assert payload["execution_authority"] is False
    assert payload["risk_authority"] is False
