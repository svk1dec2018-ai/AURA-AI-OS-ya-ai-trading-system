from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path

from aura.runtime.mt5_demo_execution_daemon import (
    MT5AutonomousDemoConfig,
    build_mt5_autonomous_demo_daemon,
)
from aura.runtime.mt5_paper_daemon import MT5AllMarketPaperConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA scanner/agents/CEO/RiskEngine on live MT5 DEMO data and mirror only "
            "RiskEngine-approved intents into the verified MT5 DEMO broker."
        )
    )
    parser.add_argument("--max-symbols", type=int, default=10)
    parser.add_argument("--max-batches", type=int, default=100)
    parser.add_argument("--max-demo-orders", type=int, default=3)
    parser.add_argument("--starting-cash", default="10000")
    parser.add_argument("--state-dir", default="runtime/mt5_autonomous_demo")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    state_dir = Path(args.state_dir)
    paper_config = MT5AllMarketPaperConfig(
        starting_cash=Decimal(args.starting_cash),
        state_dir=state_dir / "decision_paper",
        max_symbols=args.max_symbols,
    )
    demo_config = MT5AutonomousDemoConfig(
        state_dir=state_dir,
        max_demo_orders=args.max_demo_orders,
    )
    daemon = await build_mt5_autonomous_demo_daemon(
        paper_config=paper_config,
        demo_config=demo_config,
    )
    counters = await daemon.run(max_batches=args.max_batches)
    return {
        "demo_only": True,
        "real_money_enabled": False,
        "max_symbols": args.max_symbols,
        "max_batches": args.max_batches,
        "max_demo_orders": args.max_demo_orders,
        "batches": counters.batches,
        "opportunities": counters.opportunities,
        "risk_approved_intents": counters.risk_approved_intents,
        "broker_submissions": counters.broker_submissions,
        "broker_fills": counters.broker_fills,
        "broker_safety_blocks": counters.broker_safety_blocks,
        "broker_state_checks": counters.broker_state_checks,
        "status_path": str(daemon.status_path),
        "broker_financial_wal": str(state_dir / "broker_financial.jsonl"),
    }


def main() -> int:
    args = _parser().parse_args()
    try:
        payload = asyncio.run(_run(args))
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "demo_only": True,
                    "real_money_enabled": False,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps({"ok": True, **payload}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
