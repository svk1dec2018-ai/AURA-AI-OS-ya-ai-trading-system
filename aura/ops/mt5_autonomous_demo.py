from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path

from aura.execution.mt5_protected_demo import ProtectedMT5DemoConfig
from aura.runtime.mt5_autonomous_demo import build_mt5_autonomous_demo_daemon
from aura.runtime.mt5_paper_daemon import MT5AllMarketPaperConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA's all-market self-evolving scanner/agents/CEO/RiskEngine on "
            "live MT5 data and send only approved orders to a verified MT5 DEMO account."
        )
    )
    parser.add_argument("--max-symbols", type=int, default=10)
    parser.add_argument("--max-batches", type=int, default=100)
    parser.add_argument("--state-dir", default="runtime/mt5_autonomous_demo")
    parser.add_argument("--max-order-notional-pct", type=Decimal, default=Decimal("0.50"))
    parser.add_argument("--max-gross-exposure-pct", type=Decimal, default=Decimal(10))
    parser.add_argument("--max-symbol-exposure-pct", type=Decimal, default=Decimal(2))
    parser.add_argument("--max-daily-loss-pct", type=Decimal, default=Decimal(3))
    parser.add_argument("--max-drawdown-pct", type=Decimal, default=Decimal(8))
    parser.add_argument("--stop-bps", type=Decimal, default=Decimal(35))
    parser.add_argument("--target-bps", type=Decimal, default=Decimal(70))
    parser.add_argument("--research-every-new-samples", type=int, default=100)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    config = MT5AllMarketPaperConfig(
        state_dir=Path(args.state_dir),
        max_symbols=args.max_symbols,
        max_order_notional_pct=args.max_order_notional_pct,
        max_gross_exposure_pct=args.max_gross_exposure_pct,
        max_symbol_exposure_pct=args.max_symbol_exposure_pct,
        max_daily_loss_pct=args.max_daily_loss_pct,
        max_drawdown_pct=args.max_drawdown_pct,
    )
    protection = ProtectedMT5DemoConfig(
        stop_bps=args.stop_bps,
        target_bps=args.target_bps,
    )
    daemon = await build_mt5_autonomous_demo_daemon(
        config,
        protection=protection,
        research_every_new_samples=args.research_every_new_samples,
    )
    counters = await daemon.run(max_batches=args.max_batches)
    return {
        "demo_only": True,
        "real_money_enabled": False,
        "strategy_research_enabled": True,
        "native_sl_tp_required": True,
        "pyramiding_enabled": False,
        "max_symbols": args.max_symbols,
        "max_batches": args.max_batches,
        "batches": counters.batches,
        "contexts": counters.contexts,
        "opportunities": counters.opportunities,
        "submitted_orders": counters.submitted_orders,
        "broker_fills": counters.fills,
        "reconciliations": counters.reconciliations,
        "status_path": str(daemon.base.status_path),
        "brain_status_path": str(daemon.brain_state_dir / "status.json"),
        "financial_wal": str(config.state_dir / "financial.jsonl"),
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
