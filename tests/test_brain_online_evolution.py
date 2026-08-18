from datetime import UTC, datetime, timedelta
from pathlib import Path

from aura.evolution.brain_online import (
    BrainPaperChampionManager,
    BrainPaperPromotionPolicy,
)
from aura.evolution.brain_optimizer import BrainOptimizerConfig, BrainResearchOptimizer
from aura.evolution.brain_policy import AuraBrainPolicy
from aura.evolution.brain_replay import BrainReplaySample, SampleOrigin


def _sample(
    index: int,
    *,
    net_return_pct: float = 0.2,
    origin: SampleOrigin = SampleOrigin.HISTORICAL,
) -> BrainReplaySample:
    return BrainReplaySample(
        sample_id=f"sample-{index}",
        decision_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
        symbol="XAUUSD",
        timeframe="1m",
        regime="trend",
        memo_confidence=0.80,
        directional_margin=0.30,
        deliberation_disagreement=0.20,
        failed_agent_fraction=0.0,
        execution_spread_bps=2.0,
        estimated_slippage_bps=1.0,
        net_return_pct=net_return_pct,
        origin=origin,
    )


def test_brain_optimizer_uses_sealed_holdout_and_returns_bounded_policy() -> None:
    samples = tuple(_sample(i) for i in range(120))
    optimizer = BrainResearchOptimizer(
        BrainOptimizerConfig(
            minimum_samples=100,
            population_size=8,
            generations=2,
            elite_count=2,
            minimum_validation_trades=5,
            minimum_holdout_trades=5,
        )
    )
    result = optimizer.optimize(samples, baseline=AuraBrainPolicy())
    policy = AuraBrainPolicy.from_genome(result.genome)
    assert result.holdout_passed
    assert result.validation.selected_trades >= 5
    assert result.sealed_holdout.selected_trades >= 5
    assert 0.05 <= policy.ceo_directional_margin <= 0.50
    assert 0.40 <= policy.min_opportunity_confidence <= 0.95
    assert 1.0 <= policy.max_execution_spread_bps <= 100.0


def test_forward_challenger_requires_new_live_samples_and_never_live_promotes(
    tmp_path: Path,
) -> None:
    manager = BrainPaperChampionManager(
        tmp_path,
        promotion_policy=BrainPaperPromotionPolicy(
            min_forward_trades=10,
            min_profit_factor=1.0,
            max_drawdown_pct=20.0,
        ),
    )
    genome = AuraBrainPolicy().to_genome()
    created_at = datetime(2026, 1, 2, tzinfo=UTC)
    manager.install_research_challenger(
        genome,
        research_score=1.0,
        created_at=created_at,
    )

    pre_creation_live = _sample(0, origin=SampleOrigin.LIVE_BROKER).model_copy(
        update={"decision_time": created_at - timedelta(minutes=1)}
    )
    assert not manager.observe(pre_creation_live)
    assert not manager.observe(
        _sample(3000, origin=SampleOrigin.HISTORICAL).model_copy(
            update={"decision_time": created_at + timedelta(minutes=1)}
        )
    )

    for index in range(10):
        sample = _sample(2000 + index, origin=SampleOrigin.LIVE_BROKER).model_copy(
            update={"decision_time": created_at + timedelta(minutes=index + 1)}
        )
        assert manager.observe(sample)

    assert manager.try_promote()
    assert manager.paper_champion is not None
    text = (tmp_path / "brain_paper_champion.json").read_text(encoding="utf-8")
    assert '"validation_source": "live_broker"' in text
    assert '"live_approved": false' in text
    assert '"live_money_enabled": false' in text
