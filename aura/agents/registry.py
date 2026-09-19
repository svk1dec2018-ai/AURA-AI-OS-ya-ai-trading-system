from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.base import SpecialistAgent
from aura.agents.models import AgentEvidence, AgentRole


class AgentRegistration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(min_length=1)
    role: AgentRole
    implementation: str = Field(min_length=1)
    output_schema: str = "aura.agents.models.AgentEvidence"
    authority: str = "advisory_only"
    broker_access: bool = False
    portfolio_mutation: bool = False
    strategy_approval: bool = False


@dataclass(slots=True, frozen=True)
class AgentRegistry:
    registrations: tuple[AgentRegistration, ...]

    @classmethod
    def from_agents(cls, agents: tuple[SpecialistAgent, ...] | list[SpecialistAgent]) -> AgentRegistry:
        if not agents:
            raise ValueError("agent registry requires at least one specialist")
        registrations: list[AgentRegistration] = []
        seen: set[str] = set()
        for agent in agents:
            if not isinstance(agent, SpecialistAgent):
                raise TypeError("registered agents must implement SpecialistAgent")
            if not isinstance(agent.agent_id, str) or not agent.agent_id.strip():
                raise ValueError("registered agent_id must be a non-empty string")
            if not isinstance(agent.role, AgentRole):
                raise TypeError(f"agent {agent.agent_id} has an invalid role")
            if agent.agent_id in seen:
                raise ValueError("specialist agent_id values must be unique")
            seen.add(agent.agent_id)
            implementation = f"{type(agent).__module__}.{type(agent).__qualname__}"
            registrations.append(
                AgentRegistration(
                    agent_id=agent.agent_id,
                    role=agent.role,
                    implementation=implementation,
                )
            )
        registrations.sort(key=lambda item: (item.role.value, item.agent_id))
        return cls(tuple(registrations))

    @property
    def roles(self) -> frozenset[AgentRole]:
        return frozenset(item.role for item in self.registrations)

    def registration_for(self, agent_id: str) -> AgentRegistration:
        for registration in self.registrations:
            if registration.agent_id == agent_id:
                return registration
        raise KeyError(f"unregistered specialist agent: {agent_id}")

    def validate_evidence(
        self,
        agent: SpecialistAgent,
        evidence: object,
    ) -> AgentEvidence:
        registration = self.registration_for(agent.agent_id)
        if not isinstance(evidence, AgentEvidence):
            raise TypeError(
                f"agent {agent.agent_id} must return the AgentEvidence schema"
            )
        if evidence.agent_id != registration.agent_id or evidence.role != registration.role:
            raise ValueError(
                f"agent {agent.agent_id} returned mismatched identity/role"
            )
        if evidence.execution_authority:
            raise ValueError(f"agent {agent.agent_id} attempted execution authority")
        return evidence
