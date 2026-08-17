from __future__ import annotations

import asyncio
import math
from datetime import datetime
from statistics import fmean, pstdev

from pydantic import BaseModel, ConfigDict, Field

from aura.evolution.brain_policy import AuraBrainPolicy
from aura.evolution.core import CandidateEvaluation, PerformanceSlice, StrategyGenome
from aura.research.robustness import bootstrap_monte_carlo


class BrainReplaySample(BaseModel):
    """One historically recorded shadow/paper decision plus its later outcome.

    Decision fields must be captured at `decision_time`. `net_return_pct` is joined
    only after the outcome is known and is used exclusively by offline research.
    """

    model_config = ConfigDict(frozen=True)

    sample_id: str = Field(min_length=1)
    decision_time: datetime
    symbol: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    regime: str = "unknown"
    memo_confidence: float = Field(ge=0, le=1)
    directional_margin: float = Field(ge=0, le=1)
    deliberation_disagreement: float = Field(ge=0, le=1)
    failed_agent_fraction: float = Field(ge=0, le=1)
    execution_spread_bps: float = Field(ge=0)
    estimated_slippage_bps: float = Field(ge=0)
    net_return_pct: float


class BrainPolicyReplayEvaluator:
    """Fast chronological research evaluator for AURA brain-policy genomes.

    It evaluates only previously observed decisions/outcomes, preserves time order,
    creates rolling OOS folds, and emits *no paper evidence*. Therefore a strong
    replay candidate can become a challenger but never a paper/live champion by
    replay alone.
    """

    def __init__(
        self,
        samples: tuple[BrainReplaySample, ...] | list[BrainReplaySample],
        *,
        train_size: int = 200,
        test_size: int = 50,
        step_size: int = 50,
        monte_carlo_paths: int = 1000,
        monte_carlo_block_size: int = 5,
        seed: int = 0,
    ) -> None:
        ordered = tuple(sorted(samples, key=lambda item: (item.decision_time, item.sample_id)))
        if len({item.sample_id for item in ordered}) != len(ordered):
            raise ValueError("brain replay sample_id values must be unique")
        if train_size <= 0 or test_size <= 0 or step_size <= 0:
            raise ValueError("brain replay window sizes must be positive")
        if len(ordered) < train_size + test_size:
            raise ValueError("not enough brain replay samples for one OOS fold")
        if monte_carlo_paths <= 0 or monte_carlo_block_size <= 0:
            raise ValueError("invalid Monte Carlo configuration")
        self.samples = ordered
        self.train_size = train_size
        self.test_size = test_size
        self.step_size = step_size
        self.monte_carlo_paths = monte_carlo_paths
        self.monte_carlo_block_size = monte_carlo_block_size
        self.seed = seed

    async def evaluate(self, genome: StrategyGenome) -> CandidateEvaluation:
        return await asyncio.to_thread(self._evaluate_sync, genome)

    def _evaluate_sync(self, genome: StrategyGenome) -> CandidateEvaluation:
        policy = AuraBrainPolicy.from_genome(genome)
        first_train = self.samples[: self.train_size]
        in_sample = _performance(
            "brain_replay_in_sample",
            _selected_returns(first_train, policy),
        )

        folds: list[PerformanceSlice] = []
        oos_returns: list[float] = []
        fold = 0
        test_start = self.train_size
        while test_start + self.test_size <= len(self.samples):
            test = self.samples[test_start : test_start + self.test_size]
            returns = _selected_returns(test, policy)
            oos_returns.extend(returns)
            folds.append(_performance(f"brain_replay_oos_{fold}", returns))
            fold += 1
            test_start += self.step_size
        if not folds:
            raise ValueError("brain replay produced no OOS folds")

        monte_values = oos_returns or [0.0]
        monte = bootstrap_monte_carlo(
            monte_values,
            paths=self.monte_carlo_paths,
            block_size=min(self.monte_carlo_block_size, len(monte_values)),
            seed=self.seed,
        )
        return CandidateEvaluation(
            genome=genome,
            in_sample=in_sample,
            walk_forward=tuple(folds),
            monte_carlo_p05_return_pct=monte.p05_terminal_return * 100.0,
            monte_carlo_p95_drawdown_pct=monte.p95_max_drawdown * 100.0,
            paper=None,
        )


def policy_allows(sample: BrainReplaySample, policy: AuraBrainPolicy) -> bool:
    return (
        sample.memo_confidence >= policy.min_opportunity_confidence
        and sample.directional_margin >= policy.ceo_directional_margin
        and sample.deliberation_disagreement <= policy.max_deliberation_disagreement
        and sample.failed_agent_fraction <= policy.max_failed_agent_fraction
        and sample.execution_spread_bps <= policy.max_execution_spread_bps
        and sample.estimated_slippage_bps <= policy.max_execution_slippage_bps
    )


def _selected_returns(
    samples: tuple[BrainReplaySample, ...],
    policy: AuraBrainPolicy,
) -> list[float]:
    return [item.net_return_pct for item in samples if policy_allows(item, policy)]


def _performance(label: str, returns_pct: list[float]) -> PerformanceSlice:
    if not returns_pct:
        return PerformanceSlice(
            label=label,
            trades=0,
            net_return_pct=0.0,
            expectancy_pct=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            sharpe=0.0,
            win_rate=0.0,
            avg_slippage_bps=0.0,
        )
    gross_factors = [1.0 + value / 100.0 for value in returns_pct]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for factor in gross_factors:
        equity *= max(0.0, factor)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    positives = [value for value in returns_pct if value > 0]
    negatives = [value for value in returns_pct if value < 0]
    if negatives:
        profit_factor = sum(positives) / abs(sum(negatives))
    elif positives:
        profit_factor = 99.0
    else:
        profit_factor = 0.0
    std = pstdev(returns_pct) if len(returns_pct) > 1 else 0.0
    sharpe = fmean(returns_pct) / std * math.sqrt(len(returns_pct)) if std > 0 else 0.0
    return PerformanceSlice(
        label=label,
        trades=len(returns_pct),
        net_return_pct=(equity - 1.0) * 100.0,
        expectancy_pct=fmean(returns_pct),
        profit_factor=max(0.0, profit_factor),
        max_drawdown_pct=max_drawdown,
        sharpe=sharpe,
        win_rate=len(positives) / len(returns_pct),
        avg_slippage_bps=0.0,
    )
