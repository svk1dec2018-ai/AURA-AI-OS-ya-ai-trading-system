from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.domain.models import OrderStatus
from aura.execution.broker import BrokerExecutionMode


class BrokerEvidenceSource(str, Enum):
    INTERNAL_FIXTURE = "INTERNAL_FIXTURE"
    AUTHORIZED_EXTERNAL_BROKER = "AUTHORIZED_EXTERNAL_BROKER"


class BrokerExecutionObservation(BaseModel):
    """Credential-free facts exported after one externally authorized order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    probe_id: str = Field(min_length=1)
    client_order_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    broker_order_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    broker_response_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_quantity: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(ge=0)
    fill_count: int = Field(ge=0)
    final_status: OrderStatus
    submitted_at: datetime
    acknowledged_at: datetime
    final_observed_at: datetime

    @field_validator("submitted_at", "acknowledged_at", "final_observed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("broker evidence timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_execution_sequence(self) -> BrokerExecutionObservation:
        if not self.submitted_at <= self.acknowledged_at <= self.final_observed_at:
            raise ValueError("broker execution timestamps are not causal")
        if self.filled_quantity > self.requested_quantity:
            raise ValueError("broker evidence reports an overfill")
        if self.fill_count == 0 and self.filled_quantity != 0:
            raise ValueError("filled quantity requires at least one normalized fill")
        if self.final_status == OrderStatus.FILLED and (
            self.filled_quantity != self.requested_quantity or self.fill_count == 0
        ):
            raise ValueError("FILLED evidence requires complete normalized fills")
        return self


class BrokerReconciliationObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    observed_at: datetime
    local_open_orders: int = Field(ge=0)
    broker_open_orders: int = Field(ge=0)
    compared_positions: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    critical_issue_count: int = Field(ge=0)
    safe_for_new_risk: bool
    report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reconciliation timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def safety_flag_must_match_issues(self) -> BrokerReconciliationObservation:
        if self.critical_issue_count > self.issue_count:
            raise ValueError("critical reconciliation issues exceed total issues")
        if self.safe_for_new_risk != (self.critical_issue_count == 0):
            raise ValueError("reconciliation safety flag contradicts critical issues")
        return self


class BrokerEvidenceBundle(BaseModel):
    """A non-authoritative evidence export; never a permission to trade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    capture_id: str = Field(min_length=1)
    adapter_name: str = Field(min_length=1)
    mode: BrokerExecutionMode
    source: BrokerEvidenceSource
    environment_verified: bool
    account_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    attestation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    executions: tuple[BrokerExecutionObservation, ...]
    reconciliation_runs: tuple[BrokerReconciliationObservation, ...]
    execution_authority: Literal[False] = False

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("broker evidence captured_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def observations_cannot_arrive_after_capture(self) -> BrokerEvidenceBundle:
        if any(item.final_observed_at > self.captured_at for item in self.executions):
            raise ValueError("execution evidence arrives after bundle capture")
        if any(item.observed_at > self.captured_at for item in self.reconciliation_runs):
            raise ValueError("reconciliation evidence arrives after bundle capture")
        if (
            self.mode in {BrokerExecutionMode.PAPER, BrokerExecutionMode.READ_ONLY}
            and self.executions
        ):
            raise ValueError("paper/read-only evidence cannot claim broker execution")
        probe_ids = [item.probe_id for item in self.executions]
        if len(set(probe_ids)) != len(probe_ids):
            raise ValueError("broker execution probe IDs must be unique")
        run_ids = [item.run_id for item in self.reconciliation_runs]
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("broker reconciliation run IDs must be unique")
        return self


class SealedBrokerEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle: BrokerEvidenceBundle
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> SealedBrokerEvidence:
        expected = broker_evidence_sha256(self.bundle)
        if self.sha256 != expected:
            raise ValueError("broker evidence content hash mismatch")
        return self

    @classmethod
    def seal(cls, bundle: BrokerEvidenceBundle) -> SealedBrokerEvidence:
        return cls(bundle=bundle, sha256=broker_evidence_sha256(bundle))


class BrokerAttestationReview(BaseModel):
    """One credential-free human review bound to an exact evidence bundle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_at: datetime
    decision: Literal["ACCEPTED"] = "ACCEPTED"
    purpose: Literal["PHASE11_BROKER_EVIDENCE"] = "PHASE11_BROKER_EVIDENCE"

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("broker attestation review timestamp must be timezone-aware")
        return value


class BrokerAttestationRegistry(BaseModel):
    """Owner-controlled review quorum; it grants no broker or execution authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    registry_id: str = Field(min_length=1)
    generated_at: datetime
    minimum_independent_reviewers: int = Field(default=2, ge=2)
    reviews: tuple[BrokerAttestationReview, ...]
    execution_authority: Literal[False] = False

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attestation registry timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_review_registry(self) -> BrokerAttestationRegistry:
        identities = [
            (review.bundle_sha256, review.reviewer_fingerprint)
            for review in self.reviews
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate broker attestation review")
        if any(review.reviewed_at > self.generated_at for review in self.reviews):
            raise ValueError("broker attestation review occurs after registry generation")
        return self

    def verifies(self, bundle: BrokerEvidenceBundle) -> bool:
        digest = broker_evidence_sha256(bundle)
        reviewers = {
            review.reviewer_fingerprint
            for review in self.reviews
            if review.bundle_sha256 == digest
        }
        return len(reviewers) >= self.minimum_independent_reviewers


class SealedBrokerAttestationRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry: BrokerAttestationRegistry
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> SealedBrokerAttestationRegistry:
        expected = broker_attestation_registry_sha256(self.registry)
        if self.sha256 != expected:
            raise ValueError("broker attestation registry content hash mismatch")
        return self

    @classmethod
    def seal(
        cls,
        registry: BrokerAttestationRegistry,
    ) -> SealedBrokerAttestationRegistry:
        return cls(
            registry=registry,
            sha256=broker_attestation_registry_sha256(registry),
        )


class BrokerAdapterEvidenceAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_name: str
    present: bool
    trusted_external_source: bool
    controlled_live_mode: bool
    environment_verified: bool
    filled_execution_verified: bool
    stable_reconciliation_verified: bool
    eligible: bool
    reasons: tuple[str, ...]


class BrokerEvidenceAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: Literal[11] = 11
    gate_decision: Literal["PASS", "BLOCKED"]
    adapters: tuple[BrokerAdapterEvidenceAssessment, ...]
    phase11_eligible: bool
    reasons: tuple[str, ...]
    execution_authority: Literal[False] = False


class BrokerEvidencePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    required_adapters: tuple[str, ...] = (
        "ANGEL_ONE_SMARTAPI",
        "MT5",
    )
    min_filled_executions: int = Field(default=1, gt=0)
    min_clean_reconciliation_runs: int = Field(default=3, gt=0)

    @field_validator("required_adapters")
    @classmethod
    def adapters_must_be_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("required broker adapters cannot be empty")
        normalized = tuple(item.strip().upper() for item in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("required broker adapters must be unique")
        return normalized


class BrokerEvidenceVerifier:
    """Assess external proof without connecting to or authorizing a broker."""

    def __init__(
        self,
        policy: BrokerEvidencePolicy | None = None,
        *,
        attestation_verifier: Callable[[BrokerEvidenceBundle], bool] | None = None,
    ) -> None:
        self.policy = policy or BrokerEvidencePolicy()
        self.attestation_verifier = attestation_verifier

    def assess(
        self,
        evidence: tuple[SealedBrokerEvidence, ...],
    ) -> BrokerEvidenceAssessment:
        by_adapter: dict[str, list[BrokerEvidenceBundle]] = {}
        capture_ids: set[str] = set()
        for item in evidence:
            if item.bundle.capture_id in capture_ids:
                raise ValueError("duplicate broker evidence capture_id")
            capture_ids.add(item.bundle.capture_id)
            key = item.bundle.adapter_name.strip().upper()
            by_adapter.setdefault(key, []).append(item.bundle)

        adapter_results = tuple(
            self._assess_adapter(adapter, tuple(by_adapter.get(adapter, ())))
            for adapter in self.policy.required_adapters
        )
        eligible = all(item.eligible for item in adapter_results)
        reasons = tuple(
            f"{item.adapter_name}: {reason}"
            for item in adapter_results
            for reason in item.reasons
        )
        return BrokerEvidenceAssessment(
            gate_decision="PASS" if eligible else "BLOCKED",
            adapters=adapter_results,
            phase11_eligible=eligible,
            reasons=reasons,
        )

    def _assess_adapter(
        self,
        adapter_name: str,
        bundles: tuple[BrokerEvidenceBundle, ...],
    ) -> BrokerAdapterEvidenceAssessment:
        present = bool(bundles)
        trusted = (
            present
            and self.attestation_verifier is not None
            and all(
                item.source == BrokerEvidenceSource.AUTHORIZED_EXTERNAL_BROKER
                and self.attestation_verifier(item)
                for item in bundles
            )
        )
        controlled_live = present and all(
            item.mode == BrokerExecutionMode.CONTROLLED_LIVE for item in bundles
        )
        environment_verified = present and all(item.environment_verified for item in bundles)
        execution_items = [
            execution
            for bundle in bundles
            for execution in bundle.executions
        ]
        if len({item.probe_id for item in execution_items}) != len(execution_items):
            raise ValueError(f"duplicate execution probe_id for {adapter_name}")
        filled = sum(
            1
            for execution in execution_items
            if execution.final_status == OrderStatus.FILLED
            and execution.filled_quantity == execution.requested_quantity
            and execution.fill_count > 0
        )
        reconciliation_items = [
            run
            for bundle in bundles
            for run in bundle.reconciliation_runs
        ]
        if len({item.run_id for item in reconciliation_items}) != len(
            reconciliation_items
        ):
            raise ValueError(f"duplicate reconciliation run_id for {adapter_name}")
        reconciliation_runs = sorted(
            reconciliation_items,
            key=lambda item: (item.observed_at, item.run_id),
        )
        filled_verified = filled >= self.policy.min_filled_executions
        stable_reconciliation = (
            len(reconciliation_runs) >= self.policy.min_clean_reconciliation_runs
            and all(
                run.safe_for_new_risk and run.critical_issue_count == 0
                for run in reconciliation_runs[-self.policy.min_clean_reconciliation_runs :]
            )
        )
        checks = {
            "evidence bundle is missing": present,
            "evidence source is not an authorized external broker export": trusted,
            "controlled-live broker mode is not externally verified": controlled_live,
            "broker environment identity is not verified": environment_verified,
            "no complete normalized broker fill is verified": filled_verified,
            "insufficient consecutive clean reconciliation evidence": stable_reconciliation,
        }
        reasons = tuple(reason for reason, passed in checks.items() if not passed)
        return BrokerAdapterEvidenceAssessment(
            adapter_name=adapter_name,
            present=present,
            trusted_external_source=trusted,
            controlled_live_mode=controlled_live,
            environment_verified=environment_verified,
            filled_execution_verified=filled_verified,
            stable_reconciliation_verified=stable_reconciliation,
            eligible=not reasons,
            reasons=reasons,
        )


_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "api_key",
        "authorization",
        "jwt",
        "password",
        "pin",
        "refresh_token",
        "secret",
        "session_token",
        "totp",
    }
)


def load_sealed_broker_evidence(path: Path) -> SealedBrokerEvidence:
    raw = json.loads(path.read_text(encoding="utf-8"))
    _reject_secret_fields(raw)
    return SealedBrokerEvidence.model_validate(raw)


def load_sealed_broker_attestation_registry(
    path: Path,
) -> SealedBrokerAttestationRegistry:
    raw = json.loads(path.read_text(encoding="utf-8"))
    _reject_secret_fields(raw)
    return SealedBrokerAttestationRegistry.model_validate(raw)


def broker_evidence_sha256(bundle: BrokerEvidenceBundle) -> str:
    return hashlib.sha256(_canonical_json(bundle.model_dump(mode="json"))).hexdigest()


def broker_attestation_registry_sha256(registry: BrokerAttestationRegistry) -> str:
    return hashlib.sha256(_canonical_json(registry.model_dump(mode="json"))).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _reject_secret_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise ValueError(f"broker evidence contains forbidden secret field at {path}.{key}")
            _reject_secret_fields(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_fields(item, f"{path}[{index}]")
