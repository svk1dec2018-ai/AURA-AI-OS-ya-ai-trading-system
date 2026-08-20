from __future__ import annotations

import argparse
import asyncio
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aura.interface.operator_read_model import OperatorReadModel, ReadDomain
from aura.interface.runtime_bridge import OperatorRuntimeBridge, RuntimeBridgeFreshness
from aura.interface.web_command_center import CommandCenterConfig
from aura.interface.web_command_center_v2 import CommandCenterV2Service
from aura.runtime.free_public_ai_council import FreePublicAICouncilConfig
from aura.runtime.observable_public_council import ObservableFreePublicAICouncilRuntime


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA's public/no-key market intelligence council and Command Center v2 "
            "in one process. Broker orders and real money remain disabled."
        )
    )
    parser.add_argument("--provider", choices=("coinbase", "bybit"), default="coinbase")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--timeframe", default="5s")
    parser.add_argument("--htf-timeframe", default=None)
    parser.add_argument("--min-history-bars", type=int, default=30)
    parser.add_argument("--history-seed-bars", type=int, default=240)
    parser.add_argument("--analyze-every-bars", type=int, default=5)
    parser.add_argument("--max-ticks", type=int, default=0)
    parser.add_argument("--max-ai-decisions", type=int, default=0)
    parser.add_argument("--disable-history", action="store_true")
    parser.add_argument("--disable-news", action="store_true")
    parser.add_argument("--state-dir", default="runtime/public_command_center")
    parser.add_argument("--host", default=os.getenv("AURA_COMMAND_CENTER_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("AURA_COMMAND_CENTER_PORT", "8765")),
    )
    return parser.parse_args()


async def main() -> None:
    args = _args()
    symbols = _symbols(args.provider, args.symbols)
    htf = args.htf_timeframe or _default_htf(args.timeframe)
    timeframes = tuple(
        dict.fromkeys(
            (
                args.timeframe,
                htf,
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
    read_model = OperatorReadModel()
    bridge = OperatorRuntimeBridge(
        read_model,
        freshness=RuntimeBridgeFreshness(
            opportunities=timedelta(minutes=2),
            agents=timedelta(minutes=2),
            data=timedelta(minutes=2),
            system=timedelta(minutes=2),
        ),
    )

    def observe(scan) -> None:
        bridge.publish_scan(
            scan,
            source=f"{args.provider}-public-council",
            runtime_metadata={
                "provider": args.provider,
                "symbols": list(symbols),
                "decision_timeframe": args.timeframe,
                "broker_orders_enabled": False,
                "real_money_enabled": False,
            },
        )

    runtime = ObservableFreePublicAICouncilRuntime(
        FreePublicAICouncilConfig(
            provider=args.provider,
            symbols=symbols,
            decision_timeframe=args.timeframe,
            timeframes=timeframes,
            htf_timeframe=htf,
            min_history_bars=args.min_history_bars,
            history_seed_bars=args.history_seed_bars,
            analyze_every_bars=args.analyze_every_bars,
            enable_public_history=not args.disable_history,
            enable_live_intelligence=not args.disable_news,
            state_dir=root / "council",
        ),
        scan_observer=observe,
    )

    now = datetime.now(UTC)
    read_model.publish(
        ReadDomain.SYSTEM,
        {
            "mode": "PUBLIC_LIVE_INTELLIGENCE",
            "provider": args.provider,
            "symbols": list(symbols),
            "decision_timeframe": args.timeframe,
            "local_ai_agent_count": runtime.ai_agent_count,
            "broker_order_authority": False,
            "live_money_enabled": False,
        },
        source="public-command-center:startup",
        observed_at=now,
        received_at=now,
        max_age=timedelta(minutes=5),
    )
    read_model.publish(
        ReadDomain.BROKERS,
        {
            "attached": False,
            "execution_mode": "OBSERVATION_ONLY",
            "broker_order_authority": False,
            "live_money_enabled": False,
        },
        source="public-command-center:no-broker",
        observed_at=now,
        received_at=now,
        max_age=timedelta(minutes=5),
    )

    command_config = CommandCenterConfig(
        host=args.host,
        port=args.port,
        queue_path=root / "research_requests.jsonl",
        api_token=os.getenv("AURA_COMMAND_CENTER_TOKEN") or None,
    )
    service = CommandCenterV2Service(command_config, read_model=read_model)
    server = service.make_server()
    thread = threading.Thread(
        target=server.serve_forever,
        name="aura-command-center-v2",
        daemon=True,
    )
    thread.start()

    print(f"AURA Command Center v2: http://{command_config.host}:{command_config.port}")
    print(f"Public provider={args.provider} symbols={','.join(symbols)}")
    print("SAFETY: observation/research only; broker orders and real money are disabled")
    print("LOCAL AI: AURA_OLLAMA_MODELS must reference operator-installed Ollama models")
    try:
        await runtime.run(
            max_ticks=args.max_ticks or None,
            max_ai_decisions=args.max_ai_decisions or None,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
        print("AURA public Command Center stopped by operator.")
