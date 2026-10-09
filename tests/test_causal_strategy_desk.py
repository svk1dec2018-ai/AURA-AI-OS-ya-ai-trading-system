from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from aura.agents.models import AgentContext
from aura.agents.specialists import TechnicalSpecialist
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.prime.ensemble import ModelVote, PrimeModelEnsemble, VoteQuality
from aura.research.blueprint_compiler import compile_blueprint
from aura.research.strategy_catalog import STRATEGY_SETUPS
from aura.research.strategy_factory import ExitPrimitive, StrategyBlueprint, StrategyPrimitive
from aura.strategy.causal_indicators import (
    choppiness,
    donchian_vote,
    order_block_retest_vote,
    supertrend_vote,
)
from aura.strategy.desk import CausalStrategyDesk


def _bars(prices, *, spread=Decimal("0.2")):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    output = []
    for i, (o, c) in enumerate(prices):
        o, c = Decimal(str(o)), Decimal(str(c))
        output.append(
            NormalizedCandle(
                symbol="X",
                venue="TEST",
                timeframe="5m",
                open_time=start + timedelta(minutes=5 * i),
                close_time=start + timedelta(minutes=5 * (i + 1)),
                open=o,
                high=max(o, c) + spread,
                low=min(o, c) - spread,
                close=c,
                volume=100,
                closed=True,
            )
        )
    return output


def _blueprint(confirmations=()):
    return StrategyBlueprint(
        family="test",
        market_scope=("X",),
        timeframe_scope=("5m",),
        entries=(StrategyPrimitive.EMA_TREND,),
        confirmations=confirmations,
        exits=(ExitPrimitive.ATR_STOP,),
        parameters={"ema_fast": 8, "ema_slow": 21, "minimum_confirmations": 1},
    )


def test_donchian_uses_prior_channel_and_requires_close_break():
    bars = _bars([(100, 100)] * 20 + [(100, 102)])
    assert donchian_vote(bars) == 1
    bars[-1] = bars[-1].model_copy(update={"close": Decimal(100)})
    assert donchian_vote(bars) == 0  # wick beyond channel alone is insufficient
    bars = _bars([(100, 100)] * 20 + [(100, 98)])
    assert donchian_vote(bars) == -1


def test_supertrend_warmup_and_confirmed_reversal():
    up = _bars([(100 + i, 101 + i) for i in range(40)])
    assert supertrend_vote(up[:10]) == 0
    assert supertrend_vote(up) == 1
    down = _bars([(140 - i, 139 - i) for i in range(40)])
    assert supertrend_vote(down) == -1
    crash = up[-1].model_copy(
        update={
            "open": Decimal(140),
            "high": Decimal(141),
            "low": Decimal(79),
            "close": Decimal(80),
            "open_time": up[-1].close_time,
            "close_time": up[-1].close_time + timedelta(minutes=5),
        }
    )
    assert supertrend_vote(up + [crash]) == -1


def test_chop_distinguishes_trend_from_whipsaw_and_flat():
    trend = _bars([(100 + i, 101 + i) for i in range(40)])
    chop = _bars([(100, 101) if i % 2 else (101, 100) for i in range(40)])
    assert choppiness(trend) < 38.2
    assert choppiness(chop) > 61.8
    assert choppiness(_bars([(100, 100)] * 20, spread=Decimal(0))) == 100
    assert choppiness(trend[:5]) is None


def test_order_block_is_confirmed_then_consumed_or_invalidated():
    bars = _bars([(100, 100)] * 10 + [(100, 99), (100, 103), (103, 104), (100, 102)])
    assert order_block_retest_vote(bars, lookback=5) == 1
    assert order_block_retest_vote(bars[:-1], lookback=5) == 0
    second_touch = bars[-1].model_copy(
        update={
            "open_time": bars[-1].close_time,
            "close_time": bars[-1].close_time + timedelta(minutes=5),
        }
    )
    assert order_block_retest_vote(bars + [second_touch], lookback=5) == 0
    invalid = bars[-2].model_copy(
        update={"open": Decimal(99), "high": Decimal(100), "low": Decimal(97), "close": Decimal(98)}
    )
    assert order_block_retest_vote(bars[:-2] + [invalid, bars[-1]], lookback=5) == 0


def test_regime_filter_cannot_be_outvoted_by_other_confirmation():
    bars = _bars([(100 + i, 101 + i) for i in range(40)])
    strategy = compile_blueprint(
        _blueprint((StrategyPrimitive.RSI_STATE, StrategyPrimitive.RANGE_FILTER))
    )
    assert strategy.on_closed_candle(bars) is None  # RSI agrees, but range condition fails
    strategy = compile_blueprint(
        _blueprint((StrategyPrimitive.RSI_STATE, StrategyPrimitive.CHOP_FILTER))
    )
    assert strategy.on_closed_candle(bars).intent == SignalIntent.LONG


@pytest.mark.parametrize(
    "corruption", ["unclosed_old", "mixed_old", "duplicate", "overlap", "reverse"]
)
def test_compiler_rejects_invalid_consumed_history(corruption):
    bars = _bars([(100 + i, 101 + i) for i in range(65)])
    if corruption == "unclosed_old":
        bars[0] = bars[0].model_copy(update={"closed": False})
    if corruption == "mixed_old":
        bars[0] = bars[0].model_copy(update={"symbol": "Y"})
    if corruption == "duplicate":
        bars.insert(3, bars[3])
    if corruption == "overlap":
        bars[3] = bars[3].model_copy(update={"open_time": bars[2].open_time})
    if corruption == "reverse":
        bars[2], bars[3] = bars[3], bars[2]
    assert compile_blueprint(_blueprint()).on_closed_candle(bars) is None


def test_family_desk_does_not_count_correlated_setups_as_quorum():
    bars = _bars([(100 + i, 101 + i) for i in range(40)])
    desk = CausalStrategyDesk()
    signal = SimpleNamespace(intent=SignalIntent.LONG)
    strategy = SimpleNamespace(on_closed_candle=lambda _: signal)
    desk.strategies = (
        (SimpleNamespace(key="a", family="trend"), strategy),
        (SimpleNamespace(key="b", family="trend"), strategy),
    )
    decision = desk.evaluate(bars)
    assert decision.intent == SignalIntent.FLAT
    assert decision.supporting_families == ("trend",)
    assert decision.execution_authority is False
    desk.strategies += ((SimpleNamespace(key="c", family="breakout"), strategy),)
    assert desk.evaluate(bars).intent == SignalIntent.LONG


def test_family_desk_removes_internal_conflicts():
    desk = CausalStrategyDesk()

    def vote(intent):
        return SimpleNamespace(on_closed_candle=lambda _: SimpleNamespace(intent=intent))

    desk.strategies = tuple(
        (SimpleNamespace(key=key, family=family), vote(intent))
        for key, family, intent in (
            ("a", "trend", SignalIntent.LONG),
            ("b", "trend", SignalIntent.SHORT),
            ("c", "breakout", SignalIntent.LONG),
        )
    )
    result = desk.evaluate(_bars([(100 + i, 101 + i) for i in range(40)]))
    assert result.intent == SignalIntent.FLAT
    assert "trend" in result.conflicting_families


@pytest.mark.asyncio
async def test_technical_evidence_exposes_advisory_desk_without_new_agent_votes():
    candles = tuple(_bars([(100 + i, 101 + i) for i in range(45)]))
    context = AgentContext(
        correlation_id="desk",
        symbol="X",
        decision_timeframe="5m",
        candles=candles,
        created_at=candles[-1].close_time,
    )
    result = await TechnicalSpecialist().analyze(context)
    assert result.features["strategy_desk"]["active_setups"]
    assert not result.features["strategy_desk"]["execution_authority"]
    assert result.agent_id == "deterministic:technical:v1"


def test_all_catalog_candidates_are_executable_and_research_only():
    for setup in STRATEGY_SETUPS:
        compiled = compile_blueprint(setup.blueprint())
        assert compiled.blueprint.research_only
        assert not compiled.blueprint.live_approved


def test_ensemble_honors_strong_abstention():
    result = PrimeModelEnsemble(min_directional_margin=0.01).decide(
        (
            ModelVote(model_key="weak-long", intent=SignalIntent.LONG, confidence=0.1),
            ModelVote(model_key="no-trade", intent=SignalIntent.FLAT, confidence=0.95),
        )
    )
    assert result.intent == SignalIntent.FLAT
    assert "abstention" in result.reasons[0]


def test_zero_weight_models_do_not_satisfy_quorum():
    result = PrimeModelEnsemble().decide(
        (
            ModelVote(model_key="a", intent=SignalIntent.LONG, confidence=0.9, reliability=0),
            ModelVote(model_key="b", intent=SignalIntent.LONG, confidence=0.9, calibration=0),
        )
    )
    assert result.quality == VoteQuality.INSUFFICIENT


def test_duplicate_model_identity_is_rejected():
    vote = ModelVote(model_key="same", intent=SignalIntent.LONG, confidence=0.9)
    with pytest.raises(ValueError, match="unique"):
        PrimeModelEnsemble().decide((vote, vote))


def test_zero_margin_threshold_does_not_turn_a_tie_into_short():
    result = PrimeModelEnsemble(min_directional_margin=0).decide(
        (
            ModelVote(model_key="a", intent=SignalIntent.LONG, confidence=0.9),
            ModelVote(model_key="b", intent=SignalIntent.SHORT, confidence=0.9),
        )
    )
    assert result.intent == SignalIntent.FLAT


@pytest.mark.parametrize("direction", [1, -1])
def test_rsi_divergence_emits_only_after_two_confirmation_bars(direction):
    from aura.research.blueprint_compiler import _confirmed_rsi_divergence

    prices = [100] * 20 + [95, 85, 80, 90, 100, 100, 99, 101, 78, 85, 90]
    if direction < 0:
        prices = [200 - p for p in prices]
    history = _bars([(p, p) for p in prices])
    assert _confirmed_rsi_divergence(history[:-2], period=3) == 0
    assert _confirmed_rsi_divergence(history[:-1], period=3) == 0
    assert _confirmed_rsi_divergence(history, period=3) == direction


def test_prior_bar_pivot_reclaim_is_not_daily_pivot_or_future_level():
    from aura.research.blueprint_compiler import CompiledBlueprintStrategy

    history = _bars([(100, 100)] * 35 + [(99, 101)])
    strategy = CompiledBlueprintStrategy(_blueprint())
    assert strategy._primitive_vote(StrategyPrimitive.PIVOT_SUPPORT_RESISTANCE, history) == 1
    history[-1] = history[-1].model_copy(update={"open": Decimal(101), "close": Decimal(99)})
    assert strategy._primitive_vote(StrategyPrimitive.PIVOT_SUPPORT_RESISTANCE, history) == -1
