from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from aura.ops.release_gate import ProductionEvidence, ProductionReleaseGate
from aura.research.lifecycle import StrategyStage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate an AURA live-canary release evidence document."
    )
    parser.add_argument("evidence", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/production/release_manifest.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw = json.loads(args.evidence.read_text(encoding="utf-8"))
    evidence = ProductionEvidence(
        strategy_id=str(raw["strategy_id"]),
        strategy_version=str(raw["strategy_version"]),
        strategy_stage=StrategyStage(str(raw["strategy_stage"])),
        forward_live_trades=int(raw["forward_live_trades"]),
        forward_live_days=int(raw["forward_live_days"]),
        max_drawdown_pct=Decimal(str(raw["max_drawdown_pct"])),
        profit_factor=Decimal(str(raw["profit_factor"])),
        expectancy=Decimal(str(raw["expectancy"])),
        critical_incidents=int(raw.get("critical_incidents", 0)),
        reconciliation_failures=int(raw.get("reconciliation_failures", 0)),
        unresolved_data_integrity_events=int(
            raw.get("unresolved_data_integrity_events", 0)
        ),
        source=str(raw.get("source", "LIVE_BROKER")),
    )
    manifest = ProductionReleaseGate().evaluate(evidence)
    manifest.write_atomic(args.output)
    print(json.dumps(manifest.to_json_dict(), indent=2, sort_keys=True))
    return 0 if manifest.eligible else 3


if __name__ == "__main__":
    raise SystemExit(main())
