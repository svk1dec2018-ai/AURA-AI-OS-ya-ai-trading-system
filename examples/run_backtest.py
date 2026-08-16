from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aura.backtest.engine import BacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.domain.models import NormalizedCandle
from aura.risk.engine import RiskEngine, RiskLimits
from aura.strategy.ema import EmaCrossStrategy


def build_demo_candles() -> list[NormalizedCandle]:
    closes = [
        100, 99, 98, 97, 96, 95, 96, 97, 99, 101, 103, 105,
        104, 102, 100, 98, 96, 95, 97, 100, 103, 106, 108, 110,
    ]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[NormalizedCandle] = []
    previous = Decimal(str(closes[0]))
    for index, value in enumerate(closes):
        close = Decimal(str(value))
        open_price = previous
        candles.append(
            NormalizedCandle(
                symbol="DEMO/USD",
                venue="SIM",
                timeframe="1m",
                open_time=start + timedelta(minutes=index),
                close_time=start + timedelta(minutes=index + 1),
                open=open_price,
                high=max(open_price, close),
                low=min(open_price, close),
                close=close,
                volume=Decimal("100"),
                closed=True,
            )
        )
        previous = close
    return candles


def main() -> None:
    strategy = EmaCrossStrategy(fast=3, slow=5)
    risk = RiskEngine(
        RiskLimits(
            max_order_notional_pct=Decimal("5"),
            max_gross_exposure_pct=Decimal("50"),
            max_drawdown_pct=Decimal("10"),
            max_daily_loss_pct=Decimal("4"),
        )
    )
    pipeline = DecisionPipeline(strategy, risk)
    engine = BacktestEngine(
        pipeline=pipeline,
        starting_cash=Decimal("10000"),
        requested_quantity=Decimal("1"),
        fee_bps=Decimal("5"),
    )
    result = engine.run(build_demo_candles())
    print(result)


if __name__ == "__main__":
    main()
