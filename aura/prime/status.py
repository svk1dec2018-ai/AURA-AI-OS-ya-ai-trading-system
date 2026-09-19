from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from aura.ops.phase_gates import phase_is_pass, validate_phase_gate_ledger

from .providers import provider_matrix


def prime_status(repository_root: Path | None = None) -> dict[str, Any]:
    root = (repository_root or Path.cwd()).resolve()
    ledger = root / "artifacts" / "governance" / "phase_gate_status.json"
    errors = validate_phase_gate_ledger(ledger, root)
    software_phases = tuple(range(11)) + (12, 13, 14)
    phase_state = {
        str(phase): phase_is_pass(ledger, root, phase) if not errors else False
        for phase in range(16)
    }
    software_ready = not errors and all(
        phase_state[str(phase)] for phase in software_phases
    )
    live_ready = not errors and phase_state["11"] and phase_state["15"]

    optional = {
        name: importlib.util.find_spec(module) is not None
        for name, module in (
            ("duckdb", "duckdb"),
            ("polars", "polars"),
            ("sklearn", "sklearn"),
            ("xgboost", "xgboost"),
            ("lightgbm", "lightgbm"),
            ("hmmlearn", "hmmlearn"),
            ("onnxruntime", "onnxruntime"),
            ("prometheus_client", "prometheus_client"),
        )
    }

    return {
        "ok": software_ready,
        "architecture": "AURA_PRIME_V1",
        "software_production_ready": software_ready,
        "live_money_eligible": live_ready,
        "phase_gate_errors": list(errors),
        "phase_state": phase_state,
        "optional_capabilities": optional,
        "providers": list(provider_matrix()),
        "hard_boundaries": {
            "ai_execution_authority": False,
            "model_execution_authority": False,
            "fund_movement": False,
            "risk_bypass": False,
            "live_money_default": False,
        },
    }


def main() -> int:
    import json

    payload = prime_status()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["software_production_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
