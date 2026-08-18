from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aura.runtime.free_public_ai_council import (
    FreePublicAICouncilConfig,
    FreePublicAICouncilRuntime,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA deterministic specialists + local multi-AI council on no-key "
            "public crypto live trades. No broker orders are sent."
        )
    )
    parser.add_argument("--provider", choices=("coinbase", "bybit"), default="coinbase")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--timeframe", default="1s")
    parser.add_argument("--min-history-bars", type=int, default=30)
    parser.add_argument("--analyze-every-bars", type=int, default=5)
    parser.add_argument("--max-inflight-ai-decisions", type=int, default=1)
    parser.add_argument("--max-ticks", type=int, default=0)
    parser.add_argument("--max-ai-decisions", type=int, default=0)
    parser.add_argument("--state-dir", default="runtime/free_public_ai_council")
    return parser.parse_args()


async def main() -> None:
    args = _args()
    if args.symbols:
        symbols = tuple(args.symbols)
    elif args.provider == "coinbase":
        symbols = ("BTC-USD",)
    else:
        symbols = ("BTCUSDT",)
    timeframes = tuple(
        dict.fromkeys((args.timeframe, "1s", "5s", "15s", "30s", "1m"))
    )
    runtime = FreePublicAICouncilRuntime(
        FreePublicAICouncilConfig(
            provider=args.provider,
            symbols=symbols,
            decision_timeframe=args.timeframe,
            timeframes=timeframes,
            min_history_bars=args.min_history_bars,
            analyze_every_bars=args.analyze_every_bars,
            max_inflight_ai_decisions=args.max_inflight_ai_decisions,
            state_dir=Path(args.state_dir),
        )
    )
    print(
        "AURA FREE PUBLIC MULTI-AI: no broker key -> live public trades -> "
        "closed candles -> deterministic specialists + local AI council -> "
        "adversarial review -> CEO memo."
    )
    print("BROKER ORDERS: disabled. REAL MONEY: disabled.")
    counters = await runtime.run(
        max_ticks=args.max_ticks or None,
        max_ai_decisions=args.max_ai_decisions or None,
    )
    print(
        f"Stopped: ticks={counters.ticks} decisions={counters.ai_decisions_completed} "
        f"actionable={counters.actionable_decisions}"
    )


if __name__ == "__main__":
    asyncio.run(main())
