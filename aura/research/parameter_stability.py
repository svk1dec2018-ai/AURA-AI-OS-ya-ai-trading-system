from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from aura.evolution.core import (
    CandidateEvaluation,
    FitnessPolicy,
    GeneKind,
    GeneSpec,
    StrategyGenome,
)

ParameterValue = int | float | str


class ParameterNeighborAssessment(BaseModel):
    """Measured evidence for one deterministic local parameter perturbation."""

    model_config = ConfigDict(frozen=True)

    parameter_name: str = Field(min_length=1)
    neighbor_value: ParameterValue
    neighbor_genome_id: str = Field(min_length=1)
    score: float
    score_retention_ratio: float | None
    research_failures: tuple[str, ...]
    stable: bool


class ParameterStabilityAssessment(BaseModel):
    """Fail-closed local stability result; never a paper/live approval artifact."""

    model_config = ConfigDict(frozen=True)

    reference_genome_id: str = Field(min_length=1)
    reference_score: float
    expected_neighbors: int = Field(gt=0)
    evaluated_neighbors: int = Field(ge=0)
    stable_neighbors: int = Field(ge=0)
    stable_neighbor_fraction: float = Field(ge=0.0, le=1.0)
    worst_score_retention_ratio: float | None
    missing_neighbor_genome_ids: tuple[str, ...]
    neighbors: tuple[ParameterNeighborAssessment, ...]
    approved: bool
    reasons: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ParameterStabilityPolicy:
    """Conservative thresholds for rejecting sharp local performance cliffs."""

    min_score_retention_ratio: float = 0.50
    min_stable_neighbor_fraction: float = 1.0
    require_neighbor_research_pass: bool = True
    max_neighbors: int = 128

    def __post_init__(self) -> None:
        if not 0 <= self.min_score_retention_ratio <= 1:
            raise ValueError("min_score_retention_ratio must be between 0 and 1")
        if not 0 < self.min_stable_neighbor_fraction <= 1:
            raise ValueError("min_stable_neighbor_fraction must be in (0, 1]")
        if self.max_neighbors <= 0:
            raise ValueError("max_neighbors must be positive")


def build_parameter_neighborhood(
    reference: StrategyGenome,
    gene_specs: tuple[GeneSpec, ...],
    *,
    max_neighbors: int = 128,
) -> tuple[StrategyGenome, ...]:
    """Build deterministic one-at-a-time perturbations around a reference genome.

    Numeric genes require an explicit step. Categorical genes enumerate every
    declared alternative. Only one parameter changes in each returned genome,
    keeping the stability question local and auditable.
    """

    if max_neighbors <= 0:
        raise ValueError("max_neighbors must be positive")
    _validate_gene_space(reference, gene_specs)
    neighbors: list[StrategyGenome] = []
    for spec in gene_specs:
        values = _neighbor_values(reference.parameters[spec.name], spec)
        if not values:
            raise ValueError(f"gene {spec.name!r} has no available perturbation")
        for value in values:
            parameters = dict(reference.parameters)
            parameters[spec.name] = value
            neighbors.append(
                StrategyGenome(
                    family=reference.family,
                    parameters=parameters,
                    generation=reference.generation,
                    parents=(reference.genome_id,),
                    created_at=reference.created_at,
                )
            )
            if len(neighbors) > max_neighbors:
                raise ValueError(
                    f"parameter neighborhood exceeds max_neighbors={max_neighbors}"
                )
    hashes = [item.content_hash for item in neighbors]
    if len(set(hashes)) != len(hashes):
        raise ValueError("gene space produced duplicate parameter neighbors")
    return tuple(neighbors)


def assess_parameter_stability(
    reference: CandidateEvaluation,
    neighbor_evaluations: tuple[CandidateEvaluation, ...],
    gene_specs: tuple[GeneSpec, ...],
    *,
    policy: ParameterStabilityPolicy | None = None,
    fitness_policy: FitnessPolicy | None = None,
) -> ParameterStabilityAssessment:
    """Assess measured local neighbors without creating or promoting a strategy.

    Missing expected neighbors count as unstable. Evidence for an unexpected or
    duplicate genome is rejected so callers cannot substitute hand-picked trials.
    """

    limits = policy or ParameterStabilityPolicy()
    fitness = fitness_policy or FitnessPolicy()
    expected = build_parameter_neighborhood(
        reference.genome,
        gene_specs,
        max_neighbors=limits.max_neighbors,
    )
    expected_by_hash = {item.content_hash: item for item in expected}
    evidence_by_hash: dict[str, CandidateEvaluation] = {}
    for evaluation in neighbor_evaluations:
        genome_hash = evaluation.genome.content_hash
        if genome_hash in evidence_by_hash:
            raise ValueError(f"duplicate neighbor evaluation: {evaluation.genome.genome_id}")
        if genome_hash not in expected_by_hash:
            raise ValueError(f"unexpected neighbor evaluation: {evaluation.genome.genome_id}")
        evidence_by_hash[genome_hash] = evaluation

    reference_score = float(fitness.score(reference))
    if not math.isfinite(reference_score):
        raise ValueError("reference fitness score must be finite")
    reference_failures = fitness.research_failures(reference)

    results: list[ParameterNeighborAssessment] = []
    missing_ids: list[str] = []
    stable_count = 0
    retention_values: list[float] = []
    saw_neighbor_research_failure = False
    saw_retention_failure = False
    for expected_genome in expected:
        evaluation = evidence_by_hash.get(expected_genome.content_hash)
        if evaluation is None:
            missing_ids.append(expected_genome.genome_id)
            continue
        score = float(fitness.score(evaluation))
        if not math.isfinite(score):
            raise ValueError(
                f"neighbor fitness score must be finite: {evaluation.genome.genome_id}"
            )
        failures = fitness.research_failures(evaluation)
        retention = score / reference_score if reference_score > 0 else None
        if retention is not None:
            retention_values.append(retention)
        retention_passed = (
            retention is not None and retention >= limits.min_score_retention_ratio
        )
        research_passed = not failures or not limits.require_neighbor_research_pass
        stable = retention_passed and research_passed
        stable_count += int(stable)
        saw_neighbor_research_failure = saw_neighbor_research_failure or not research_passed
        saw_retention_failure = saw_retention_failure or not retention_passed
        parameter_name = _changed_parameter(reference.genome, expected_genome)
        results.append(
            ParameterNeighborAssessment(
                parameter_name=parameter_name,
                neighbor_value=expected_genome.parameters[parameter_name],
                neighbor_genome_id=expected_genome.genome_id,
                score=score,
                score_retention_ratio=retention,
                research_failures=failures,
                stable=stable,
            )
        )

    expected_count = len(expected)
    stable_fraction = stable_count / expected_count
    reasons: list[str] = []
    if reference_failures:
        reasons.append("reference_research_gate_failed")
    if reference_score <= 0:
        reasons.append("reference_score_not_positive")
    if missing_ids:
        reasons.append("missing_neighbor_evidence")
    if stable_fraction < limits.min_stable_neighbor_fraction:
        if saw_neighbor_research_failure:
            reasons.append("neighbor_research_gate_failed")
        if saw_retention_failure:
            reasons.append("neighbor_score_retention_failed")
        reasons.append("stable_neighbor_fraction_below_threshold")

    return ParameterStabilityAssessment(
        reference_genome_id=reference.genome.genome_id,
        reference_score=reference_score,
        expected_neighbors=expected_count,
        evaluated_neighbors=len(results),
        stable_neighbors=stable_count,
        stable_neighbor_fraction=stable_fraction,
        worst_score_retention_ratio=min(retention_values) if retention_values else None,
        missing_neighbor_genome_ids=tuple(missing_ids),
        neighbors=tuple(results),
        approved=not reasons,
        reasons=tuple(reasons),
    )


def _validate_gene_space(reference: StrategyGenome, gene_specs: tuple[GeneSpec, ...]) -> None:
    if not gene_specs:
        raise ValueError("parameter stability requires at least one gene")
    names = [item.name for item in gene_specs]
    if len(set(names)) != len(names):
        raise ValueError("gene names must be unique")
    if set(reference.parameters) != set(names):
        raise ValueError("reference parameters do not match gene space")
    for spec in gene_specs:
        value = reference.parameters[spec.name]
        if spec.kind == GeneKind.CATEGORICAL:
            if len(set(spec.choices)) != len(spec.choices):
                raise ValueError(f"categorical gene {spec.name!r} has duplicate choices")
            if not isinstance(value, str) or value not in spec.choices:
                raise ValueError(f"reference value is invalid for gene {spec.name!r}")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"numeric gene {spec.name!r} requires a numeric reference")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"reference value for gene {spec.name!r} must be finite")
        assert spec.low is not None and spec.high is not None
        if not spec.low <= numeric <= spec.high:
            raise ValueError(f"reference value is outside bounds for gene {spec.name!r}")
        if spec.step is None:
            raise ValueError(f"numeric gene {spec.name!r} requires an explicit stability step")
        units = (numeric - spec.low) / spec.step
        if not math.isclose(units, round(units), rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"reference value is off-grid for gene {spec.name!r}")
        if spec.kind == GeneKind.INTEGER and (
            not isinstance(value, int) or not float(spec.step).is_integer()
        ):
            raise ValueError(f"integer gene {spec.name!r} requires integer value/step")


def _neighbor_values(value: ParameterValue, spec: GeneSpec) -> tuple[ParameterValue, ...]:
    if spec.kind == GeneKind.CATEGORICAL:
        return tuple(item for item in spec.choices if item != value)
    assert spec.low is not None and spec.high is not None and spec.step is not None
    numeric = float(value)
    candidates: list[ParameterValue] = []
    for candidate in (numeric - spec.step, numeric + spec.step):
        if candidate < spec.low - 1e-12 or candidate > spec.high + 1e-12:
            continue
        if spec.kind == GeneKind.INTEGER:
            candidates.append(round(candidate))
        else:
            candidates.append(round(candidate, 12))
    return tuple(candidates)


def _changed_parameter(reference: StrategyGenome, neighbor: StrategyGenome) -> str:
    changed = [
        name
        for name, value in reference.parameters.items()
        if neighbor.parameters.get(name) != value
    ]
    if len(changed) != 1:
        raise ValueError("parameter neighbor must change exactly one value")
    return changed[0]
