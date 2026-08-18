from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from pathlib import Path

from aura.evolution.brain_online import BrainPaperPromotionPolicy
from aura.evolution.brain_optimizer import BrainOptimizerConfig
from aura.evolution.opportunity_audit import OpportunityAuditPolicy
from aura.evolution.shadow_outcomes import ShadowOutcomePolicy
from aura.runtime.dhan_learning_daemon import (
    DhanSelfEvolvingPaperConfig,
    build_dhan_self_evolving_paper_daemon,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AURA on live Dhan Indian market data with broad radar, Full-feed "
            "deep analysis, internal paper trading and live-only brain evolution."
        )
    )
    parser.add_argument("--cash", default="300000")
    parser.add_argument("--broad-cap", type=int, default=5000)
    parser.add_argument("--deep-top", type=int, default=40)
    parser.add_argument("--max-deep-batches", type=int, default=0)
    parser.add_argument("--history-days", type=int, default=35)
    parser.add_argument("--optimizer-min-samples", type=int, default=250)
    parser.add_argument("--research-every-samples", type=int, default=100)
    parser.add_argument("--forward-paper-trades", type=int, default=50)
    parser.add_argument("--shadow-horizon-bars", type=int, default=5)
    parser.add_argument("--audit-horizon-bars", type=int, default=5)
    parser.add_argument("--audit-min-move-atr", type=float, default=1.0)
    parser.add_argument("--state-dir", default="runtime/dhan_self_evolving_paper")
    return parser.parse_args()


async def main() -> None:
    args = _args()
    daemon = await build_dhan_self_evolving_paper_daemon(
        DhanSelfEvolvingPaperConfig(
            starting_cash=Decimal(args.cash),
            state_dir=Path(args.state_dir),
            broad_stream_cap=args.broad_cap,
            deep_top_k=args.deep_top,
            history_days=args.history_days,
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
        opportunity_audit_policy=OpportunityAuditPolicy(
            horizon_bars=args.audit_horizon_bars,
            min_move_atr_multiple=args.audit_min_move_atr,
        ),
        research_every_new_samples=args.research_every_samples,
    )
    print(
        "AURA DHAN SELF-EVOLVING PAPER: live broad universe -> radar -> Full depth/OI/"
        "volume -> 10 agents -> adversarial review -> RiskEngine -> internal paper."
    )
    print(
        "Learning: live future outcomes + missed-opportunity audit -> sealed research -> "
        "forward-only live paper challenger -> paper champion."
    )
    print("REAL MONEY: disabled. Dhan order API: not used by this runner.")
    counters = await daemon.run(max_deep_batches=args.max_deep_batches or None)
    print(
        f"Stopped: radar_batches={counters.radar_batches} "
        f"deep_batches={counters.deep_batches} contexts={counters.contexts} "
        f"opportunities={counters.opportunities} orders={counters.submitted_orders} "
        f"fills={counters.fills} seeded={counters.history_seeded_symbols}"
    )


if __name__ == "__main__":
    asyncio.run(main())
