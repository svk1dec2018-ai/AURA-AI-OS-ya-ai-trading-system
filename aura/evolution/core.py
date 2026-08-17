from __future__ import annotations

import hashlib
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeneKind(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"
    CATEGORICAL = "categorical"


class GeneSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    kind: GeneKind
    low: float | None = None
    high: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()
    mutation_scale: float = Field(default=0.15, gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> GeneSpec:
        if self.kind == GeneKind.CATEGORICAL:
            if not self.choices:
                raise ValueError("categorical gene requires choices")
            return self
        if self.low is None or self.high is None or self.low >= self.high:
            raise ValueError("numeric gene requires low < high")
        if self.step is not None and self.step <= 0:
            raise ValueError("step must be positive")
        return self


class StrategyGenome(BaseModel):
    """Immutable candidate parameters. Deployed strategy code is never mutated in place."""

    model_config = ConfigDict(frozen=True)

    family: str = Field(min_length=1)
    parameters: dict[str, int | float | str]
    generation: int = Field(default=0, ge=0)
    parents: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            {"family": self.family, "parameters": self.parameters},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def genome_id(self) -> str:
        return f"{self.family}:{self.content_hash[:16]}"


class PerformanceSlice(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    trades: int = Field(ge=0)
    net_return_pct: float
    expectancy_pct: float
    profit_factor: float = Field(ge=0)
    max_drawdown_pct: float = Field(ge=0)
    sharpe: float
    win_rate: float = Field(ge=0, le=1)
    avg_slippage_bps: float = Field(default=0, ge=0)


class CandidateEvaluation(BaseModel):
    """Measured candidate evidence. Search never sees a sealed holdout metric."""

    model_config = ConfigDict(frozen=True)

    genome: StrategyGenome
    in_sample: PerformanceSlice
    walk_forward: tuple[PerformanceSlice, ...]
    monte_carlo_p05_return_pct: float
    monte_carlo_p95_drawdown_pct: float = Field(ge=0)
    paper: PerformanceSlice | None = None
    reconciliation_incidents: int = Field(default=0, ge=0)
    operational_incidents: int = Field(default=0, ge=0)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_oos_trades(self) -> int:
        return sum(item.trades for item in self.walk_forward)


@dataclass(slots=True, frozen=True)
class FitnessPolicy:
    """Conservative multi-objective policy designed to fight overfitting."""

    min_walk_forward_folds: int = 3
    min_oos_trades: int = 60
    min_positive_fold_fraction: float = 0.67
    min_profit_factor: float = 1.05
    min_expectancy_pct: float = 0.0
    max_drawdown_pct: float = 20.0
    min_monte_carlo_p05_return_pct: float = -5.0
    max_monte_carlo_p95_drawdown_pct: float = 25.0
    min_paper_trades: int = 40
    max_paper_drawdown_pct: float = 15.0
    complexity_penalty: float = 0.03
    slippage_penalty: float = 0.02

    def __post_init__(self) -> None:
        if self.min_walk_forward_folds <= 0 or self.min_oos_trades < 0:
            raise ValueError("invalid walk-forward requirements")
        if not 0 < self.min_positive_fold_fraction <= 1:
            raise ValueError("min_positive_fold_fraction must be in (0, 1]")

    def research_failures(self, evaluation: CandidateEvaluation) -> tuple[str, ...]:
        folds = evaluation.walk_forward
        failures: list[str] = []
        if len(folds) < self.min_walk_forward_folds:
            failures.append("insufficient_walk_forward_folds")
        if evaluation.total_oos_trades < self.min_oos_trades:
            failures.append("insufficient_oos_trades")
        if folds:
            positive = sum(
                1
                for item in folds
                if item.expectancy_pct > self.min_expectancy_pct
                and item.profit_factor >= self.min_profit_factor
            )
            if positive / len(folds) < self.min_positive_fold_fraction:
                failures.append("unstable_walk_forward")
            if max(item.max_drawdown_pct for item in folds) > self.max_drawdown_pct:
                failures.append("walk_forward_drawdown")
        if evaluation.monte_carlo_p05_return_pct < self.min_monte_carlo_p05_return_pct:
            failures.append("monte_carlo_tail_return")
        if evaluation.monte_carlo_p95_drawdown_pct > self.max_monte_carlo_p95_drawdown_pct:
            failures.append("monte_carlo_tail_drawdown")
        if evaluation.reconciliation_incidents:
            failures.append("reconciliation_incident")
        if evaluation.operational_incidents:
            failures.append("operational_incident")
        return tuple(failures)

    def paper_failures(self, evaluation: CandidateEvaluation) -> tuple[str, ...]:
        failures = list(self.research_failures(evaluation))
        paper = evaluation.paper
        if paper is None:
            failures.append("paper_evidence_missing")
            return tuple(failures)
        if paper.trades < self.min_paper_trades:
            failures.append("insufficient_paper_trades")
        if paper.expectancy_pct <= self.min_expectancy_pct:
            failures.append("non_positive_paper_expectancy")
        if paper.profit_factor < self.min_profit_factor:
            failures.append("weak_paper_profit_factor")
        if paper.max_drawdown_pct > self.max_paper_drawdown_pct:
            failures.append("paper_drawdown")
        return tuple(failures)

    def score(self, evaluation: CandidateEvaluation) -> float:
        """Robust score; failed candidates remain rankable for learning, not promotion."""
        folds = evaluation.walk_forward or (evaluation.in_sample,)
        mean_return = sum(item.net_return_pct for item in folds) / len(folds)
        mean_expectancy = sum(item.expectancy_pct for item in folds) / len(folds)
        mean_pf = sum(min(item.profit_factor, 3.0) for item in folds) / len(folds)
        mean_sharpe = sum(max(min(item.sharpe, 4.0), -4.0) for item in folds) / len(folds)
        worst_dd = max(item.max_drawdown_pct for item in folds)
        mean_slippage = sum(item.avg_slippage_bps for item in folds) / len(folds)
        complexity = len(evaluation.genome.parameters)
        stability = _stability_penalty([item.net_return_pct for item in folds])
        tail_penalty = max(0.0, -evaluation.monte_carlo_p05_return_pct)
        return (
            mean_return
            + 4.0 * mean_expectancy
            + 2.0 * (mean_pf - 1.0)
            + mean_sharpe
            - 0.35 * worst_dd
            - stability
            - 0.2 * tail_penalty
            - self.complexity_penalty * complexity
            - self.slippage_penalty * mean_slippage
        )


def _stability_penalty(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


@dataclass(slots=True, frozen=True)
class EvolutionConfig:
    population_size: int = 12
    elite_fraction: float = 0.25
    mutation_probability: float = 0.65
    crossover_probability: float = 0.35
    random_seed: int = 7

    def __post_init__(self) -> None:
        if self.population_size < 2:
            raise ValueError("population_size must be >= 2")
        if not 0 < self.elite_fraction <= 0.5:
            raise ValueError("elite_fraction must be in (0, 0.5]")
        for value in (self.mutation_probability, self.crossover_probability):
            if not 0 <= value <= 1:
                raise ValueError("probabilities must be in [0, 1]")


class PopulationEvolution:
    """Small dependency-free PBT/genetic-style optimizer for AURA research sandboxes.

    It borrows the *concept* of population based exploration/exploitation, but the
    implementation is original and intentionally bounded by AURA validation gates.
    """

    def __init__(
        self,
        gene_specs: tuple[GeneSpec, ...],
        *,
        family: str,
        config: EvolutionConfig | None = None,
        fitness_policy: FitnessPolicy | None = None,
    ) -> None:
        if not gene_specs:
            raise ValueError("at least one gene is required")
        if len({gene.name for gene in gene_specs}) != len(gene_specs):
            raise ValueError("gene names must be unique")
        self.gene_specs = gene_specs
        self.family = family
        self.config = config or EvolutionConfig()
        self.fitness_policy = fitness_policy or FitnessPolicy()
        self._rng = random.Random(self.config.random_seed)

    def random_genome(self, *, generation: int = 0) -> StrategyGenome:
        return StrategyGenome(
            family=self.family,
            parameters={spec.name: self._random_value(spec) for spec in self.gene_specs},
            generation=generation,
        )

    def initial_population(
        self,
        seeds: tuple[StrategyGenome, ...] = (),
    ) -> tuple[StrategyGenome, ...]:
        population = list(seeds[: self.config.population_size])
        for seed in population:
            self._validate_genome(seed)
        population = _dedupe_genomes(population)
        while len(population) < self.config.population_size:
            population.append(self.random_genome())
            population = _dedupe_genomes(population)
        return tuple(population[: self.config.population_size])

    def next_generation(
        self,
        evaluations: tuple[CandidateEvaluation, ...],
    ) -> tuple[StrategyGenome, ...]:
        if not evaluations:
            raise ValueError("cannot evolve without evaluations")
        ranked = sorted(
            evaluations,
            key=lambda item: self.fitness_policy.score(item),
            reverse=True,
        )
        elite_count = max(1, round(self.config.population_size * self.config.elite_fraction))
        elites = [item.genome for item in ranked[:elite_count]]
        generation = max(item.genome.generation for item in evaluations) + 1
        children: list[StrategyGenome] = [
            elite.model_copy(update={"generation": generation, "parents": (elite.genome_id,)})
            for elite in elites
        ]

        while len(children) < self.config.population_size:
            parent_a = self._rng.choice(elites)
            parameters = dict(parent_a.parameters)
            parents = [parent_a.genome_id]
            if len(elites) > 1 and self._rng.random() < self.config.crossover_probability:
                parent_b = self._rng.choice([item for item in elites if item != parent_a])
                parents.append(parent_b.genome_id)
                for spec in self.gene_specs:
                    if self._rng.random() < 0.5:
                        parameters[spec.name] = parent_b.parameters[spec.name]
            for spec in self.gene_specs:
                if self._rng.random() < self.config.mutation_probability:
                    parameters[spec.name] = self._mutate(spec, parameters[spec.name])
            children.append(
                StrategyGenome(
                    family=self.family,
                    parameters=parameters,
                    generation=generation,
                    parents=tuple(parents),
                )
            )
        unique = _dedupe_genomes(children)
        while len(unique) < self.config.population_size:
            unique.append(self.random_genome(generation=generation))
            unique = _dedupe_genomes(unique)
        return tuple(unique[: self.config.population_size])

    def _validate_genome(self, genome: StrategyGenome) -> None:
        if genome.family != self.family:
            raise ValueError("seed genome family mismatch")
        expected = {spec.name for spec in self.gene_specs}
        if set(genome.parameters) != expected:
            raise ValueError("seed genome parameters do not match gene space")

    def _random_value(self, spec: GeneSpec) -> int | float | str:
        if spec.kind == GeneKind.CATEGORICAL:
            return self._rng.choice(spec.choices)
        assert spec.low is not None and spec.high is not None
        if spec.kind == GeneKind.INTEGER:
            low = math.ceil(spec.low)
            high = math.floor(spec.high)
            return self._rng.randint(low, high)
        value = self._rng.uniform(spec.low, spec.high)
        return _quantize(value, spec)

    def _mutate(self, spec: GeneSpec, value: float | str) -> int | float | str:
        if spec.kind == GeneKind.CATEGORICAL:
            choices = [item for item in spec.choices if item != value]
            return self._rng.choice(choices or list(spec.choices))
        assert spec.low is not None and spec.high is not None
        span = spec.high - spec.low
        mutated = float(value) + self._rng.gauss(0.0, span * spec.mutation_scale)
        mutated = min(max(mutated, spec.low), spec.high)
        if spec.kind == GeneKind.INTEGER:
            return round(mutated)
        return _quantize(mutated, spec)


def _quantize(value: float, spec: GeneSpec) -> float:
    if spec.step is None or spec.low is None or spec.high is None:
        return float(value)
    units = round((value - spec.low) / spec.step)
    return float(min(max(spec.low + units * spec.step, spec.low), spec.high))


def _dedupe_genomes(genomes: list[StrategyGenome]) -> list[StrategyGenome]:
    unique: dict[str, StrategyGenome] = {}
    for genome in genomes:
        unique.setdefault(genome.content_hash, genome)
    return list(unique.values())


class EvolutionJournal:
    """Append-only learning journal and atomic champion checkpoint."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.events_path = directory / "evolution.jsonl"
        self.champion_path = directory / "paper_champion.json"

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def save_paper_champion(
        self,
        evaluation: CandidateEvaluation,
        *,
        score: float,
    ) -> None:
        payload = {
            "genome": evaluation.genome.model_dump(mode="json"),
            "score": score,
            "paper": evaluation.paper.model_dump(mode="json") if evaluation.paper else None,
            "saved_at": datetime.now(UTC).isoformat(),
            "live_approved": False,
        }
        temp = self.champion_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.champion_path)
