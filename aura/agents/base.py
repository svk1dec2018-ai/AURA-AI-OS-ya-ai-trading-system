from __future__ import annotations

from abc import ABC, abstractmethod

from aura.agents.models import AgentContext, AgentEvidence, AgentRole


class SpecialistAgent(ABC):
    """Read-only market specialist contract.

    Specialist agents may analyze and propose evidence. They must not own broker
    credentials, submit orders, mutate the portfolio ledger, or modify approved
    strategy code. Execution authority remains outside the agent layer.
    """

    agent_id: str
    role: AgentRole

    @abstractmethod
    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raise NotImplementedError
