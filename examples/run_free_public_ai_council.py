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
    parser.add_argument("--htf-timeframe", default=None)
    parser.add_argument("--min-history-bars", type=int, default=30)
    parser.add_argument("--history-seed-bars", type=int, default=240)
    parser.add_argument("--analyze-every-bars", type=int, default=5)
    parser.add_argument("--max-inflight-ai-decisions", type=int, default=1)
    parser.add_argument("--disable-history", action="store_true")
    parser.add_argument("--disable-news", action="store_true")
    parser.add_argument("--gdelt-query", action="append", default=None)
    parser.add_argument("--max-ticks", type=int, default=0)
    parser.add_argument("--max-ai-decisions", type=int, default=0)
    parser.add_argument("--state-dir", default="runtime/free_public_ai_council")
    return parser.parse_args()


async def main() -> None:
    args = _args()
    if args.symbols:
        symbols = tuple(args.symbols)
    elif args.provider == "coinbase":
        symbols = ("BTC-USD", "ETH-USD")
    else:
        symbols = ("BTCUSDT", "ETHUSDT")
    htf_timeframe = args.htf_timeframe or _default_htf(args.timeframe)
    timeframes = tuple(
        dict.fromkeys(
            (
                args.timeframe,
                htf_timeframe,
                "1s",
                "5s",
                "15s",
                "30s",
                "1m",
                "5m",
                "15m",
                "1h",
                "4h",
            )
        )
    )
    gdelt_queries = (
        tuple(args.gdelt_query)
        if args.gdelt_query
        else FreePublicAICouncilConfig().gdelt_queries
    )
    runtime = FreePublicAICouncilRuntime(
        FreePublicAICouncilConfig(
            provider=args.provider,
            symbols=symbols,
            decision_timeframe=args.timeframe,
            timeframes=timeframes,
            htf_timeframe=htf_timeframe,
            min_history_bars=args.min_history_bars,
            history_seed_bars=args.history_seed_bars,
            analyze_every_bars=args.analyze_every_bars,
            max_inflight_ai_decisions=args.max_inflight_ai_decisions,
            enable_public_history=not args.disable_history,
            enable_live_intelligence=not args.disable_news,
            gdelt_queries=gdelt_queries,
            state_dir=Path(args.state_dir),
        )
    )
    print(
        "AURA FREE PUBLIC MULTI-AI: no broker key -> live public trades -> "
        "historical/news/forecast context -> closed candles -> "
        "deterministic specialists + local AI council -> "
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


def _default_htf(decision_timeframe: str) -> str:
    if decision_timeframe in {"1s", "5s", "15s", "30s", "1m", "3m"}:
        return "5m" if decision_timeframe != "5m" else "15m"
    if decision_timeframe in {"5m", "15m"}:
        return "15m" if decision_timeframe == "5m" else "1h"
    return "4h"


if __name__ == "__main__":
    asyncio.run(main())
