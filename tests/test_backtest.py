from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.backtest.engine import BacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import NormalizedCandle, SignalIntent, StrategySignal
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.base import Strategy


class OneShotLong(Strategy):
    strategy_id = "test.one_shot"
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
            reason="test",
        )


def candle(i: int, open_price: str, close_price: str) -> NormalizedCandle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i)
    op = Decimal(open_price)
    cp = Decimal(close_price)
    return NormalizedCandle(
        symbol="X",
        venue="TEST",
        timeframe="1m",
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open=op,
        high=max(op, cp),
        low=min(op, cp),
        close=cp,
        volume=Decimal(1),
        closed=True,
    )


def test_signal_on_close_fills_next_bar_open() -> None:
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal(100),
            max_gross_exposure_pct=Decimal(100),
        )
    )
    pipeline = DecisionPipeline(OneShotLong(), risk)
    engine = BacktestEngine(
        pipeline=pipeline,
        starting_cash=Decimal(10000),
        requested_quantity=Decimal(1),
    )
    result = engine.run(
        [
            candle(0, "100", "100"),
            candle(1, "105", "110"),
            candle(2, "120", "125"),
        ]
    )

    assert result.orders == 1
    assert result.fills == 1
    position = engine.ledger.positions["X"]
    assert position.average_price == Decimal(120)
    assert result.ending_equity == Decimal(10005)
