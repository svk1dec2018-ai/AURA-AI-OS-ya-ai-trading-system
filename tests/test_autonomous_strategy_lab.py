from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.domain.models import NormalizedCandle, SignalIntent
from aura.evolution.core import CandidateEvaluation, PerformanceSlice, StrategyGenome
from aura.research.autonomous_strategy_lab import (
    AutonomousDslStrategy,
    ProTraderResearchObjective,
    autonomous_strategy_gene_specs,
)


def _genome(**overrides) -> StrategyGenome:
    params = {
        "style": "trend",
        "fast_ema": 5,
        "slow_ema": 12,
        "rsi_period": 7,
        "momentum_lookback": 3,
        "breakout_lookback": 5,
        "band_lookback": 10,
        "volume_lookback": 5,
        "atr_lookback": 5,
        "min_votes": 2,
        "rsi_long": 52.0,
        "rsi_short": 48.0,
        "volume_ratio": 1.0,
        "atr_ratio": 0.8,
        "band_z": 1.0,
        "use_ema": "on",
        "use_rsi": "on",
        "use_momentum": "on",
        "use_breakout": "on",
        "use_bollinger": "off",
        "use_volume": "on",
        "use_atr": "on",
    }
    params.update(overrides)
    return StrategyGenome(family="autonomous_strategy_dsl.v1", parameters=params)


def _candles(count: int = 30) -> list[NormalizedCandle]:
    start = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    result = []
    price = Decimal("100")
    for index in range(count):
        next_price = price + Decimal("1")
        result.append(
            NormalizedCandle(
                symbol="TEST",
                venue="PAPER",
                timeframe="1m",
                open_time=start + timedelta(minutes=index),
                close_time=start + timedelta(minutes=index + 1),
                open=price,
                high=next_price + Decimal("0.2"),
                low=price - Decimal("0.2"),
                close=next_price,
                volume=Decimal(100 + index * 5),
                closed=True,
            )
        )
        price = next_price
    return result


def test_autonomous_gene_space_contains_no_risk_engine_controls() -> None:
    names = {item.name for item in autonomous_strategy_gene_specs()}
    assert "risk_per_trade" not in names
    assert "max_drawdown" not in names
    assert "kill_switch" not in names
    assert {"style", "fast_ema", "slow_ema", "use_breakout", "use_bollinger"} <= names


def test_autonomous_dsl_can_create_directional_strategy_signal() -> None:
    strategy = AutonomousDslStrategy(_genome())
    signal = strategy.on_closed_candle(_candles(max(strategy.warmup_bars, 35)))
    assert signal is not None
    assert signal.intent == SignalIntent.LONG
    assert signal.strategy_id.startswith("research.autonomous_strategy_dsl.v1")


def _slice(label: str, *, trades: int, win_rate: float, expectancy: float) -> PerformanceSlice:
    return PerformanceSlice(
        label=label,
        trades=trades,
        net_return_pct=12.0,
        expectancy_pct=expectancy,
        profit_factor=1.5,
        max_drawdown_pct=6.0,
        sharpe=1.2,
        win_rate=win_rate,
        avg_slippage_bps=2.0,
    )


def test_pro_trader_objective_rewards_accuracy_only_with_enough_samples() -> None:
    genome = _genome()
    strong = CandidateEvaluation(
        genome=genome,
        in_sample=_slice("in", trades=100, win_rate=0.82, expectancy=0.1),
        walk_forward=(
            _slice("wf1", trades=100, win_rate=0.82, expectancy=0.1),
            _slice("wf2", trades=100, win_rate=0.80, expectancy=0.1),
            _slice("wf3", trades=100, win_rate=0.81, expectancy=0.1),
        ),
        monte_carlo_p05_return_pct=2.0,
        monte_carlo_p95_drawdown_pct=10.0,
    )
    tiny = CandidateEvaluation(
        genome=genome,
        in_sample=_slice("in", trades=5, win_rate=0.95, expectancy=0.1),
        walk_forward=(
            _slice("wf1", trades=5, win_rate=0.95, expectancy=0.1),
            _slice("wf2", trades=5, win_rate=0.95, expectancy=0.1),
            _slice("wf3", trades=5, win_rate=0.95, expectancy=0.1),
        ),
        monte_carlo_p05_return_pct=2.0,
        monte_carlo_p95_drawdown_pct=10.0,
    )
    objective = ProTraderResearchObjective(min_oos_trades_for_confidence=200)
    assert objective.score(strong) > objective.score(tiny)
    assert "pro_trader_sample_too_small" in objective.research_failures(tiny)
    assert "pro_trader_sample_too_small" not in objective.research_failures(strong)
