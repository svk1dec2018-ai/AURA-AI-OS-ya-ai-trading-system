from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from aura.execution.mt5_protected_demo import ProtectedMT5DemoConfig
from aura.runtime.mt5_autonomous_demo import build_mt5_autonomous_demo_daemon
from aura.runtime.mt5_paper_daemon import MT5AllMarketPaperConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA all-market self-evolving intelligence with actual MT5 DEMO "
            "orders, native SL/TP and live-money hard-blocked."
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
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
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
    print(
        "AURA MT5 self-evolving autonomous DEMO started: "
        f"server={daemon.base.bootstrap.account_server} "
        f"symbols={daemon.base.bootstrap.active_symbols} "
        "real_money_enabled=false"
    )
    await daemon.run(max_batches=args.max_batches)


if __name__ == "__main__":
    asyncio.run(main())
