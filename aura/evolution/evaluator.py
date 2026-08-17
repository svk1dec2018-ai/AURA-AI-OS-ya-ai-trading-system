from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from decimal import Decimal
from statistics import fmean, pstdev
from typing import Protocol

from aura.backtest.engine import BacktestEngine, BacktestResult
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import NormalizedCandle
from aura.evolution.core import CandidateEvaluation, PerformanceSlice, StrategyGenome
from aura.portfolio.instruments import InstrumentLedgerSpec
from aura.research.robustness import WalkForwardPlan, bootstrap_monte_carlo
from aura.risk.engine import RiskEngine
from aura.strategy.base import Strategy

StrategyFactory = Callable[[StrategyGenome], Strategy]
RiskEngineFactory = Callable[[], RiskEngine]


class PaperPerformanceProvider(Protocol):
    def performance_for(self, genome: StrategyGenome) -> PerformanceSlice | None: ...


class CausalBacktestEvolutionEvaluator:
    """Build measured evolution evidence from AURA's shared causal backtest path.

    Each candidate is evaluated with fresh Strategy/RiskEngine instances. Rolling
    OOS windows receive only prior candles as warm-up and trading starts exactly
    at the test boundary. Monte Carlo is bootstrapped from aggregated OOS period
    returns. Paper evidence is supplied separately from real AURA paper/demo runs;
    missing paper evidence deliberately prevents paper-champion promotion.
    """

    def __init__(
        self,
        *,
        candles: tuple[NormalizedCandle, ...],
        strategy_factory: StrategyFactory,
        risk_engine_factory: RiskEngineFactory,
        walk_forward_plan: WalkForwardPlan,
        starting_cash: Decimal,
        requested_quantity: Decimal,
        fee_bps: Decimal = Decimal(0),
        slippage_bps: Decimal = Decimal(0),
        monte_carlo_paths: int = 1000,
        monte_carlo_block_size: int = 5,
        monte_carlo_seed: int = 0,
        paper_provider: PaperPerformanceProvider | None = None,
        instrument_specs: dict[str, InstrumentLedgerSpec] | None = None,
    ) -> None:
        if not candles:
            raise ValueError("evolution evaluator requires candles")
        if len({(item.symbol, item.timeframe) for item in candles}) != 1:
            raise ValueError("one symbol/timeframe series is required per evaluator")
        if starting_cash <= 0 or requested_quantity <= 0:
            raise ValueError("starting_cash/requested_quantity must be positive")
        if monte_carlo_paths <= 0 or monte_carlo_block_size <= 0:
            raise ValueError("invalid Monte Carlo configuration")
        self.candles = candles
        self.strategy_factory = strategy_factory
        self.risk_engine_factory = risk_engine_factory
        self.walk_forward_plan = walk_forward_plan
        self.starting_cash = starting_cash
        self.requested_quantity = requested_quantity
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.monte_carlo_paths = monte_carlo_paths
        self.monte_carlo_block_size = monte_carlo_block_size
        self.monte_carlo_seed = monte_carlo_seed
        self.paper_provider = paper_provider
        self.instrument_specs = dict(instrument_specs or {})

    async def evaluate(self, genome: StrategyGenome) -> CandidateEvaluation:
        return await asyncio.to_thread(self._evaluate_sync, genome)

    def _evaluate_sync(self, genome: StrategyGenome) -> CandidateEvaluation:
        splits = self.walk_forward_plan.splits(len(self.candles))
        first = splits[0]
        in_sample_candles = list(self.candles[first.train_start : first.train_end])
        in_sample = self._run_slice(
            genome,
            in_sample_candles,
            label="in_sample",
            signal_start_index=0,
        )

        fold_metrics: list[PerformanceSlice] = []
        oos_returns: list[float] = []
        for split in splits:
            probe_strategy = self.strategy_factory(genome)
            warmup = max(0, int(probe_strategy.warmup_bars))
            warmup_start = max(split.train_start, split.test_start - warmup)
            window = list(self.candles[warmup_start : split.test_end])
            signal_start = split.test_start - warmup_start
            result = self._run_backtest(genome, window, signal_start_index=signal_start)
            test_returns = result.period_returns[signal_start:]
            oos_returns.extend(float(value) for value in test_returns)
            fold_metrics.append(
                _performance_from_result(
                    f"walk_forward_{split.fold}",
                    result,
                    returns=test_returns,
                    slippage_bps=self.slippage_bps,
                )
            )

        usable_returns = [value for value in oos_returns if math.isfinite(value)]
        if not usable_returns:
            usable_returns = [0.0]
        block_size = min(self.monte_carlo_block_size, len(usable_returns))
        monte_carlo = bootstrap_monte_carlo(
            usable_returns,
            paths=self.monte_carlo_paths,
            block_size=block_size,
            seed=self.monte_carlo_seed,
        )
        paper = self.paper_provider.performance_for(genome) if self.paper_provider else None
        return CandidateEvaluation(
            genome=genome,
            in_sample=in_sample,
            walk_forward=tuple(fold_metrics),
            monte_carlo_p05_return_pct=monte_carlo.p05_terminal_return * 100.0,
            monte_carlo_p95_drawdown_pct=monte_carlo.p95_max_drawdown * 100.0,
            paper=paper,
        )

    def _run_slice(
        self,
        genome: StrategyGenome,
        candles: list[NormalizedCandle],
        *,
        label: str,
        signal_start_index: int,
    ) -> PerformanceSlice:
        result = self._run_backtest(
            genome,
            candles,
            signal_start_index=signal_start_index,
        )
        returns = result.period_returns[signal_start_index:]
        return _performance_from_result(
            label,
            result,
            returns=returns,
            slippage_bps=self.slippage_bps,
        )

    def _run_backtest(
        self,
        genome: StrategyGenome,
        candles: list[NormalizedCandle],
        *,
        signal_start_index: int,
    ) -> BacktestResult:
        strategy = self.strategy_factory(genome)
        risk_engine = self.risk_engine_factory()
        return BacktestEngine(
            DecisionPipeline(strategy, risk_engine),
            starting_cash=self.starting_cash,
            requested_quantity=self.requested_quantity,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            instrument_specs=self.instrument_specs,
        ).run(candles, signal_start_index=signal_start_index)


def _performance_from_result(
    label: str,
    result: BacktestResult,
    *,
    returns: tuple[Decimal, ...],
    slippage_bps: Decimal,
) -> PerformanceSlice:
    values = [float(value) for value in returns]
    nonzero = [value for value in values if value != 0.0]
    positive = [value for value in nonzero if value > 0]
    negative = [value for value in nonzero if value < 0]
    net_return = float(result.ending_equity / result.starting_equity - Decimal(1)) * 100.0
    expectancy = net_return / result.fills if result.fills else 0.0
    if negative:
        profit_factor = sum(positive) / abs(sum(negative))
    elif positive:
        profit_factor = 99.0
    else:
        profit_factor = 0.0
    if len(values) > 1 and pstdev(values) > 0:
        sharpe = fmean(values) / pstdev(values) * math.sqrt(len(values))
    else:
        sharpe = 0.0
    win_rate = len(positive) / len(nonzero) if nonzero else 0.0
    return PerformanceSlice(
        label=label,
        trades=result.fills,
        net_return_pct=net_return,
        expectancy_pct=expectancy,
        profit_factor=max(0.0, profit_factor),
        max_drawdown_pct=float(result.max_drawdown_pct),
        sharpe=sharpe,
        win_rate=win_rate,
        avg_slippage_bps=float(slippage_bps),
    )
