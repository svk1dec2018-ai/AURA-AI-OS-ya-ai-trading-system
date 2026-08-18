from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from aura.research.lifecycle import StrategyStage


@dataclass(slots=True, frozen=True)
class ReleasePolicy:
    min_forward_live_trades: int = 1000
    min_forward_live_days: int = 30
    max_drawdown_pct: Decimal = Decimal("10")
    min_profit_factor: Decimal = Decimal("1.10")
    min_expectancy: Decimal = Decimal("0")
    max_critical_incidents: int = 0
    max_reconciliation_failures: int = 0
    max_unresolved_data_integrity_events: int = 0


@dataclass(slots=True, frozen=True)
class ProductionEvidence:
    strategy_id: str
    strategy_version: str
    strategy_stage: StrategyStage
    forward_live_trades: int
    forward_live_days: int
    max_drawdown_pct: Decimal
    profit_factor: Decimal
    expectancy: Decimal
    critical_incidents: int = 0
    reconciliation_failures: int = 0
    unresolved_data_integrity_events: int = 0
    source: str = "LIVE_BROKER"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.strategy_version.strip():
            raise ValueError("strategy identity is required")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if self.forward_live_trades < 0 or self.forward_live_days < 0:
            raise ValueError("forward evidence counts cannot be negative")
        if self.max_drawdown_pct < 0:
            raise ValueError("max_drawdown_pct cannot be negative")
        if self.critical_incidents < 0 or self.reconciliation_failures < 0:
            raise ValueError("incident counters cannot be negative")
        if self.unresolved_data_integrity_events < 0:
            raise ValueError("data-integrity counter cannot be negative")


@dataclass(slots=True, frozen=True)
class ProductionReleaseManifest:
    eligible: bool
    reasons: tuple[str, ...]
    evidence: ProductionEvidence
    policy: ReleasePolicy
    manifest_hash: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_json_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "evidence": _json_safe(asdict(self.evidence)),
            "policy": _json_safe(asdict(self.policy)),
            "manifest_hash": self.manifest_hash,
            "evaluated_at": self.evaluated_at.isoformat(),
        }

    def write_atomic(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_json_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)


class ProductionReleaseGate:
    """Objective, fail-closed eligibility gate for a live canary candidate.

    The gate does not predict profitability. It requires forward broker-origin
    evidence, human-approved strategy stage and zero unresolved critical controls.
    """

    def __init__(self, policy: ReleasePolicy | None = None) -> None:
        self.policy = policy or ReleasePolicy()

    def evaluate(self, evidence: ProductionEvidence) -> ProductionReleaseManifest:
        reasons: list[str] = []
        policy = self.policy

        if evidence.strategy_stage != StrategyStage.APPROVED:
            reasons.append("strategy is not human APPROVED")
        if evidence.source != "LIVE_BROKER":
            reasons.append("release evidence must come from LIVE_BROKER forward validation")
        if evidence.forward_live_trades < policy.min_forward_live_trades:
            reasons.append(
                f"forward trades {evidence.forward_live_trades} < {policy.min_forward_live_trades}"
            )
        if evidence.forward_live_days < policy.min_forward_live_days:
            reasons.append(
                f"forward days {evidence.forward_live_days} < {policy.min_forward_live_days}"
            )
        if evidence.max_drawdown_pct > policy.max_drawdown_pct:
            reasons.append(
                f"max drawdown {evidence.max_drawdown_pct}% > {policy.max_drawdown_pct}%"
            )
        if evidence.profit_factor < policy.min_profit_factor:
            reasons.append(
                f"profit factor {evidence.profit_factor} < {policy.min_profit_factor}"
            )
        if evidence.expectancy <= policy.min_expectancy:
            reasons.append(f"expectancy {evidence.expectancy} <= {policy.min_expectancy}")
        if evidence.critical_incidents > policy.max_critical_incidents:
            reasons.append("critical incidents exceed release policy")
        if evidence.reconciliation_failures > policy.max_reconciliation_failures:
            reasons.append("reconciliation failures exceed release policy")
        if (
            evidence.unresolved_data_integrity_events
            > policy.max_unresolved_data_integrity_events
        ):
            reasons.append("unresolved data-integrity events exceed release policy")

        manifest_hash = _manifest_hash(evidence, policy, tuple(reasons))
        return ProductionReleaseManifest(
            eligible=not reasons,
            reasons=tuple(reasons),
            evidence=evidence,
            policy=policy,
            manifest_hash=manifest_hash,
        )


def _manifest_hash(
    evidence: ProductionEvidence,
    policy: ReleasePolicy,
    reasons: tuple[str, ...],
) -> str:
    payload = {
        "evidence": _json_safe(asdict(evidence)),
        "policy": _json_safe(asdict(policy)),
        "reasons": list(reasons),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrategyStage):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
