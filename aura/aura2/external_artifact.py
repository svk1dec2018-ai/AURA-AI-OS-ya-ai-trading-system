from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .opensource_registry import PROJECTS
from .research_gateway import GatewayDecision, ResearchCandidate, ResearchGateway


class ExternalResearchMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trades: int = Field(ge=0)
    profit_factor: float = Field(ge=0.0)
    max_drawdown: float = Field(ge=0.0, le=1.0)
    expectancy_r: float


class ExternalResearchArtifact(BaseModel):
    """Normalized research result accepted from isolated open-source sidecars."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    source: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1, max_length=200)
    hypothesis: str = Field(min_length=1, max_length=4000)
    metrics: ExternalResearchMetrics
    out_of_sample: bool
    walk_forward: bool
    research_only: Literal[True] = True
    live_approved: Literal[False] = False
    execution_authority: Literal[False] = False
    risk_authority: Literal[False] = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_candidate(self) -> ResearchCandidate:
        if self.source not in PROJECTS:
            raise ValueError(f"unknown AURA 2 research source: {self.source}")
        return ResearchCandidate(
            source=self.source,
            candidate_id=self.candidate_id,
            hypothesis=self.hypothesis,
            metrics=self.metrics.model_dump(),
            out_of_sample=self.out_of_sample,
            walk_forward=self.walk_forward,
            metadata={
                **self.metadata,
                "research_only": True,
                "live_approved": False,
                "execution_authority": False,
                "risk_authority": False,
            },
        )

    @property
    def artifact_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


class ExternalResearchIntake:
    """Validate a sidecar artifact and route it to AURA-owned evidence gates."""

    def __init__(self, gateway: ResearchGateway | None = None) -> None:
        self.gateway = gateway or ResearchGateway()

    def ingest(self, payload: dict[str, Any]) -> tuple[ExternalResearchArtifact, GatewayDecision]:
        artifact = ExternalResearchArtifact.model_validate(payload)
        return artifact, self.gateway.ingest(artifact.to_candidate())
