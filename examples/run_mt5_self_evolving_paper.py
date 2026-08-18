from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from aura.evolution.brain_online import BrainPaperPromotionPolicy
from aura.evolution.shadow_outcomes import ShadowOutcomePolicy

from aura.evolution.brain_optimizer import BrainOptimizerConfig
from aura.runtime.mt5_learning_daemon import build_mt5_self_evolving_paper_daemon
from aura.runtime.mt5_paper_daemon import MT5AllMarketPaperConfig


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA on all Exness MT5 DEMO symbols with live data, internal paper "
            "execution, automatic mistake labeling and forward-only brain evolution."
        )
    )
    parser.add_argument("--cash", default="10000")
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--seed-bars", type=int, default=250)
    parser.add_argument("--shadow-horizon-bars", type=int, default=5)
    parser.add_argument("--optimizer-min-samples", type=int, default=250)
    parser.add_argument("--research-every-samples", type=int, default=100)
    parser.add_argument("--forward-paper-trades", type=int, default=50)
    parser.add_argument("--state-dir", default="runtime/mt5_self_evolving_paper")
    return parser.parse_args()


async def main() -> None:
    args = _args()
    daemon = await build_mt5_self_evolving_paper_daemon(
        MT5AllMarketPaperConfig(
            starting_cash=Decimal(args.cash),
            state_dir=Path(args.state_dir),
            max_symbols=args.max_symbols or None,
            seed_bars=args.seed_bars,
        ),
        optimizer_config=BrainOptimizerConfig(
            minimum_samples=args.optimizer_min_samples,
        ),
        shadow_policy=ShadowOutcomePolicy(
            horizon_bars=args.shadow_horizon_bars,
        ),
        promotion_policy=BrainPaperPromotionPolicy(
            min_forward_trades=args.forward_paper_trades,
        ),
        research_every_new_samples=args.research_every_samples,
    )
    print(
        "AURA SELF-EVOLVING PAPER: live Exness/MT5 DEMO data -> full universe -> "
        "10 agents -> adversarial review -> brain policy -> RiskEngine -> internal paper."
    )
    print(
        "Brain evolution: future outcome labels -> train/validation/sealed holdout -> "
        "research challenger -> forward-only paper challenger -> paper champion."
    )
    print("REAL MONEY: disabled. Live approval: disabled.")
    counters = await daemon.run(max_batches=args.max_batches or None)
    print(
        f"Stopped: batches={counters.batches} contexts={counters.contexts} "
        f"opportunities={counters.opportunities} orders={counters.submitted_orders} "
        f"fills={counters.fills} reconciliations={counters.reconciliations}"
    )


if __name__ == "__main__":
    asyncio.run(main())
