from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from aura.runtime.mt5_paper_daemon import (
    MT5AllMarketPaperConfig,
    build_mt5_all_market_paper_daemon,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA's full Exness/MT5 DEMO market universe on live data with "
            "internal paper-only execution."
        )
    )
    parser.add_argument("--cash", default="10000")
    parser.add_argument("--seed-bars", type=int, default=250)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--fee-bps", default="0")
    parser.add_argument("--slippage-bps", default="1")
    parser.add_argument("--max-order-risk-pct", default="1")
    parser.add_argument("--max-gross-pct", default="25")
    parser.add_argument("--max-symbol-pct", default="5")
    parser.add_argument("--state-dir", default="runtime/mt5_all_market_paper")
    return parser.parse_args()


async def main() -> None:
    args = _args()
    daemon = await build_mt5_all_market_paper_daemon(
        MT5AllMarketPaperConfig(
            starting_cash=Decimal(args.cash),
            state_dir=Path(args.state_dir),
            seed_bars=args.seed_bars,
            max_symbols=args.max_symbols or None,
            paper_fee_bps=Decimal(args.fee_bps),
            paper_slippage_bps=Decimal(args.slippage_bps),
            max_order_notional_pct=Decimal(args.max_order_risk_pct),
            max_gross_exposure_pct=Decimal(args.max_gross_pct),
            max_symbol_exposure_pct=Decimal(args.max_symbol_pct),
        )
    )
    print(
        "AURA MT5 PAPER bootstrapped: "
        f"server={daemon.bootstrap.account_server} "
        f"discovered={daemon.bootstrap.discovered_symbols} "
        f"active={daemon.bootstrap.active_symbols} "
        f"seed_series={daemon.bootstrap.seed_series} "
        f"seed_issues={daemon.bootstrap.seed_issues}"
    )
    print(
        "Mode: LIVE MT5 DEMO DATA -> AURA 10-agent scan -> RiskEngine -> INTERNAL PAPER. "
        "Real-money execution is disabled."
    )
    counters = await daemon.run(max_batches=args.max_batches or None)
    print(
        "Stopped: "
        f"batches={counters.batches} contexts={counters.contexts} "
        f"opportunities={counters.opportunities} orders={counters.submitted_orders} "
        f"fills={counters.fills} reconciliations={counters.reconciliations}"
    )


if __name__ == "__main__":
    asyncio.run(main())
