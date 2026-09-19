from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aura.ai.openai_responses import StructuredResponse
from aura.maintenance.authority import (
    AuthorityAction,
    AuthorityDeniedError,
    AuthorityRole,
    DevelopmentAuthorityPolicy,
)
from aura.maintenance.models import ChangeRisk, MaintenanceSeverity, SystemObservation
from aura.maintenance.monitor import MaintenanceMonitor
from aura.maintenance.openai_developer import (
    AIMaintenanceDeveloper,
    OpenAIMaintenanceDeveloper,
)
from aura.ops.health import ComponentHealth, HealthReport, HealthStatus


class _FakeClient:
    model_id = "gpt-5.4-mini"

    def __init__(self) -> None:
        self.user_payload: dict | None = None

    async def structured(self, **kwargs) -> StructuredResponse:
        self.user_payload = kwargs["user_payload"]
        return StructuredResponse(
            response_id="resp_repair_1",
            model_id=self.model_id,
            output={
                "diagnosis": "health serialization does not cover the new state",
                "root_cause_hypotheses": ["missing state branch"],
                "proposed_change_summary": "handle the state and add a regression test",
                "changed_files": ["aura/ops/health.py", "tests/test_production_ops.py"],
                "unified_diff": (
                    "diff --git a/aura/ops/health.py b/aura/ops/health.py\n"
                    "--- a/aura/ops/health.py\n"
                    "+++ b/aura/ops/health.py\n"
                    "@@ -1,1 +1,1 @@\n-from __future__ import annotations\n"
                    "+from __future__ import annotations\n"
                    "diff --git a/tests/test_production_ops.py b/tests/test_production_ops.py\n"
                    "--- a/tests/test_production_ops.py\n"
                    "+++ b/tests/test_production_ops.py\n"
                    "@@ -1,1 +1,1 @@\n-from __future__ import annotations\n"
                    "+from __future__ import annotations\n"
                ),
                "validation_rationale": ["regression test", "full suite"],
                "rollback_plan": "reverse the exact patch",
                "residual_risks": ["health adapter integration"],
                "requires_owner_approval": True,
                "touches_financial_core": False,
            },
        )


class _FakeOllamaClient(_FakeClient):
    provider_id = "ollama"
    model_id = "qwen3.5:4b"


def test_owner_and_ai_cannot_move_funds_rewrite_history_or_bypass_risk() -> None:
    policy = DevelopmentAuthorityPolicy()
    immutable = (
        AuthorityAction.ADD_FUNDS,
        AuthorityAction.WITHDRAW_FUNDS,
        AuthorityAction.TRANSFER_FUNDS,
        AuthorityAction.REWRITE_HISTORICAL_FILL,
        AuthorityAction.REWRITE_HISTORICAL_TRADE,
        AuthorityAction.REWRITE_HISTORICAL_PNL,
        AuthorityAction.BYPASS_RISK_ENGINE,
        AuthorityAction.EXPOSE_SECRETS,
        AuthorityAction.SELF_APPROVE_LIVE_DEPLOYMENT,
    )
    for role in AuthorityRole:
        for action in immutable:
            assert policy.decide(role, action).allowed is False
    assert policy.decide(AuthorityRole.OWNER, AuthorityAction.APPROVE_CODE_CHANGE).allowed
    assert not policy.decide(
        AuthorityRole.MAINTENANCE_AI,
        AuthorityAction.APPROVE_CODE_CHANGE,
    ).allowed


def test_monitor_converts_degraded_health_to_deduplicated_incident() -> None:
    observed_at = datetime(2026, 8, 21, 4, 0, tzinfo=UTC)
    report = HealthReport(
        components=(
            ComponentHealth(
                component="market_data",
                status=HealthStatus.DEGRADED,
                detail="feed lag crossed warning threshold",
                observed_at=observed_at,
            ),
        )
    )
    monitor = MaintenanceMonitor()
    first = monitor.observe_health_report(report)
    second = monitor.observe_health_report(report)

    assert len(first) == 1
    assert first[0].severity == MaintenanceSeverity.DEGRADED
    assert first[0].evidence["ready_for_new_risk"] is False
    assert second == ()


@pytest.mark.asyncio
async def test_openai_developer_only_returns_sanitized_owner_gated_proposal() -> None:
    client = _FakeClient()
    developer = OpenAIMaintenanceDeveloper(client)  # type: ignore[arg-type]
    observation = SystemObservation(
        observation_id="incident:test",
        component="health",
        severity=MaintenanceSeverity.DEGRADED,
        summary="API_KEY=secret-value failed",
        symptoms=("Bearer sensitive-token-value",),
        evidence={"password": "password=hunter2"},
        observed_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
    )
    proposal = await developer.propose_repair(
        observation=observation,
        base_commit="a" * 40,
        relevant_files={
            "aura/ops/health.py": "API_KEY=secret-value\nclass Health: pass",
        },
    )

    assert proposal.provider_id == "openai"
    assert proposal.risk == ChangeRisk.STANDARD
    assert proposal.owner_approval_required is True
    assert proposal.auto_apply_allowed is False
    assert proposal.live_deploy_allowed is False
    assert client.user_payload is not None
    serialized = str(client.user_payload)
    assert "secret-value" not in serialized
    assert "hunter2" not in serialized


@pytest.mark.asyncio
async def test_free_local_developer_uses_identical_owner_gated_authority() -> None:
    client = _FakeOllamaClient()
    developer = AIMaintenanceDeveloper(client)
    observation = SystemObservation(
        observation_id="incident:local-ai",
        component="health",
        severity=MaintenanceSeverity.DEGRADED,
        summary="health state requires a bounded repair",
        symptoms=("health test failed",),
        evidence={"source": "unit_test"},
        observed_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
    )

    proposal = await developer.propose_repair(
        observation=observation,
        base_commit="b" * 40,
        relevant_files={"aura/ops/health.py": "class Health: pass"},
    )

    assert proposal.provider_id == "ollama"
    assert proposal.model_id == "qwen3.5:4b"
    assert proposal.owner_approval_required is True
    assert proposal.auto_apply_allowed is False
    assert proposal.live_deploy_allowed is False


def test_ai_cannot_approve_its_own_change() -> None:
    with pytest.raises(AuthorityDeniedError):
        DevelopmentAuthorityPolicy().require(
            AuthorityRole.MAINTENANCE_AI,
            AuthorityAction.APPROVE_CODE_CHANGE,
        )
