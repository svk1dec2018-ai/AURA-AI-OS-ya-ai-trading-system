from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from aura.evolution.core import (
    CandidateEvaluation,
    EvolutionConfig,
    PopulationEvolution,
    StrategyGenome,
)
from aura.research.autonomous_strategy_lab import (
    ProTraderResearchObjective,
    autonomous_strategy_gene_specs,
)


class CandidateEvaluator(Protocol):
    async def evaluate(self, genome: StrategyGenome) -> CandidateEvaluation: ...


@dataclass(slots=True, frozen=True)
class StrategyFarmConfig:
    population_size: int = 64
    max_concurrent_evaluations: int = 8
    elite_fraction: float = 0.25
    mutation_probability: float = 0.70
    crossover_probability: float = 0.35
    random_seed: int = 17

    def __post_init__(self) -> None:
        if self.population_size < 2:
            raise ValueError("population_size must be at least 2")
        if self.max_concurrent_evaluations <= 0:
            raise ValueError("max_concurrent_evaluations must be positive")


@dataclass(slots=True, frozen=True)
class StrategyFarmGeneration:
    generation: int
    evaluations: tuple[CandidateEvaluation, ...]
    ranked: tuple[CandidateEvaluation, ...]
    research_qualified: tuple[CandidateEvaluation, ...]
    evaluated_trades: int

    @property
    def champion(self) -> CandidateEvaluation:
        if not self.ranked:
            raise RuntimeError("generation has no evaluations")
        return self.ranked[0]


class AutonomousStrategyResearchFarm:
    """Mass strategy-hypothesis search with bounded concurrency and immutable risk rails.

    The farm is allowed to invent alpha combinations inside AURA's safe DSL. It
    has no broker and no RiskEngine mutation authority. Its output is research
    evidence only; normal governance still controls paper/live promotion.
    """

    def __init__(
        self,
        evaluator: CandidateEvaluator,
        *,
        config: StrategyFarmConfig | None = None,
        objective: ProTraderResearchObjective | None = None,
    ) -> None:
        self.evaluator = evaluator
        self.config = config or StrategyFarmConfig()
        self.objective = objective or ProTraderResearchObjective()
        self.evolution = PopulationEvolution(
            autonomous_strategy_gene_specs(),
            family="autonomous_strategy_dsl.v1",
            config=EvolutionConfig(
                population_size=self.config.population_size,
                elite_fraction=self.config.elite_fraction,
                mutation_probability=self.config.mutation_probability,
                crossover_probability=self.config.crossover_probability,
                random_seed=self.config.random_seed,
            ),
            fitness_policy=self.objective,  # type: ignore[arg-type]
        )
        self.population = self.evolution.initial_population()
        self.completed_generations = 0
        self.total_candidate_evaluations = 0
        self.total_evaluated_trades = 0

    async def run_generation(self) -> StrategyFarmGeneration:
        semaphore = asyncio.Semaphore(self.config.max_concurrent_evaluations)

        async def evaluate(genome: StrategyGenome) -> CandidateEvaluation:
            async with semaphore:
                return await self.evaluator.evaluate(genome)

        evaluations = tuple(await asyncio.gather(*(evaluate(item) for item in self.population)))
        ranked = tuple(sorted(evaluations, key=self.objective.score, reverse=True))
        qualified = tuple(
            item for item in ranked if not self.objective.research_failures(item)
        )
        evaluated_trades = sum(
            item.in_sample.trades + sum(fold.trades for fold in item.walk_forward)
            for item in evaluations
        )
        generation_number = self.completed_generations
        result = StrategyFarmGeneration(
            generation=generation_number,
            evaluations=evaluations,
            ranked=ranked,
            research_qualified=qualified,
            evaluated_trades=evaluated_trades,
        )
        self.population = self.evolution.next_generation(evaluations)
        self.completed_generations += 1
        self.total_candidate_evaluations += len(evaluations)
        self.total_evaluated_trades += evaluated_trades
        return result

    async def run(self, generations: int) -> tuple[StrategyFarmGeneration, ...]:
        if generations <= 0:
            raise ValueError("generations must be positive")
        results = []
        for _ in range(generations):
            results.append(await self.run_generation())
        return tuple(results)
