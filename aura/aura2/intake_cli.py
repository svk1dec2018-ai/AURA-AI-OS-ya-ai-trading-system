from __future__ import annotations

import argparse
import json
from pathlib import Path

from .external_artifact import ExternalResearchIntake


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a normalized open-source research artifact for AURA 2"
    )
    parser.add_argument("artifact", type=Path, help="JSON artifact exported by an AURA 2 sidecar")
    return parser


def main() -> int:
    args = _parser().parse_args()
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("artifact must contain one JSON object")
    artifact, decision = ExternalResearchIntake().ingest(payload)
    print(
        json.dumps(
            {
                "candidate_id": artifact.candidate_id,
                "source": artifact.source,
                "artifact_hash": artifact.artifact_hash,
                "accepted_for_aura_validation": decision.accepted_for_aura_validation,
                "reasons": list(decision.reasons),
                "stage": decision.stage,
                "execution_authority": decision.granted_execution_authority,
                "risk_authority": decision.granted_risk_authority,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if decision.accepted_for_aura_validation else 2


if __name__ == "__main__":
    raise SystemExit(main())
