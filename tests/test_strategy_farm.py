import pytest

from aura.evolution.core import CandidateEvaluation, PerformanceSlice, StrategyGenome
from aura.research.autonomous_strategy_lab import ProTraderResearchObjective
from aura.research.strategy_farm import AutonomousStrategyResearchFarm, StrategyFarmConfig


class _Evaluator:
    async def evaluate(self, genome: StrategyGenome) -> CandidateEvaluation:
        score_seed = sum(ord(char) for char in genome.genome_id) % 10
        win_rate = 0.70 + score_seed / 100.0
        fold = PerformanceSlice(
            label="wf",
            trades=100,
            net_return_pct=10.0,
            expectancy_pct=0.1,
            profit_factor=1.4,
            max_drawdown_pct=5.0,
            sharpe=1.0,
            win_rate=win_rate,
            avg_slippage_bps=1.0,
        )
        return CandidateEvaluation(
            genome=genome,
            in_sample=fold.model_copy(update={"label": "in"}),
            walk_forward=(
                fold.model_copy(update={"label": "wf1"}),
                fold.model_copy(update={"label": "wf2"}),
                fold.model_copy(update={"label": "wf3"}),
            ),
            monte_carlo_p05_return_pct=1.0,
            monte_carlo_p95_drawdown_pct=8.0,
        )


@pytest.mark.asyncio
async def test_strategy_farm_evaluates_population_and_counts_virtual_trades() -> None:
    farm = AutonomousStrategyResearchFarm(
        _Evaluator(),
        config=StrategyFarmConfig(population_size=8, max_concurrent_evaluations=4),
        objective=ProTraderResearchObjective(min_oos_trades_for_confidence=200),
    )
    generation = await farm.run_generation()
    assert len(generation.evaluations) == 8
    assert len(generation.ranked) == 8
    assert generation.evaluated_trades == 8 * 400
    assert farm.total_candidate_evaluations == 8
    assert farm.total_evaluated_trades == 8 * 400
    assert all(item.genome.family == "autonomous_strategy_dsl.v1" for item in generation.ranked)
