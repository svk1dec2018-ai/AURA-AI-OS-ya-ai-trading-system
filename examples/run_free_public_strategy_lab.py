from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aura.runtime.free_public_strategy_lab import (
    FreePublicStrategyLabConfig,
    FreePublicStrategyLabRuntime,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA's no-key live shadow strategy lab on public crypto market trades. "
            "No broker account and no API key are required; no orders are sent."
        )
    )
    parser.add_argument("--provider", choices=("coinbase", "bybit"), default="coinbase")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--population", type=int, default=64)
    parser.add_argument("--horizon-bars", type=int, default=5)
    parser.add_argument("--max-ticks", type=int, default=0)
    parser.add_argument("--max-closed-candles", type=int, default=0)
    parser.add_argument("--state-dir", default="runtime/free_public_strategy_lab")
    return parser.parse_args()


async def main() -> None:
    args = _args()
    if args.symbols:
        symbols = tuple(args.symbols)
    elif args.provider == "coinbase":
        symbols = ("BTC-USD", "ETH-USD")
    else:
        symbols = ("BTCUSDT", "ETHUSDT")
    runtime = FreePublicStrategyLabRuntime(
        FreePublicStrategyLabConfig(
            provider=args.provider,
            symbols=symbols,
            population_size=args.population,
            horizon_bars=args.horizon_bars,
            state_dir=Path(args.state_dir),
        )
    )
    print(
        "AURA FREE PUBLIC STRATEGY LAB: no API key -> public live trades -> "
        "1s/5s/15s/30s/1m/3m/5m candles -> strategy population -> forward shadow learning."
    )
    print("BROKER ORDERS: disabled. REAL MONEY: disabled. Research only.")
    counters = await runtime.run(
        max_ticks=args.max_ticks or None,
        max_closed_candles=args.max_closed_candles or None,
    )
    print(
        f"Stopped: ticks={counters.ticks} closed_candles={counters.closed_candles} "
        f"plans={counters.generated_plans}"
    )


if __name__ == "__main__":
    asyncio.run(main())
