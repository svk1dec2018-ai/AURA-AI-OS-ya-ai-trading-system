from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.domain.models import NormalizedCandle
from aura.evolution.core import StrategyGenome
from aura.research.live_shadow_strategy_lab import LiveShadowPolicy, LiveShadowStrategyLab
from aura.research.strategy_mutation import mutate_autonomous_genome


def _genome() -> StrategyGenome:
    return StrategyGenome(
        family="autonomous_strategy_dsl.v1",
        parameters={
            "style": "trend",
            "fast_ema": 4,
            "slow_ema": 6,
            "rsi_period": 5,
            "momentum_lookback": 2,
            "breakout_lookback": 5,
            "band_lookback": 10,
            "volume_lookback": 5,
            "atr_lookback": 5,
            "min_votes": 1,
            "rsi_long": 51.0,
            "rsi_short": 49.0,
            "volume_ratio": 1.0,
            "atr_ratio": 0.8,
            "band_z": 1.0,
            "use_ema": "on",
            "use_rsi": "off",
            "use_momentum": "on",
            "use_breakout": "off",
            "use_bollinger": "off",
            "use_volume": "off",
            "use_atr": "off",
        },
    )


def _candle(index: int, price: Decimal) -> NormalizedCandle:
    start = datetime(2026, 8, 18, 0, 0, tzinfo=UTC) + timedelta(seconds=index)
    return NormalizedCandle(
        symbol="BTC-USD",
        venue="COINBASE_PUBLIC",
        timeframe="1s",
        open_time=start,
        close_time=start + timedelta(seconds=1),
        open=price,
        high=price + Decimal("0.2"),
        low=price - Decimal("0.2"),
        close=price + Decimal("0.1"),
        volume=Decimal(1),
        closed=True,
    )


def test_live_shadow_lab_resolves_forward_only_plans() -> None:
    lab = LiveShadowStrategyLab(
        [_genome()],
        policy=LiveShadowPolicy(
            horizon_bars=2,
            max_history_bars=100,
            min_resolved_for_confidence=2,
            min_abs_outcome_bps=0.0,
        ),
    )
    for index in range(20):
        lab.on_closed_candles([_candle(index, Decimal(100 + index))])
    assert lab.total_plans > 0
    assert lab.total_resolved > 0
    snapshot = lab.snapshots()[0]
    assert snapshot.resolved == lab.total_resolved
    assert snapshot.win_rate > 0.5
    assert snapshot.expectancy_bps > 0
    assert lab.pending_plans >= 0


def test_population_refresh_preserves_elite_metrics_and_market_history() -> None:
    elite = _genome()
    lab = LiveShadowStrategyLab(
        [elite],
        policy=LiveShadowPolicy(
            horizon_bars=2,
            max_history_bars=100,
            min_resolved_for_confidence=2,
            min_abs_outcome_bps=0.0,
        ),
    )
    for index in range(20):
        lab.on_closed_candles([_candle(index, Decimal(100 + index))])
    before = lab.snapshots()[0]
    assert before.resolved > 0
    assert lab.history_size("BTC-USD", "1s") == 20
    assert lab.pending_plans > 0

    challenger = mutate_autonomous_genome(elite, seed=123)
    assert challenger.content_hash != elite.content_hash
    assert challenger.parents == (elite.genome_id,)
    lab.replace_population([elite, challenger], preserve_retained_metrics=True)

    after_by_id = {item.genome_id: item for item in lab.snapshots()}
    assert after_by_id[elite.genome_id].resolved == before.resolved
    assert after_by_id[challenger.genome_id].resolved == 0
    assert lab.history_size("BTC-USD", "1s") == 20
    assert lab.pending_plans == 0
    assert lab.discarded_pending_on_refresh > 0
    assert lab.population_refreshes == 1
