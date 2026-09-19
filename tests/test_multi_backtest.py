from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.backtest.multi_engine import MultiSymbolBacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import NormalizedCandle, SignalIntent, StrategySignal
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.base import Strategy


class FirstBarLong(Strategy):
    def __init__(self, strategy_id: str, confidence: float = 0.8) -> None:
        self.strategy_id = strategy_id
        self.confidence = confidence
        self.warmup_bars = 1

    def on_closed_candle(self, history):
        if len(history) != 1:
            return None
        latest = history[-1]
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=latest.symbol,
            intent=SignalIntent.LONG,
            confidence=self.confidence,
            reference_price=latest.close,
            generated_at=latest.close_time,
            reason="first closed bar long",
        )


def _series(symbol: str) -> list[NormalizedCandle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values = [("100", "100"), ("101", "102")]
    candles: list[NormalizedCandle] = []
    for index, (open_price, close_price) in enumerate(values):
        open_value = Decimal(open_price)
        close_value = Decimal(close_price)
        candles.append(
            NormalizedCandle(
                symbol=symbol,
                venue="TEST",
                timeframe="1m",
                open_time=start + timedelta(minutes=index),
                close_time=start + timedelta(minutes=index + 1),
                open=open_value,
                high=max(open_value, close_value),
                low=min(open_value, close_value),
                close=close_value,
                volume=Decimal(100),
                closed=True,
            )
        )
    return candles


def test_multi_symbol_backtest_reserves_shared_portfolio_capacity() -> None:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(10),
        )
    )
    engine = MultiSymbolBacktestEngine(
        pipelines={
            "X": DecisionPipeline(FirstBarLong("x", confidence=0.9), risk),
            "Y": DecisionPipeline(FirstBarLong("y", confidence=0.8), risk),
        },
        starting_cash=Decimal(10000),
        requested_quantities={"X": Decimal(8), "Y": Decimal(8)},
    )

    result = engine.run({"Y": _series("Y"), "X": _series("X")})

    assert result.orders == 2
    assert result.fills == 2
    assert result.rejected_signals == 0
    assert result.symbols == ("X", "Y")
    assert engine.ledger.positions["X"].quantity == Decimal(8)
    assert engine.ledger.positions["Y"].quantity == Decimal(2)
    assert result.ending_equity == Decimal(10010)


def test_multi_symbol_backtest_requires_one_shared_risk_engine() -> None:
    with pytest.raises(ValueError, match="share one RiskEngine"):
        MultiSymbolBacktestEngine(
            pipelines={
                "X": DecisionPipeline(FirstBarLong("x"), RiskEngine(RiskLimits())),
                "Y": DecisionPipeline(FirstBarLong("y"), RiskEngine(RiskLimits())),
            },
            starting_cash=Decimal(10000),
            requested_quantities={"X": Decimal(1), "Y": Decimal(1)},
        )


def test_multi_symbol_backtest_applies_shared_adverse_slippage_and_fees() -> None:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(100),
        )
    )
    engine = MultiSymbolBacktestEngine(
        pipelines={"X": DecisionPipeline(FirstBarLong("x"), risk)},
        starting_cash=Decimal(10000),
        requested_quantities={"X": Decimal(2)},
        fee_bps=Decimal(10),
        slippage_bps=Decimal(10),
    )

    result = engine.run({"X": _series("X")})

    assert len(result.fill_records) == 1
    assert result.fill_records[0].price == Decimal("101.101")
    assert result.fill_records[0].fee == Decimal("0.202202")
