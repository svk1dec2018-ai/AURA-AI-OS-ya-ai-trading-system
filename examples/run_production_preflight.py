from __future__ import annotations

import argparse
import json
from pathlib import Path

from aura.ops.preflight import DeploymentMode, ProductionPreflight
from aura.research.lifecycle import StrategyStage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AURA fail-closed production configuration preflight."
    )
    parser.add_argument(
        "--mode",
        choices=[item.value.lower() for item in DeploymentMode],
        default="paper",
    )
    parser.add_argument(
        "--connector",
        action="append",
        default=[],
        help="Connector profile: public, mt5_demo, dhan, shoonya, flattrade, oanda",
    )
    parser.add_argument("--runtime-dir", default="runtime/production")
    parser.add_argument(
        "--strategy-stage",
        choices=[item.value for item in StrategyStage],
        default=None,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stage = StrategyStage(args.strategy_stage) if args.strategy_stage else None
    report = ProductionPreflight(
        mode=DeploymentMode(args.mode.upper()),
        runtime_dir=Path(args.runtime_dir),
        connectors=tuple(args.connector),
        strategy_stage=stage,
    ).run()
    payload = {
        "ready": report.ready,
        "mode": report.mode.value,
        "checks": [
            {
                "check_id": item.check_id,
                "passed": item.passed,
                "blocking": item.blocking,
                "detail": item.detail,
            }
            for item in report.checks
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
