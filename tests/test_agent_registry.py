from datetime import UTC, datetime

import pytest

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.registry import AgentRegistry
from aura.domain.models import SignalIntent


class _Agent(SpecialistAgent):
    agent_id = "technical-test"
    role = AgentRole.TECHNICAL

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raise NotImplementedError


def _evidence(**updates) -> AgentEvidence:
    values = {
        "agent_id": "technical-test",
        "role": AgentRole.TECHNICAL,
        "intent": SignalIntent.FLAT,
        "confidence": 0.5,
        "thesis": "structured advisory output",
        "sources": (
            EvidenceSource(
                source_id="fixture",
                source_type=EvidenceSourceType.INTERNAL_MEMORY,
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                trust_score=1.0,
            ),
        ),
        "generated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(updates)
    return AgentEvidence(**values)


def test_registry_manifest_is_advisory_and_schema_bound() -> None:
    agent = _Agent()
    registry = AgentRegistry.from_agents((agent,))

    registration = registry.registration_for(agent.agent_id)
    assert registration.output_schema.endswith("AgentEvidence")
    assert registration.authority == "advisory_only"
    assert registration.broker_access is False
    assert registry.validate_evidence(agent, _evidence()) == _evidence()


def test_registry_rejects_non_schema_or_mismatched_output() -> None:
    agent = _Agent()
    registry = AgentRegistry.from_agents((agent,))

    with pytest.raises(TypeError, match="AgentEvidence schema"):
        registry.validate_evidence(agent, {"intent": "LONG"})
    with pytest.raises(ValueError, match="mismatched identity/role"):
        registry.validate_evidence(agent, _evidence(agent_id="different"))
