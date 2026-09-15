from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path

from aura.runtime.mt5_learning_daemon import build_mt5_self_evolving_paper_daemon
from aura.runtime.mt5_paper_daemon import (
    MT5AllMarketPaperConfig,
    build_mt5_all_market_paper_daemon,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA against the full tradable MT5 DEMO universe using live broker data. "
            "Execution remains internal paper-only in this runner."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("paper", "learn"),
        default="learn",
        help="paper = fixed policy; learn = bounded self-evolving paper policy",
    )
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--starting-cash", default="10000")
    parser.add_argument(
        "--state-dir",
        default="runtime/mt5_all_market_paper",
        help="durable runtime/audit state directory",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    config = MT5AllMarketPaperConfig(
        starting_cash=Decimal(args.starting_cash),
        state_dir=Path(args.state_dir),
        max_symbols=args.max_symbols,
    )
    if args.mode == "learn":
        daemon = await build_mt5_self_evolving_paper_daemon(config)
    else:
        daemon = await build_mt5_all_market_paper_daemon(config)
    counters = await daemon.run(max_batches=args.max_batches)
    base = daemon.base if hasattr(daemon, "base") else daemon
    return {
        "mode": args.mode,
        "real_money_enabled": False,
        "execution": "internal_paper_only",
        "discovered_symbols": base.bootstrap.discovered_symbols,
        "active_symbols": base.bootstrap.active_symbols,
        "seed_series": base.bootstrap.seed_series,
        "seed_issues": base.bootstrap.seed_issues,
        "batches": counters.batches,
        "contexts": counters.contexts,
        "opportunities": counters.opportunities,
        "submitted_orders": counters.submitted_orders,
        "fills": counters.fills,
        "reconciliations": counters.reconciliations,
        "state_dir": str(base.config.state_dir),
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
