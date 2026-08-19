from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.domain.models import NormalizedCandle
from aura.evolution.core import FitnessPolicy, StrategyGenome
from aura.evolution.evaluator import CausalBacktestEvolutionEvaluator
from aura.evolution.paper_tracker import PaperGenomePerformanceTracker
from aura.research.paper_evidence import PaperTradeOutcome
from aura.research.robustness import WalkForwardPlan
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.ema import EmaCrossStrategy


def _candles(count: int = 80) -> tuple[NormalizedCandle, ...]:
    candles = []
    start = datetime(2026, 1, 1, tzinfo=UTC)
    price = Decimal(100)
    for index in range(count):
        direction = Decimal(2) if (index // 6) % 2 == 0 else Decimal(-2)
        close = max(Decimal(10), price + direction)
        candles.append(
            NormalizedCandle(
                symbol="TEST",
                venue="PAPER",
                timeframe="1m",
                open_time=start + timedelta(minutes=index),
                close_time=start + timedelta(minutes=index + 1),
                open=price,
                high=max(price, close),
                low=min(price, close),
                close=close,
                volume=Decimal(100),
                closed=True,
            )
        )
        price = close
    return tuple(candles)


def _strategy(genome: StrategyGenome) -> EmaCrossStrategy:
    fast = int(genome.parameters["fast"])
    gap = int(genome.parameters["gap"])
    return EmaCrossStrategy(fast=fast, slow=fast + gap)


def _risk() -> RiskEngine:
    return RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(200),
            max_symbol_exposure_pct=Decimal(200),
            max_drawdown_pct=Decimal(100),
            max_daily_loss_pct=Decimal(100),
        )
    )


@pytest.mark.asyncio
async def test_evaluator_uses_walk_forward_and_monte_carlo_without_fake_paper() -> None:
    evaluator = CausalBacktestEvolutionEvaluator(
        candles=_candles(),
        strategy_factory=_strategy,
        risk_engine_factory=_risk,
        walk_forward_plan=WalkForwardPlan(train_size=30, test_size=10, step_size=10),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(1),
        fee_bps=Decimal("0.5"),
        slippage_bps=Decimal("0.5"),
        monte_carlo_paths=100,
        monte_carlo_block_size=3,
    )
    result = await evaluator.evaluate(
        StrategyGenome(family="ema", parameters={"fast": 3, "gap": 4})
    )
    assert len(result.walk_forward) == 5
    assert result.paper is None
    assert result.in_sample.trades >= 0
    assert result.monte_carlo_p95_drawdown_pct >= 0


@pytest.mark.asyncio
async def test_evaluator_propagates_measured_paper_incidents_to_promotion_gates() -> None:
    genome = StrategyGenome(family="ema", parameters={"fast": 3, "gap": 4})
    tracker = PaperGenomePerformanceTracker(starting_equity=Decimal(10000))
    tracker.record_trade(
        genome,
        PaperTradeOutcome(
            trade_id="paper-1",
            symbol="TEST",
            gross_pnl=Decimal(25),
        ),
    )
    tracker.record_reconciliation_incident(genome, incident_id="reconcile-1")
    tracker.record_operational_incident(genome, incident_id="feed-gap-1")
    evaluator = CausalBacktestEvolutionEvaluator(
        candles=_candles(),
        strategy_factory=_strategy,
        risk_engine_factory=_risk,
        walk_forward_plan=WalkForwardPlan(train_size=30, test_size=10, step_size=10),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(1),
        monte_carlo_paths=50,
        monte_carlo_block_size=3,
        paper_provider=tracker,
    )

    result = await evaluator.evaluate(genome)

    assert result.paper is not None
    assert result.reconciliation_incidents == 1
    assert result.operational_incidents == 1
    failures = FitnessPolicy().paper_failures(result)
    assert "reconciliation_incident" in failures
    assert "operational_incident" in failures
