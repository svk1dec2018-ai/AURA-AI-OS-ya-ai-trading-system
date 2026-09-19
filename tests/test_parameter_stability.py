from datetime import UTC, datetime

import pytest

from aura.evolution.core import (
    CandidateEvaluation,
    GeneKind,
    GeneSpec,
    PerformanceSlice,
    StrategyGenome,
)
from aura.research.parameter_stability import (
    ParameterStabilityPolicy,
    assess_parameter_stability,
    build_parameter_neighborhood,
)

GENES = (
    GeneSpec(name="fast", kind=GeneKind.INTEGER, low=2, high=4, step=1),
    GeneSpec(name="threshold", kind=GeneKind.FLOAT, low=0.1, high=0.3, step=0.1),
    GeneSpec(name="mode", kind=GeneKind.CATEGORICAL, choices=("trend", "mean")),
)


def _genome(*, fast: int = 3) -> StrategyGenome:
    return StrategyGenome(
        family="stability-test",
        parameters={"fast": fast, "threshold": 0.2, "mode": "trend"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _evaluation(
    genome: StrategyGenome,
    *,
    net_return_pct: float = 8.0,
    expectancy_pct: float = 0.5,
) -> CandidateEvaluation:
    def performance(label: str) -> PerformanceSlice:
        return PerformanceSlice(
            label=label,
            trades=20,
            net_return_pct=net_return_pct,
            expectancy_pct=expectancy_pct,
            profit_factor=1.4,
            max_drawdown_pct=5.0,
            sharpe=1.0,
            win_rate=0.55,
        )

    return CandidateEvaluation(
        genome=genome,
        in_sample=performance("in_sample"),
        walk_forward=(performance("wf-1"), performance("wf-2"), performance("wf-3")),
        monte_carlo_p05_return_pct=1.0,
        monte_carlo_p95_drawdown_pct=10.0,
        evaluated_at=datetime(2026, 2, 1, tzinfo=UTC),
    )


def test_neighborhood_is_deterministic_and_changes_one_parameter_at_a_time() -> None:
    reference = _genome()

    first = build_parameter_neighborhood(reference, GENES)
    second = build_parameter_neighborhood(reference, GENES)

    assert [item.content_hash for item in first] == [item.content_hash for item in second]
    assert len(first) == 5
    assert [item.parameters["fast"] for item in first[:2]] == [2, 4]
    assert [item.parameters["threshold"] for item in first[2:4]] == [0.1, 0.3]
    assert first[4].parameters["mode"] == "mean"
    for neighbor in first:
        changed = [
            name
            for name, value in reference.parameters.items()
            if neighbor.parameters[name] != value
        ]
        assert len(changed) == 1


def test_boundary_gene_requires_only_available_local_side() -> None:
    neighbors = build_parameter_neighborhood(_genome(fast=2), GENES)

    fast_values = [item.parameters["fast"] for item in neighbors if item.parameters["fast"] != 2]
    assert fast_values == [3]
    assert len(neighbors) == 4


def test_stability_approves_complete_measured_neighborhood() -> None:
    reference = _evaluation(_genome(), net_return_pct=10.0)
    neighbors = tuple(
        _evaluation(genome, net_return_pct=8.0)
        for genome in build_parameter_neighborhood(reference.genome, GENES)
    )

    result = assess_parameter_stability(reference, neighbors, GENES)

    assert result.approved
    assert result.reasons == ()
    assert result.expected_neighbors == 5
    assert result.evaluated_neighbors == 5
    assert result.stable_neighbor_fraction == 1.0
    assert result.worst_score_retention_ratio is not None
    assert result.worst_score_retention_ratio > 0.5


def test_stability_fails_closed_when_neighbor_evidence_is_missing() -> None:
    reference = _evaluation(_genome(), net_return_pct=10.0)
    planned = build_parameter_neighborhood(reference.genome, GENES)
    neighbors = tuple(_evaluation(genome) for genome in planned[:-1])

    result = assess_parameter_stability(reference, neighbors, GENES)

    assert not result.approved
    assert result.evaluated_neighbors == 4
    assert result.stable_neighbor_fraction == pytest.approx(0.8)
    assert result.missing_neighbor_genome_ids == (planned[-1].genome_id,)
    assert "missing_neighbor_evidence" in result.reasons
    assert "stable_neighbor_fraction_below_threshold" in result.reasons


def test_stability_rejects_local_performance_cliff() -> None:
    reference = _evaluation(_genome(), net_return_pct=10.0)
    planned = build_parameter_neighborhood(reference.genome, GENES)
    neighbors = tuple(
        _evaluation(genome, net_return_pct=-10.0 if index == 0 else 8.0)
        for index, genome in enumerate(planned)
    )

    result = assess_parameter_stability(reference, neighbors, GENES)

    assert not result.approved
    assert result.stable_neighbors == 4
    assert result.neighbors[0].stable is False
    assert "neighbor_score_retention_failed" in result.reasons
    assert "stable_neighbor_fraction_below_threshold" in result.reasons


def test_explicit_policy_can_tolerate_bounded_unstable_fraction() -> None:
    reference = _evaluation(_genome(), net_return_pct=10.0)
    planned = build_parameter_neighborhood(reference.genome, GENES)
    neighbors = tuple(
        _evaluation(genome, net_return_pct=-10.0 if index == 0 else 8.0)
        for index, genome in enumerate(planned)
    )

    result = assess_parameter_stability(
        reference,
        neighbors,
        GENES,
        policy=ParameterStabilityPolicy(min_stable_neighbor_fraction=0.8),
    )

    assert result.approved
    assert result.stable_neighbor_fraction == pytest.approx(0.8)
    assert result.reasons == ()


def test_stability_requires_neighbors_to_pass_normal_research_gate() -> None:
    reference = _evaluation(_genome(), net_return_pct=10.0)
    planned = build_parameter_neighborhood(reference.genome, GENES)
    neighbors = tuple(
        _evaluation(genome, expectancy_pct=-0.1 if index == 0 else 0.5)
        for index, genome in enumerate(planned)
    )

    result = assess_parameter_stability(reference, neighbors, GENES)

    assert not result.approved
    assert "unstable_walk_forward" in result.neighbors[0].research_failures
    assert "neighbor_research_gate_failed" in result.reasons


def test_stability_rejects_cherry_picked_or_duplicate_evidence() -> None:
    reference = _evaluation(_genome())
    planned = build_parameter_neighborhood(reference.genome, GENES)
    unexpected = StrategyGenome(
        family=reference.genome.family,
        parameters={"fast": 4, "threshold": 0.3, "mode": "trend"},
    )

    with pytest.raises(ValueError, match="unexpected neighbor evaluation"):
        assess_parameter_stability(reference, (_evaluation(unexpected),), GENES)
    duplicate = _evaluation(planned[0])
    with pytest.raises(ValueError, match="duplicate neighbor evaluation"):
        assess_parameter_stability(reference, (duplicate, duplicate), GENES)


def test_numeric_gene_requires_explicit_reproducible_step() -> None:
    genes = (GeneSpec(name="fast", kind=GeneKind.INTEGER, low=2, high=4),)
    reference = StrategyGenome(family="x", parameters={"fast": 3})

    with pytest.raises(ValueError, match="explicit stability step"):
        build_parameter_neighborhood(reference, genes)
