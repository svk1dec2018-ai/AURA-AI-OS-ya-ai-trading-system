from __future__ import annotations

import math
import random
from dataclasses import dataclass

from aura.evolution.brain_policy import AuraBrainPolicy
from aura.evolution.brain_replay import BrainReplaySample, policy_allows
from aura.evolution.core import StrategyGenome


@dataclass(slots=True, frozen=True)
class BrainOptimizerConfig:
    minimum_samples: int = 250
    population_size: int = 32
    generations: int = 6
    elite_count: int = 6
    minimum_validation_trades: int = 20
    minimum_holdout_trades: int = 20
    mutation_probability: float = 0.55
    random_seed: int = 560026

    def __post_init__(self) -> None:
        if self.minimum_samples < 100:
            raise ValueError("minimum_samples must be at least 100")
        if self.population_size < 8:
            raise ValueError("population_size must be at least 8")
        if self.generations <= 0 or not 1 <= self.elite_count < self.population_size:
            raise ValueError("invalid optimizer generation/elite settings")
        if self.minimum_validation_trades <= 0 or self.minimum_holdout_trades <= 0:
            raise ValueError("validation/holdout trade floors must be positive")
        if not 0 <= self.mutation_probability <= 1:
            raise ValueError("mutation_probability must be in [0, 1]")


@dataclass(slots=True, frozen=True)
class BrainPolicyMetrics:
    selected_trades: int
    compounded_return_pct: float
    expectancy_pct: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate: float
    score: float


@dataclass(slots=True, frozen=True)
class BrainResearchResult:
    genome: StrategyGenome
    validation: BrainPolicyMetrics
    sealed_holdout: BrainPolicyMetrics
    holdout_passed: bool
    samples_used: int


class BrainResearchOptimizer:
    """Fast evolutionary search with a final sealed chronological holdout.

    Population selection uses only train/validation history. The newest 20% stays
    sealed until one winner is chosen, reducing repeated overfitting to the same
    recent outcomes. A holdout pass creates only a research challenger; forward
    live shadow/paper validation is still mandatory before paper promotion.
    """

    def __init__(self, config: BrainOptimizerConfig | None = None) -> None:
        self.config = config or BrainOptimizerConfig()

    def optimize(
        self,
        samples: tuple[BrainReplaySample, ...] | list[BrainReplaySample],
        *,
        baseline: AuraBrainPolicy | None = None,
    ) -> BrainResearchResult:
        ordered = tuple(sorted(samples, key=lambda item: (item.decision_time, item.sample_id)))
        if len(ordered) < self.config.minimum_samples:
            raise ValueError(
                f"brain optimizer needs {self.config.minimum_samples} samples; "
                f"received {len(ordered)}"
            )
        train_end = max(1, int(len(ordered) * 0.60))
        validation_end = max(train_end + 1, int(len(ordered) * 0.80))
        validation = ordered[train_end:validation_end]
        holdout = ordered[validation_end:]
        if not validation or not holdout:
            raise ValueError("brain optimizer split produced empty validation/holdout")

        rng = random.Random(self.config.random_seed + len(ordered))
        base = baseline or AuraBrainPolicy()
        population = [base]
        while len(population) < self.config.population_size:
            population.append(_mutate(base, rng, exploratory=True))

        best_policy = base
        best_metrics = _metrics(validation, base)
        for _generation in range(self.config.generations):
            ranked = sorted(
                ((policy, _metrics(validation, policy)) for policy in population),
                key=lambda pair: pair[1].score,
                reverse=True,
            )
            elites = [policy for policy, _ in ranked[: self.config.elite_count]]
            best_policy, best_metrics = ranked[0]
            next_population = list(elites)
            while len(next_population) < self.config.population_size:
                parent = rng.choice(elites)
                if rng.random() <= self.config.mutation_probability:
                    child = _mutate(parent, rng, exploratory=False)
                else:
                    child = _crossover(parent, rng.choice(elites), rng)
                next_population.append(child)
            population = next_population

        holdout_metrics = _metrics(holdout, best_policy)
        holdout_passed = (
            best_metrics.selected_trades >= self.config.minimum_validation_trades
            and holdout_metrics.selected_trades >= self.config.minimum_holdout_trades
            and holdout_metrics.expectancy_pct > 0
            and holdout_metrics.profit_factor > 1.0
            and holdout_metrics.compounded_return_pct > 0
            and holdout_metrics.max_drawdown_pct < 20.0
        )
        return BrainResearchResult(
            genome=best_policy.to_genome(generation=self.config.generations),
            validation=best_metrics,
            sealed_holdout=holdout_metrics,
            holdout_passed=holdout_passed,
            samples_used=len(ordered),
        )


def _metrics(
    samples: tuple[BrainReplaySample, ...],
    policy: AuraBrainPolicy,
) -> BrainPolicyMetrics:
    returns = [item.net_return_pct for item in samples if policy_allows(item, policy)]
    if not returns:
        return BrainPolicyMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, -1_000_000.0)
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    positives = [value for value in returns if value > 0]
    negatives = [value for value in returns if value < 0]
    for value in returns:
        equity *= max(0.0, 1.0 + value / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    expectancy = sum(returns) / len(returns)
    if negatives:
        profit_factor = sum(positives) / abs(sum(negatives))
    elif positives:
        profit_factor = 99.0
    else:
        profit_factor = 0.0
    compounded = (equity - 1.0) * 100.0
    win_rate = len(positives) / len(returns)
    score = (
        expectancy * math.log1p(len(returns))
        + 0.08 * compounded
        + 0.35 * min(profit_factor, 5.0)
        + 0.5 * win_rate
        - 0.12 * max_drawdown
    )
    return BrainPolicyMetrics(
        selected_trades=len(returns),
        compounded_return_pct=compounded,
        expectancy_pct=expectancy,
        profit_factor=max(0.0, profit_factor),
        max_drawdown_pct=max_drawdown,
        win_rate=win_rate,
        score=score,
    )


def _mutate(
    policy: AuraBrainPolicy,
    rng: random.Random,
    *,
    exploratory: bool,
) -> AuraBrainPolicy:
    data = policy.model_dump()
    scales = {
        "ceo_directional_margin": 0.10,
        "min_opportunity_confidence": 0.10,
        "max_deliberation_disagreement": 0.12,
        "max_failed_agent_fraction": 0.10,
        "max_execution_spread_bps": 15.0,
        "max_execution_slippage_bps": 8.0,
    }
    fields = list(scales)
    mutations = rng.randint(2 if exploratory else 1, 4 if exploratory else 2)
    for name in rng.sample(fields, k=min(mutations, len(fields))):
        data[name] = float(data[name]) + rng.gauss(0.0, scales[name])
    return AuraBrainPolicy(**data)


def _crossover(
    left: AuraBrainPolicy,
    right: AuraBrainPolicy,
    rng: random.Random,
) -> AuraBrainPolicy:
    a = left.model_dump()
    b = right.model_dump()
    return AuraBrainPolicy(
        **{name: (a[name] if rng.random() < 0.5 else b[name]) for name in a}
    )
