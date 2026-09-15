from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from aura.runtime.mt5_autonomous_demo import (
    MT5AutonomousDemoConfig,
    build_mt5_autonomous_demo_daemon,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AURA on broker-origin MT5 data with actual DEMO orders only."
    )
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--max-order-notional-pct", type=Decimal, default=Decimal("0.50"))
    parser.add_argument("--max-gross-exposure-pct", type=Decimal, default=Decimal("10"))
    parser.add_argument("--max-symbol-exposure-pct", type=Decimal, default=Decimal("2"))
    parser.add_argument("--max-daily-loss-pct", type=Decimal, default=Decimal("3"))
    parser.add_argument("--max-drawdown-pct", type=Decimal, default=Decimal("8"))
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    config = MT5AutonomousDemoConfig(
        max_symbols=args.max_symbols,
        max_order_notional_pct=args.max_order_notional_pct,
        max_gross_exposure_pct=args.max_gross_exposure_pct,
        max_symbol_exposure_pct=args.max_symbol_exposure_pct,
        max_daily_loss_pct=args.max_daily_loss_pct,
        max_drawdown_pct=args.max_drawdown_pct,
    )
    daemon = await build_mt5_autonomous_demo_daemon(config)
    print(
        "AURA MT5 autonomous DEMO started: "
        f"server={daemon.account_server} symbols={daemon.active_symbols} "
        "real_money_enabled=false"
    )
    await daemon.run(max_batches=args.max_batches)


if __name__ == "__main__":
    asyncio.run(main())
