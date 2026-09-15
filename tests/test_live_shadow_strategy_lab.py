from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import aura.research.live_shadow_strategy_lab as live_shadow_module
from aura.domain.models import NormalizedCandle
from aura.evolution.core import StrategyGenome
from aura.research.live_shadow_strategy_lab import LiveShadowPolicy, LiveShadowStrategyLab
from aura.research.strategy_mutation import mutate_autonomous_genome
from aura.runtime.free_public_strategy_lab import (
    FreePublicStrategyLabConfig,
    FreePublicStrategyLabRuntime,
)


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


def test_journal_replays_forward_history_metrics_and_pending_plans(
    tmp_path: Path,
) -> None:
    genome = _genome()
    policy = LiveShadowPolicy(
        horizon_bars=2,
        max_history_bars=100,
        min_resolved_for_confidence=2,
        min_abs_outcome_bps=0.0,
    )
    journal = tmp_path / "live_shadow_journal.jsonl"
    lab = LiveShadowStrategyLab([genome], policy=policy, journal_path=journal)
    candles = tuple(_candle(index, Decimal(100 + index)) for index in range(25))
    for candle in candles[:15]:
        lab.on_closed_candles([candle])
    before = lab.snapshots()
    pending_before = lab.pending_plans

    restored = LiveShadowStrategyLab([genome], policy=policy, journal_path=journal)

    assert restored.recovered_events == 15
    assert restored.processed_candles == 15
    assert restored.history_size("BTC-USD", "1s") == 15
    assert restored.pending_plans == pending_before
    assert restored.snapshots() == before
    assert restored.on_closed_candles([candles[14]]) == ()
    assert restored.processed_candles == 15

    control = LiveShadowStrategyLab([genome], policy=policy)
    for candle in candles:
        control.on_closed_candles([candle])
    for candle in candles[15:]:
        restored.on_closed_candles([candle])
    assert restored.snapshots() == control.snapshots()
    assert restored.pending_plans == control.pending_plans
    assert restored.total_plans == control.total_plans
    assert restored.total_resolved == control.total_resolved


def test_journal_recovers_evolved_population_and_refresh_counters(
    tmp_path: Path,
) -> None:
    elite = _genome()
    challenger = mutate_autonomous_genome(elite, seed=123)
    policy = LiveShadowPolicy(
        horizon_bars=2,
        max_history_bars=100,
        min_resolved_for_confidence=2,
        min_abs_outcome_bps=0.0,
    )
    journal = tmp_path / "population_journal.jsonl"
    lab = LiveShadowStrategyLab([elite], policy=policy, journal_path=journal)
    for index in range(20):
        lab.on_closed_candles([_candle(index, Decimal(100 + index))])
    resolved_at_refresh = lab.total_resolved
    lab.replace_population([elite, challenger], preserve_retained_metrics=True)
    expected = lab.snapshots()

    restored = LiveShadowStrategyLab([elite], policy=policy, journal_path=journal)

    assert {item.genome_id for item in restored.genomes} == {
        elite.genome_id,
        challenger.genome_id,
    }
    assert restored.snapshots() == expected
    assert restored.population_refreshes == 1
    assert restored.resolved_at_last_population_refresh == resolved_at_refresh
    assert restored.total_strategies_seen == 2
    assert restored.discarded_pending_on_refresh > 0


def test_journaled_candle_recovers_when_processing_crashes_after_append(
    tmp_path: Path,
    monkeypatch,
) -> None:
    genome = _genome()
    policy = LiveShadowPolicy(horizon_bars=2, max_history_bars=100)
    journal = tmp_path / "crash_journal.jsonl"
    lab = LiveShadowStrategyLab([genome], policy=policy, journal_path=journal)
    candle = _candle(0, Decimal(100))

    def fail_after_append(_candle_value):
        raise RuntimeError("simulated strategy evaluation crash")

    monkeypatch.setattr(lab, "_apply_candle", fail_after_append)
    with pytest.raises(RuntimeError, match="simulated strategy evaluation crash"):
        lab.on_closed_candles([candle])
    assert lab.processed_candles == 0

    restored = LiveShadowStrategyLab([genome], policy=policy, journal_path=journal)
    assert restored.processed_candles == 1
    assert restored.history_size("BTC-USD", "1s") == 1


def test_journal_sync_failure_does_not_claim_in_memory_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    genome = _genome()
    journal = tmp_path / "sync_failure_journal.jsonl"
    lab = LiveShadowStrategyLab([genome], journal_path=journal)
    candle = _candle(0, Decimal(100))

    def fail_fsync(_fd: int) -> None:
        raise OSError("simulated journal sync failure")

    monkeypatch.setattr(live_shadow_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated journal sync failure"):
        lab.on_closed_candles([candle])
    assert lab.processed_candles == 0
    assert lab.history_size("BTC-USD", "1s") == 0

    restored = LiveShadowStrategyLab([genome], journal_path=journal)
    assert restored.processed_candles == 1


def test_existing_journal_rejects_policy_or_initial_population_drift(
    tmp_path: Path,
) -> None:
    genome = _genome()
    journal = tmp_path / "configuration_journal.jsonl"
    LiveShadowStrategyLab(
        [genome],
        policy=LiveShadowPolicy(horizon_bars=2),
        journal_path=journal,
    )

    with pytest.raises(RuntimeError, match="policy changed"):
        LiveShadowStrategyLab(
            [genome],
            policy=LiveShadowPolicy(horizon_bars=3),
            journal_path=journal,
        )
    challenger = mutate_autonomous_genome(genome, seed=456)
    with pytest.raises(RuntimeError, match="initial live shadow population changed"):
        LiveShadowStrategyLab(
            [challenger],
            policy=LiveShadowPolicy(horizon_bars=2),
            journal_path=journal,
        )


def test_malformed_journal_record_fails_closed(tmp_path: Path) -> None:
    genome = _genome()
    journal = tmp_path / "malformed_journal.jsonl"
    LiveShadowStrategyLab([genome], journal_path=journal)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write('{"record_type":"candle","broken":true}\n')

    with pytest.raises(RuntimeError, match="invalid live shadow journal record"):
        LiveShadowStrategyLab([genome], journal_path=journal)


def test_public_strategy_runtime_restores_journal_population_and_counters(
    tmp_path: Path,
) -> None:
    config = FreePublicStrategyLabConfig(
        population_size=4,
        horizon_bars=2,
        max_history_bars=100,
        min_resolved_for_confidence=2,
        state_dir=tmp_path,
    )
    runtime = FreePublicStrategyLabRuntime(config, feed=object())
    for index in range(20):
        runtime.lab.on_closed_candles([_candle(index, Decimal(100 + index))])
    expected_ids = tuple(item.genome_id for item in runtime.lab.genomes)

    restored = FreePublicStrategyLabRuntime(config, feed=object())

    assert tuple(item.genome_id for item in restored.population) == expected_ids
    assert restored.counters.closed_candles == 20
    assert restored.counters.generated_plans == restored.lab.total_plans
    assert restored.counters.strategies_created == 4
    assert restored.lab.recovered_events == 20
