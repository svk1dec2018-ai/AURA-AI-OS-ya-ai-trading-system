from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.backtest.engine import BacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import NormalizedCandle, OrderRequest, Side, SignalIntent, StrategySignal
from aura.execution.paper import PaperBroker, PaperExecutionConfig
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.base import Strategy


class _OneShotLong(Strategy):
    strategy_id = "test.execution_parity"
    warmup_bars = 2

    def on_closed_candle(self, history):
        if len(history) != 2:
            return None
        latest = history[-1]
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=latest.symbol,
            intent=SignalIntent.LONG,
            confidence=1.0,
            reference_price=latest.close,
            generated_at=latest.close_time,
            reason="deterministic parity probe",
        )


class _FutureSignal(Strategy):
    strategy_id = "test.future_signal"

    def on_closed_candle(self, history):
        latest = history[-1]
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=latest.symbol,
            intent=SignalIntent.LONG,
            confidence=1.0,
            reference_price=latest.close,
            generated_at=latest.close_time + timedelta(seconds=1),
            reason="invalid future timestamp",
        )


def _candle(minute: int, open_price: str, close_price: str) -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    open_value = Decimal(open_price)
    close_value = Decimal(close_price)
    return NormalizedCandle(
        symbol="AURA-PARITY",
        venue="INTERNAL_FIXTURE",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=open_value,
        high=max(open_value, close_value),
        low=min(open_value, close_value),
        close=close_value,
        volume=Decimal(100),
        closed=True,
    )


def _pipeline(strategy: Strategy) -> DecisionPipeline:
    return DecisionPipeline(
        strategy,
        RiskEngine(
            RiskLimits(
                max_order_notional_pct=Decimal(100),
                max_gross_exposure_pct=Decimal(100),
            )
        ),
    )


@pytest.mark.asyncio
async def test_backtest_and_paper_share_identical_fill_and_cost_math() -> None:
    candles = [_candle(0, "100", "101"), _candle(1, "101", "102"), _candle(2, "110", "111")]
    backtest = BacktestEngine(
        _pipeline(_OneShotLong()),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(2),
        fee_bps=Decimal(10),
        slippage_bps=Decimal(10),
    ).run(candles)
    assert len(backtest.fill_records) == 1

    broker = PaperBroker(
        PaperExecutionConfig(fee_bps=Decimal(10), slippage_bps=Decimal(10))
    )
    await broker.connect()
    await broker.submit_order(
        OrderRequest(
            order_id="parity-order",
            client_order_id="parity-client",
            symbol="AURA-PARITY",
            venue="INTERNAL_FIXTURE",
            side=Side.BUY,
            quantity=Decimal(2),
            created_at=candles[1].close_time,
        )
    )
    paper_fills = await broker.on_candle(candles[2])

    assert len(paper_fills) == 1
    assert backtest.fill_records[0].price == paper_fills[0].price == Decimal("110.110")
    assert backtest.fill_records[0].fee == paper_fills[0].fee == Decimal("0.220220")


def test_future_dated_strategy_signal_is_rejected() -> None:
    engine = BacktestEngine(
        _pipeline(_FutureSignal()),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(1),
    )
    with pytest.raises(ValueError, match="after the latest closed candle"):
        engine.run([_candle(0, "100", "101"), _candle(1, "101", "102")])


def test_out_of_order_or_overlapping_series_is_rejected() -> None:
    engine = BacktestEngine(
        _pipeline(_OneShotLong()),
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(1),
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        engine.run([_candle(1, "101", "102"), _candle(0, "100", "101")])
