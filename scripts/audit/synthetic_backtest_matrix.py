import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aura.backtest.engine import BacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.data.public_history import CoinbaseExchangeHistoryClient, PublicHistoryError
from aura.domain.models import NormalizedCandle
from aura.research.blueprint_compiler import compile_blueprint
from aura.research.strategy_catalog import STRATEGY_SETUPS
from aura.risk.engine import RiskEngine, RiskLimits


def run(setup, bars, tf, scenario):
    blueprint = setup.blueprint().model_copy(
        update={"market_scope": ("X",), "timeframe_scope": (tf,)}
    )
    strategy = compile_blueprint(blueprint)
    result = BacktestEngine(
        DecisionPipeline(strategy, RiskEngine(RiskLimits())),
        Decimal(100000),
        Decimal(1),
        fee_bps=Decimal(2),
        slippage_bps=Decimal(2),
    ).run(bars, signal_start_index=strategy.warmup_bars)
    return {
        "strategy": setup.key,
        "timeframe": tf,
        "scenario": scenario,
        "orders": result.orders,
        "fills": result.fills,
        "rejected": result.rejected_signals,
        "ending_equity": str(result.ending_equity),
        "drawdown_pct": str(result.max_drawdown_pct),
        "coverage": "FILLS" if result.fills else "NO_TRIGGER",
    }


rows = []
for tf, minutes in [
    ("1m", 1),
    ("5m", 5),
    ("15m", 15),
    ("30m", 30),
    ("1h", 60),
    ("4h", 240),
    ("1d", 1440),
]:
    for scenario in ["trend", "range", "shock"]:
        bars = []
        previous = 100.0
        for i in range(300):
            close = (
                100 + i * 0.12 + math.sin(i * 0.6) * 0.3
                if scenario == "trend"
                else 100 + math.sin(i * 0.4) * 3
                if scenario == "range"
                else 100 + math.sin(i * 0.3) * 1.5 + (8 if i % 50 >= 25 else 0)
            )
            op, cp = Decimal(str(previous)), Decimal(str(close))
            start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes * i)
            bars.append(
                NormalizedCandle(
                    symbol="X",
                    venue="SYNTHETIC_SOFTWARE_AUDIT",
                    timeframe=tf,
                    open_time=start,
                    close_time=start + timedelta(minutes=minutes),
                    open=op,
                    close=cp,
                    high=max(op, cp) + Decimal(".2"),
                    low=min(op, cp) - Decimal(".2"),
                    volume=Decimal(100 + i % 7 * 20),
                    closed=True,
                )
            )
            previous = close
        for setup in STRATEGY_SETUPS:
            rows.append(run(setup, bars, tf, scenario))


async def market():
    try:
        bars = await CoinbaseExchangeHistoryClient().fetch_candles(
            symbol="BTC-USD", timeframe="1h", limit=300
        )
        return {"state": "FETCHED", "bars": len(bars)}
    except (PublicHistoryError, TimeoutError, OSError, ValueError) as exc:
        return {"state": "BLOCKED", "reason": str(exc)}


report = {
    "source": "DETERMINISTIC_SYNTHETIC_SOFTWARE_SCENARIOS_NOT_MARKET_PERFORMANCE",
    "runs": len(rows),
    "errors": 0,
    "fees_bps": 2,
    "slippage_bps": 2,
    "default_risk_limits": True,
    "performance_verified": False,
    "real_market_history": asyncio.run(market()),
    "results": rows,
}
Path("artifacts/governance/full_feature_backtest_matrix.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
print(json.dumps({k: v for k, v in report.items() if k != "results"}))
print("runs_with_fills", sum(r["fills"] > 0 for r in rows))
