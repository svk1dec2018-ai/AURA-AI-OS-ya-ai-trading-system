from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aura.interface.voice_alerts import LocalVoiceAnnouncer, VoiceStatusMonitor
from aura.runtime.free_public_ai_council import (
    FreePublicAICouncilConfig,
    FreePublicAICouncilRuntime,
)
from aura.runtime.free_public_strategy_lab import (
    FreePublicStrategyLabConfig,
    FreePublicStrategyLabRuntime,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA's no-key public Multi-AI council and forward-only shadow "
            "strategy lab together. Broker orders and real money remain disabled."
        )
    )
    parser.add_argument("--provider", choices=("coinbase", "bybit"), default="coinbase")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--timeframe", default="5s")
    parser.add_argument("--htf-timeframe", default=None)
    parser.add_argument("--population", type=int, default=64)
    parser.add_argument("--min-history-bars", type=int, default=30)
    parser.add_argument("--history-seed-bars", type=int, default=240)
    parser.add_argument("--analyze-every-bars", type=int, default=5)
    parser.add_argument("--max-inflight-ai-decisions", type=int, default=1)
    parser.add_argument("--max-ticks", type=int, default=0)
    parser.add_argument("--max-ai-decisions", type=int, default=0)
    parser.add_argument("--disable-history", action="store_true")
    parser.add_argument("--disable-news", action="store_true")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--state-dir", default="runtime/free_public_autonomy")
    return parser.parse_args()


async def main() -> None:
    args = _args()
    symbols = _symbols(args.provider, args.symbols)
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
    root = Path(args.state_dir)
    council = FreePublicAICouncilRuntime(
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
            state_dir=root / "ai_council",
        )
    )
    strategy_lab = FreePublicStrategyLabRuntime(
        FreePublicStrategyLabConfig(
            provider=args.provider,
            symbols=symbols,
            population_size=args.population,
            state_dir=root / "strategy_lab",
        )
    )

    print("AURA AUTONOMY: historical seed + live intelligence + local Multi-AI council")
    print("AURA TRAINING: forward-only public shadow strategy evolution is running in parallel")
    print("SAFETY: broker orders disabled; real money disabled; research triggers cannot self-deploy")
    print(f"Provider={args.provider} Symbols={','.join(symbols)} Decision={args.timeframe}")

    voice_stop = asyncio.Event()
    announcer = LocalVoiceAnnouncer(enabled=args.voice)
    voice_task = None
    if args.voice and announcer.available:
        voice_task = asyncio.create_task(
            VoiceStatusMonitor(
                root / "ai_council" / "status.json",
                announcer,
            ).run(voice_stop),
            name="aura-voice-alerts",
        )
    elif args.voice:
        print("VOICE: no supported local OS speech command found; continuing silently")

    try:
        async with asyncio.TaskGroup() as group:
            council_task = group.create_task(
                council.run(
                    max_ticks=args.max_ticks or None,
                    max_ai_decisions=args.max_ai_decisions or None,
                ),
                name="aura-ai-council",
            )
            lab_task = group.create_task(
                strategy_lab.run(max_ticks=args.max_ticks or None),
                name="aura-strategy-lab",
            )
    finally:
        voice_stop.set()
        if voice_task is not None:
            await voice_task

    council_counts = council_task.result()
    lab_counts = lab_task.result()
    print(
        "Stopped cleanly: "
        f"AI decisions={council_counts.ai_decisions_completed}, "
        f"opportunity outcomes={council_counts.opportunity_outcomes_resolved}, "
        f"shadow plans={lab_counts.generated_plans}"
    )


def _symbols(provider: str, requested: list[str] | None) -> tuple[str, ...]:
    if requested:
        return tuple(requested)
    if provider == "coinbase":
        return ("BTC-USD", "ETH-USD")
    return ("BTCUSDT", "ETHUSDT")


def _default_htf(decision_timeframe: str) -> str:
    if decision_timeframe in {"1s", "5s", "15s", "30s", "1m", "3m"}:
        return "5m"
    if decision_timeframe == "5m":
        return "15m"
    return "1h" if decision_timeframe == "15m" else "4h"


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("AURA local autonomy stopped by operator; saved shadow state remains on disk.")
