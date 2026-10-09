"""Rebuild deterministic software evidence; never approve broker/live phases."""
from __future__ import annotations

import subprocess
import sys

GATES = (
    ("repository_audit",),
    ("core_contracts", "--write"),
    ("state_engine_gate", "--write"),
    ("risk_engine_gate", "--write"),
    ("broker_conformance_gate", "--write"),
    ("market_data_gate", "--write"),
    ("backtest_gate", "--write"),
    ("strategy_research_gate", "--write"),
    ("knowledge_rag_gate", "--write"),
    ("multi_agent_gate", "--write"),
    ("ceo_decision_gate", "--write"),
    ("broker_evidence_readiness", "--write"),
    ("paper_trading_gate", "--write"),
    ("operator_interface_gate", "--write"),
    ("end_to_end_gate", "--write"),
)


def main() -> int:
    for module, *arguments in GATES:
        command = [sys.executable, "-m", f"aura.ops.{module}", *arguments]
        result = subprocess.run(command, check=False)
        if result.returncode:
            print(f"Software evidence refresh failed: {module}", file=sys.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
