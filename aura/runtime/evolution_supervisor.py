from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from aura.evolution.core import (
    CandidateEvaluation,
    EvolutionJournal,
    FitnessPolicy,
    PopulationEvolution,
    StrategyGenome,
)


class EvolutionEvaluator(Protocol):
    """Runs real AURA backtest/WFO/Monte-Carlo/paper measurements for one genome."""

    async def evaluate(self, genome: StrategyGenome) -> CandidateEvaluation: ...


@dataclass(slots=True, frozen=True)
class DemoEvolutionPolicy:
    max_generations: int = 20
    max_concurrent_evaluations: int = 4
    no_improvement_patience: int = 5
    min_champion_score_improvement: float = 0.05

    def __post_init__(self) -> None:
        if self.max_generations <= 0:
            raise ValueError("max_generations must be positive")
        if self.max_concurrent_evaluations <= 0:
            raise ValueError("max_concurrent_evaluations must be positive")
        if self.no_improvement_patience <= 0:
            raise ValueError("no_improvement_patience must be positive")


@dataclass(slots=True, frozen=True)
class GenerationResult:
    generation: int
    evaluations: tuple[CandidateEvaluation, ...]
    best_score: float
    best_genome_id: str
    paper_champion_changed: bool


@dataclass(slots=True, frozen=True)
class DemoEvolutionResult:
    generations: tuple[GenerationResult, ...]
    paper_champion: CandidateEvaluation | None
    paper_champion_score: float | None
    stopped_for_patience: bool


class DemoEvolutionSupervisor:
    """Fast bounded self-evolution loop that can create a paper champion, never live.

    The evaluator is responsible for producing causal backtest, walk-forward,
    Monte-Carlo and paper evidence. This supervisor only learns from those measured
    outcomes, journals failures, evolves immutable parameter genomes and maintains
    a paper-only champion/challenger state.
    """

    def __init__(
        self,
        *,
        evolution: PopulationEvolution,
        evaluator: EvolutionEvaluator,
        journal: EvolutionJournal,
        fitness_policy: FitnessPolicy | None = None,
        policy: DemoEvolutionPolicy | None = None,
    ) -> None:
        self.evolution = evolution
        self.evaluator = evaluator
        self.journal = journal
        self.fitness_policy = fitness_policy or evolution.fitness_policy
        self.policy = policy or DemoEvolutionPolicy()

    async def run(
        self,
        seeds: tuple[StrategyGenome, ...] = (),
    ) -> DemoEvolutionResult:
        population = self.evolution.initial_population(seeds)
        champion: CandidateEvaluation | None = None
        champion_score: float | None = None
        generation_results: list[GenerationResult] = []
        stale_generations = 0
        stopped_for_patience = False

        for generation in range(self.policy.max_generations):
            evaluations = await self._evaluate_population(population)
            ranked = sorted(
                evaluations,
                key=self.fitness_policy.score,
                reverse=True,
            )
            best = ranked[0]
            best_score = self.fitness_policy.score(best)
            champion_changed = False

            for evaluation in ranked:
                score = self.fitness_policy.score(evaluation)
                research_failures = self.fitness_policy.research_failures(evaluation)
                paper_failures = self.fitness_policy.paper_failures(evaluation)
                self.journal.append(
                    "candidate_evaluated",
                    {
                        "generation": generation,
                        "genome_id": evaluation.genome.genome_id,
                        "score": score,
                        "research_failures": list(research_failures),
                        "paper_failures": list(paper_failures),
                        "oos_trades": evaluation.total_oos_trades,
                    },
                )
                if paper_failures:
                    continue
                if champion_score is None or (
                    score >= champion_score + self.policy.min_champion_score_improvement
                ):
                    champion = evaluation
                    champion_score = score
                    champion_changed = True
                    self.journal.save_paper_champion(evaluation, score=score)
                    self.journal.append(
                        "paper_champion_promoted",
                        {
                            "generation": generation,
                            "genome_id": evaluation.genome.genome_id,
                            "score": score,
                            "live_approved": False,
                        },
                    )
                    break

            generation_results.append(
                GenerationResult(
                    generation=generation,
                    evaluations=tuple(ranked),
                    best_score=best_score,
                    best_genome_id=best.genome.genome_id,
                    paper_champion_changed=champion_changed,
                )
            )

            if champion_changed:
                stale_generations = 0
            else:
                stale_generations += 1
            if stale_generations >= self.policy.no_improvement_patience:
                stopped_for_patience = True
                self.journal.append(
                    "evolution_stopped",
                    {
                        "reason": "no_improvement_patience",
                        "generation": generation,
                    },
                )
                break
            population = self.evolution.next_generation(tuple(ranked))

        return DemoEvolutionResult(
            generations=tuple(generation_results),
            paper_champion=champion,
            paper_champion_score=champion_score,
            stopped_for_patience=stopped_for_patience,
        )

    async def _evaluate_population(
        self,
        population: tuple[StrategyGenome, ...],
    ) -> tuple[CandidateEvaluation, ...]:
        semaphore = asyncio.Semaphore(self.policy.max_concurrent_evaluations)

        async def evaluate_one(genome: StrategyGenome) -> CandidateEvaluation:
            async with semaphore:
                result = await self.evaluator.evaluate(genome)
            if result.genome.content_hash != genome.content_hash:
                raise ValueError("evaluator returned evidence for a different genome")
            return result

        return tuple(await asyncio.gather(*(evaluate_one(item) for item in population)))
