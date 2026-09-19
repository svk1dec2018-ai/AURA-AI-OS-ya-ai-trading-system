from __future__ import annotations

import random
from dataclasses import dataclass

from aura.evolution.core import GeneKind, GeneSpec, StrategyGenome
from aura.research.autonomous_strategy_lab import autonomous_strategy_gene_specs


@dataclass(slots=True, frozen=True)
class StrategyMutationPolicy:
    mutation_probability: float = 0.60
    minimum_mutations: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.mutation_probability <= 1:
            raise ValueError("mutation_probability must be in (0, 1]")
        if self.minimum_mutations <= 0:
            raise ValueError("minimum_mutations must be positive")


def mutate_autonomous_genome(
    genome: StrategyGenome,
    *,
    seed: int,
    policy: StrategyMutationPolicy | None = None,
) -> StrategyGenome:
    """Create one bounded child from an autonomous-strategy genome.

    The available gene specs deliberately contain alpha/research parameters only.
    Risk limits, kill switches, broker permissions and live-approval controls are
    absent from this mutation space by construction.
    """

    if genome.family != "autonomous_strategy_dsl.v1":
        raise ValueError("unsupported genome family for autonomous mutation")
    specs = autonomous_strategy_gene_specs()
    expected = {item.name for item in specs}
    if set(genome.parameters) != expected:
        raise ValueError("genome parameters do not match autonomous strategy grammar")

    effective = policy or StrategyMutationPolicy()
    rng = random.Random(seed)
    parameters = dict(genome.parameters)
    mutated_names: list[str] = []
    for spec in specs:
        if rng.random() >= effective.mutation_probability:
            continue
        parameters[spec.name] = _mutate_value(spec, parameters[spec.name], rng)
        mutated_names.append(spec.name)

    if len(mutated_names) < effective.minimum_mutations:
        remaining = [item for item in specs if item.name not in mutated_names]
        while len(mutated_names) < effective.minimum_mutations and remaining:
            spec = rng.choice(remaining)
            remaining.remove(spec)
            parameters[spec.name] = _mutate_value(spec, parameters[spec.name], rng)
            mutated_names.append(spec.name)

    child = StrategyGenome(
        family=genome.family,
        parameters=parameters,
        generation=genome.generation + 1,
        parents=(genome.genome_id,),
    )
    if child.content_hash == genome.content_hash:
        # Categorical choices or numeric quantisation can occasionally return the
        # same value. Force one deterministic alternative so a "new" child is real.
        spec = specs[seed % len(specs)]
        parameters[spec.name] = _force_alternative(spec, parameters[spec.name], rng)
        child = StrategyGenome(
            family=genome.family,
            parameters=parameters,
            generation=genome.generation + 1,
            parents=(genome.genome_id,),
        )
    if child.content_hash == genome.content_hash:
        raise RuntimeError("autonomous mutation could not produce a distinct child")
    return child


def _mutate_value(
    spec: GeneSpec,
    value: float | str,
    rng: random.Random,
) -> float | str:
    if spec.kind == GeneKind.CATEGORICAL:
        choices = [item for item in spec.choices if item != value]
        return rng.choice(choices or list(spec.choices))
    assert spec.low is not None and spec.high is not None
    span = spec.high - spec.low
    mutated = float(value) + rng.gauss(0.0, span * spec.mutation_scale)
    mutated = min(max(mutated, spec.low), spec.high)
    if spec.kind == GeneKind.INTEGER:
        return round(mutated)
    return _quantize(mutated, spec)


def _force_alternative(
    spec: GeneSpec,
    value: float | str,
    rng: random.Random,
) -> float | str:
    if spec.kind == GeneKind.CATEGORICAL:
        choices = [item for item in spec.choices if item != value]
        return rng.choice(choices or list(spec.choices))
    assert spec.low is not None and spec.high is not None
    if spec.kind == GeneKind.INTEGER:
        current = int(value)
        if current < int(spec.high):
            return current + 1
        return current - 1
    step = spec.step or max((spec.high - spec.low) / 100.0, 1e-9)
    current = float(value)
    candidate = current + step if current + step <= spec.high else current - step
    return _quantize(candidate, spec)


def _quantize(value: float, spec: GeneSpec) -> float:
    if spec.step is None or spec.low is None or spec.high is None:
        return float(value)
    units = round((value - spec.low) / spec.step)
    return float(min(max(spec.low + units * spec.step, spec.low), spec.high))
