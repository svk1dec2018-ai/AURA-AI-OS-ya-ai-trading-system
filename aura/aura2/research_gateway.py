from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .opensource_registry import PROJECTS


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    source: str
    candidate_id: str
    hypothesis: str
    metrics: dict[str, float]
    out_of_sample: bool
    walk_forward: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceGate:
    min_trades: int = 200
    min_profit_factor: float = 1.15
    max_drawdown: float = 0.15
    min_expectancy_r: float = 0.0

    def evaluate(self, candidate: ResearchCandidate) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        metrics = candidate.metrics
        if int(metrics.get("trades", 0)) < self.min_trades:
            reasons.append("insufficient_trades")
        if float(metrics.get("profit_factor", 0.0)) < self.min_profit_factor:
            reasons.append("profit_factor_below_gate")
        if float(metrics.get("max_drawdown", 1.0)) > self.max_drawdown:
            reasons.append("drawdown_above_gate")
        if float(metrics.get("expectancy_r", -1.0)) <= self.min_expectancy_r:
            reasons.append("non_positive_expectancy")
        if not candidate.out_of_sample:
            reasons.append("missing_out_of_sample")
        if not candidate.walk_forward:
            reasons.append("missing_walk_forward")
        return not reasons, tuple(reasons)


@dataclass(frozen=True, slots=True)
class GatewayDecision:
    candidate_id: str
    accepted_for_aura_validation: bool
    reasons: tuple[str, ...]
    granted_execution_authority: bool = False
    granted_risk_authority: bool = False
    stage: str = "RESEARCH"


class ResearchGateway:
    """Normalize external research without trusting external execution decisions."""

    def __init__(self, gate: EvidenceGate | None = None) -> None:
        self.gate = gate or EvidenceGate()

    def ingest(self, candidate: ResearchCandidate) -> GatewayDecision:
        if candidate.source not in PROJECTS:
            raise ValueError(f"unknown research source: {candidate.source}")
        if not candidate.candidate_id.strip():
            raise ValueError("candidate_id is required")
        if not candidate.hypothesis.strip():
            raise ValueError("hypothesis is required")
        accepted, reasons = self.gate.evaluate(candidate)
        return GatewayDecision(
            candidate_id=candidate.candidate_id,
            accepted_for_aura_validation=accepted,
            reasons=reasons,
        )
