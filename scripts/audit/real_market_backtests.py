import asyncio
import json
from decimal import Decimal
from pathlib import Path

from aura.backtest.engine import BacktestEngine
from aura.core.pipeline import DecisionPipeline
from aura.data.public_history import CoinbaseExchangeHistoryClient
from aura.research.blueprint_compiler import compile_blueprint
from aura.research.strategy_catalog import STRATEGY_SETUPS
from aura.risk.engine import RiskEngine, RiskLimits


async def main():
    bars = await CoinbaseExchangeHistoryClient().fetch_candles(
        symbol="BTC-USD", timeframe="1h", limit=300
    )
    results = []
    for setup in STRATEGY_SETUPS:
        strategy = compile_blueprint(setup.blueprint())
        r = BacktestEngine(
            DecisionPipeline(strategy, RiskEngine(RiskLimits())),
            Decimal(100000),
            Decimal(".01"),
            fee_bps=Decimal(10),
            slippage_bps=Decimal(5),
        ).run(list(bars), signal_start_index=strategy.warmup_bars)
        results.append(
            {
                "strategy": setup.key,
                "orders": r.orders,
                "fills": r.fills,
                "rejected": r.rejected_signals,
                "ending_equity": str(r.ending_equity),
                "realized_pnl": str(r.realized_pnl),
                "unrealized_pnl": str(r.unrealized_pnl),
                "max_drawdown_pct": str(r.max_drawdown_pct),
            }
        )
    data = {
        "source": "Coinbase Exchange public REST actual closed BTC-USD candles",
        "timeframe": "1h",
        "bars": len(bars),
        "start": bars[0].open_time.isoformat(),
        "end": bars[-1].close_time.isoformat(),
        "starting_cash": "100000",
        "quantity": ".01",
        "fee_bps": 10,
        "slippage_bps": 5,
        "default_risk_limits": True,
        "performance_certified": False,
        "limitations": [
            "Single short sample; no walk-forward/out-of-sample evaluation",
            "Public crypto history does not verify MT5 broker fills or all-market performance",
            "Fees/slippage are assumptions, not measured broker costs",
        ],
        "results": results,
        "candles": [b.model_dump(mode="json") for b in bars],
    }
    Path("artifacts/governance/real_market_strategy_backtests.json").write_text(
        json.dumps(data, indent=2) + "\n"
    )
    print(json.dumps({k: v for k, v in data.items() if k != "candles"}, indent=2))


asyncio.run(main())
