from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from aura.data.mt5_demo import (
    MT5DemoClosedCandleSource,
    OfficialMT5Gateway,
    load_mt5_demo_credentials_from_env,
)
from aura.evolution.core import (
    EvolutionConfig,
    EvolutionJournal,
    FitnessPolicy,
    GeneKind,
    GeneSpec,
    PopulationEvolution,
    StrategyGenome,
)
from aura.evolution.evaluator import CausalBacktestEvolutionEvaluator
from aura.research.robustness import WalkForwardPlan
from aura.risk.engine import RiskEngine, RiskLimits
from aura.runtime.evolution_supervisor import DemoEvolutionPolicy, DemoEvolutionSupervisor
from aura.strategy.ema import EmaCrossStrategy


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run guarded AURA research evolution on Exness/MT5 DEMO historical candles."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--population", type=int, default=8)
    parser.add_argument("--generations", type=int, default=8)
    parser.add_argument("--cash", default="10000")
    parser.add_argument("--quantity", default="0.01")
    parser.add_argument("--fee-bps", default="0")
    parser.add_argument("--slippage-bps", default="1.0")
    parser.add_argument("--state-dir", default="runtime/evolution/mt5_demo")
    return parser.parse_args()


def _strategy(genome: StrategyGenome) -> EmaCrossStrategy:
    fast = int(genome.parameters["fast"])
    gap = int(genome.parameters["slow_gap"])
    return EmaCrossStrategy(fast=fast, slow=fast + gap)


def _risk() -> RiskEngine:
    return RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(5),
            max_gross_exposure_pct=Decimal(25),
            max_symbol_exposure_pct=Decimal(15),
            max_drawdown_pct=Decimal(10),
            max_daily_loss_pct=Decimal(4),
        )
    )


async def main() -> None:
    args = _args()
    if args.bars < 1000:
        raise ValueError("use at least 1000 closed bars for the demo research run")

    gateway = OfficialMT5Gateway()
    account = gateway.connect_demo(load_mt5_demo_credentials_from_env())
    try:
        universe = gateway.discover_universe()
        tradable = {item.venue_symbol for item in universe if item.tradable}
        if args.symbol not in tradable:
            raise RuntimeError(
                f"{args.symbol} is not a tradable symbol in this MT5 demo account; "
                "use the exact broker symbol/suffix"
            )
        candles = MT5DemoClosedCandleSource(gateway).fetch(
            args.symbol,
            args.timeframe,
            count=args.bars,
        )
    finally:
        gateway.shutdown()

    train = max(500, args.bars // 3)
    test = max(100, args.bars // 12)
    evaluator = CausalBacktestEvolutionEvaluator(
        candles=candles,
        strategy_factory=_strategy,
        risk_engine_factory=_risk,
        walk_forward_plan=WalkForwardPlan(train_size=train, test_size=test, step_size=test),
        starting_cash=Decimal(args.cash),
        requested_quantity=Decimal(args.quantity),
        fee_bps=Decimal(args.fee_bps),
        slippage_bps=Decimal(args.slippage_bps),
        monte_carlo_paths=1000,
        monte_carlo_block_size=5,
    )
    fitness = FitnessPolicy(
        min_walk_forward_folds=3,
        min_oos_trades=20,
        min_paper_trades=40,
    )
    evolution = PopulationEvolution(
        (
            GeneSpec(name="fast", kind=GeneKind.INTEGER, low=3, high=30),
            GeneSpec(name="slow_gap", kind=GeneKind.INTEGER, low=3, high=80),
        ),
        family=f"ema_cross:{args.symbol}:{args.timeframe}",
        config=EvolutionConfig(
            population_size=args.population,
            random_seed=7,
        ),
        fitness_policy=fitness,
    )
    result = await DemoEvolutionSupervisor(
        evolution=evolution,
        evaluator=evaluator,
        journal=EvolutionJournal(Path(args.state_dir)),
        fitness_policy=fitness,
        policy=DemoEvolutionPolicy(
            max_generations=args.generations,
            max_concurrent_evaluations=min(4, args.population),
            no_improvement_patience=min(5, args.generations),
        ),
    ).run()

    last = result.generations[-1]
    print(f"MT5 DEMO verified: login={account.login} server={account.server}")
    print(f"Closed candles: {len(candles)} {args.symbol}/{args.timeframe}")
    print(f"Generations evaluated: {len(result.generations)}")
    print(f"Best research genome: {last.best_genome_id} score={last.best_score:.4f}")
    print(
        "Paper champion: none until enough autonomous live paper/demo outcomes "
        "are supplied to the evolution evaluator. Real-money approval remains disabled."
    )


if __name__ == "__main__":
    asyncio.run(main())
