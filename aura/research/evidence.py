from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from aura.research.lifecycle import EvidenceKind, ValidationEvidence
from aura.research.robustness import (
    MonteCarloSummary,
    RobustnessDecision,
    RobustnessThresholds,
    WalkForwardSummary,
    evaluate_robustness,
)


@dataclass(slots=True, frozen=True)
class RobustnessEvidenceBundle:
    walk_forward: ValidationEvidence
    monte_carlo: ValidationEvidence
    decision: RobustnessDecision


def build_robustness_evidence(
    walk_forward: WalkForwardSummary,
    monte_carlo: MonteCarloSummary,
    *,
    thresholds: RobustnessThresholds | None = None,
    created_at: datetime | None = None,
) -> RobustnessEvidenceBundle:
    """Derive immutable governance evidence from measured robustness outputs.

    `passed` is computed from metrics and thresholds; callers cannot supply an
    arbitrary success flag. This prevents an AI research agent from promoting a
    strategy by merely claiming that walk-forward or Monte Carlo checks passed.
    """
    limits = thresholds or RobustnessThresholds()
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")

    decision = evaluate_robustness(
        walk_forward,
        monte_carlo,
        thresholds=limits,
    )
    walk_forward_passed = (
        walk_forward.positive_fold_ratio >= limits.min_positive_fold_ratio
        and walk_forward.compounded_oos_return > limits.min_compounded_oos_return
    )
    monte_carlo_passed = (
        monte_carlo.probability_of_loss <= limits.max_probability_of_loss
        and monte_carlo.p95_max_drawdown <= limits.max_p95_drawdown
    )

    wf_payload = {
        "kind": EvidenceKind.WALK_FORWARD.value,
        "summary": walk_forward.model_dump(mode="json"),
        "thresholds": asdict(limits),
    }
    mc_payload = {
        "kind": EvidenceKind.MONTE_CARLO.value,
        "summary": monte_carlo.model_dump(mode="json"),
        "thresholds": asdict(limits),
    }
    return RobustnessEvidenceBundle(
        walk_forward=ValidationEvidence(
            kind=EvidenceKind.WALK_FORWARD,
            passed=walk_forward_passed,
            artifact_hash=_artifact_hash(wf_payload),
            created_at=timestamp,
            notes=(
                f"positive_fold_ratio={walk_forward.positive_fold_ratio:.4f}; "
                f"compounded_oos_return={walk_forward.compounded_oos_return:.6f}"
            ),
        ),
        monte_carlo=ValidationEvidence(
            kind=EvidenceKind.MONTE_CARLO,
            passed=monte_carlo_passed,
            artifact_hash=_artifact_hash(mc_payload),
            created_at=timestamp,
            notes=(
                f"probability_of_loss={monte_carlo.probability_of_loss:.4f}; "
                f"p95_max_drawdown={monte_carlo.p95_max_drawdown:.6f}"
            ),
        ),
        decision=decision,
    )


def _artifact_hash(payload: dict) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
