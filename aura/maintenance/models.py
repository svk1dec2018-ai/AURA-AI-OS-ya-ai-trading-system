from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:@/-]{1,160}$")
_MAX_REPORTING_ADJUSTMENT = Decimal(1000000000000000000)
_ALLOWED_CORRECTION_FIELDS = frozenset(
    {
        "annotation",
        "broker_reference",
        "closed_at",
        "entry_price",
        "execution_venue",
        "exit_price",
        "note",
        "opened_at",
        "quantity",
        "reported_fees",
        "reported_realized_pnl",
        "setup",
        "side",
        "status",
        "strategy_id",
    }
)


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MaintenanceSeverity(str, Enum):
    INFO = "INFO"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class ChangeRisk(str, Enum):
    STANDARD = "STANDARD"
    FINANCIAL_CORE = "FINANCIAL_CORE"


class ChangeStage(str, Enum):
    PROPOSED = "PROPOSED"
    SANDBOX_VALIDATED = "SANDBOX_VALIDATED"
    OWNER_APPROVED = "OWNER_APPROVED"
    APPLIED_TO_DEVELOPMENT = "APPLIED_TO_DEVELOPMENT"
    PR_READY = "PR_READY"
    REJECTED = "REJECTED"


class SystemObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(min_length=1, max_length=180)
    component: str = Field(min_length=1, max_length=180)
    severity: MaintenanceSeverity
    summary: str = Field(min_length=1, max_length=2000)
    symptoms: tuple[str, ...]
    evidence: dict[str, str | int | float | bool | None]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation timestamp must be timezone-aware")
        return value

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _canonical_hash(
            self.model_dump(mode="json", exclude={"fingerprint"})
        )


class RepairPlan(BaseModel):
    """Strict model output; it is a proposal and carries no apply authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnosis: str = Field(min_length=1, max_length=4000)
    root_cause_hypotheses: tuple[str, ...] = Field(min_length=1, max_length=8)
    proposed_change_summary: str = Field(min_length=1, max_length=2000)
    changed_files: tuple[str, ...] = Field(min_length=1, max_length=30)
    unified_diff: str = Field(min_length=1, max_length=500_000)
    validation_rationale: tuple[str, ...] = Field(min_length=1, max_length=12)
    rollback_plan: str = Field(min_length=1, max_length=2000)
    residual_risks: tuple[str, ...] = Field(max_length=12)
    requires_owner_approval: bool
    touches_financial_core: bool


class CodeChangeProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=180)
    observation_id: str = Field(min_length=1, max_length=180)
    provider_id: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=120)
    provider_response_id: str = Field(min_length=1, max_length=180)
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    diagnosis: str = Field(min_length=1, max_length=4000)
    summary: str = Field(min_length=1, max_length=2000)
    changed_files: tuple[str, ...] = Field(min_length=1, max_length=30)
    unified_diff: str = Field(min_length=1, max_length=500_000)
    validation_rationale: tuple[str, ...] = Field(min_length=1, max_length=12)
    rollback_plan: str = Field(min_length=1, max_length=2000)
    residual_risks: tuple[str, ...] = Field(max_length=12)
    risk: ChangeRisk
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    owner_approval_required: bool = True
    auto_apply_allowed: bool = False
    live_deploy_allowed: bool = False

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("proposal timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def immutable_authority_flags(self) -> CodeChangeProposal:
        if not self.owner_approval_required:
            raise ValueError("code proposals always require owner approval")
        if self.auto_apply_allowed or self.live_deploy_allowed:
            raise ValueError("AI code proposals cannot auto-apply or deploy live")
        return self

    @computed_field
    @property
    def patch_sha256(self) -> str:
        return hashlib.sha256(self.unified_diff.encode("utf-8")).hexdigest()


class SandboxCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command: tuple[str, ...]
    exit_code: int
    duration_ms: int = Field(ge=0)
    output_sha256: str = Field(pattern=_SHA256_PATTERN)
    output_tail: str = Field(max_length=2000)

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


class SandboxValidation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_id: str = Field(default_factory=lambda: f"validation:{uuid4()}")
    proposal_id: str
    patch_sha256: str = Field(pattern=_SHA256_PATTERN)
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    changed_files: tuple[str, ...]
    checks: tuple[SandboxCheck, ...]
    passed: bool
    credentials_available: bool = False
    live_money_enabled: bool = False
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("validated_at")
    @classmethod
    def validated_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("validation timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validation_flags_are_truthful(self) -> SandboxValidation:
        expected = bool(self.checks) and all(check.passed for check in self.checks)
        if self.passed != expected:
            raise ValueError("sandbox passed flag must match all check results")
        if self.credentials_available or self.live_money_enabled:
            raise ValueError("sandbox validation cannot expose credentials or live money")
        return self


class OwnerApprovalReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(default_factory=lambda: f"owner-approval:{uuid4()}")
    proposal_id: str
    validation_id: str
    patch_sha256: str = Field(pattern=_SHA256_PATTERN)
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    owner_id: str = Field(min_length=1, max_length=80)
    high_risk_acknowledged: bool
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scope: str = "development_branch_only"
    live_deploy_authority: bool = False
    financial_execution_authority: bool = False

    @field_validator("owner_id")
    @classmethod
    def owner_id_is_safe(cls, value: str) -> str:
        if _SAFE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("owner_id contains unsafe characters")
        return value

    @field_validator("approved_at")
    @classmethod
    def approved_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def approval_scope_is_bounded(self) -> OwnerApprovalReceipt:
        if self.scope != "development_branch_only":
            raise ValueError("owner approval scope must remain development_branch_only")
        if self.live_deploy_authority or self.financial_execution_authority:
            raise ValueError("code approval cannot grant live or financial authority")
        return self


class AppliedChangeReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    application_id: str = Field(default_factory=lambda: f"development-apply:{uuid4()}")
    proposal_id: str
    approval_id: str
    patch_sha256: str = Field(pattern=_SHA256_PATTERN)
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    resulting_diff_sha256: str = Field(pattern=_SHA256_PATTERN)
    applied_by_role: str
    applied_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    committed: bool = False
    pushed: bool = False
    deployed: bool = False

    @field_validator("applied_at")
    @classmethod
    def applied_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("application timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def receipt_cannot_claim_delivery(self) -> AppliedChangeReceipt:
        if self.committed or self.pushed or self.deployed:
            raise ValueError("development apply receipt cannot claim commit, push, or deploy")
        return self


class FinancialMode(str, Enum):
    PAPER = "PAPER"
    CONTROLLED_LIVE = "CONTROLLED_LIVE"


class FinancialCorrectionKind(str, Enum):
    TRADE_ANNOTATION = "TRADE_ANNOTATION"
    PNL_ADJUSTMENT = "PNL_ADJUSTMENT"
    FEE_ADJUSTMENT = "FEE_ADJUSTMENT"
    BROKER_TRADE_CORRECTION = "BROKER_TRADE_CORRECTION"


class FinancialCorrectionRequest(BaseModel):
    """Append-only reporting correction; cash and position fields do not exist."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correction_id: str = Field(default_factory=lambda: f"correction:{uuid4()}")
    mode: FinancialMode
    kind: FinancialCorrectionKind
    target_trade_id: str | None = Field(default=None, max_length=180)
    net_realized_pnl_delta: Decimal = Decimal(0)
    fee_delta: Decimal = Decimal(0)
    corrected_fields: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(min_length=8, max_length=2000)
    requested_by: str = Field(min_length=1, max_length=80)
    evidence_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    reconciliation_id: str | None = Field(default=None, max_length=180)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("requested_by")
    @classmethod
    def requested_by_is_safe(cls, value: str) -> str:
        if _SAFE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("requested_by contains unsafe characters")
        return value

    @field_validator("target_trade_id", "reconciliation_id")
    @classmethod
    def optional_ids_are_safe(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("financial correction identifier contains unsafe characters")
        return value

    @field_validator("net_realized_pnl_delta", "fee_delta")
    @classmethod
    def reporting_adjustments_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or abs(value) > _MAX_REPORTING_ADJUSTMENT:
            raise ValueError("reporting adjustment must be finite and within the bounded range")
        return value

    @field_validator("corrected_fields")
    @classmethod
    def corrected_fields_are_reporting_only(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 16:
            raise ValueError("too many corrected reporting fields")
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if key not in _ALLOWED_CORRECTION_FIELDS:
                raise ValueError(f"unsupported corrected reporting field: {key}")
            if not item.strip() or len(item) > 500:
                raise ValueError("corrected reporting values must contain 1-500 characters")
            normalized[key] = item.strip()
        return dict(sorted(normalized.items()))

    @field_validator("created_at")
    @classmethod
    def correction_timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("correction timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def correction_is_coherent(self) -> FinancialCorrectionRequest:
        if self.kind == FinancialCorrectionKind.TRADE_ANNOTATION:
            if self.net_realized_pnl_delta != 0 or self.fee_delta != 0:
                raise ValueError("trade annotations cannot change reported money")
            if not self.target_trade_id or not self.corrected_fields:
                raise ValueError("trade annotation requires a target and corrected fields")
        elif self.kind == FinancialCorrectionKind.PNL_ADJUSTMENT:
            if self.net_realized_pnl_delta == 0 or self.fee_delta != 0:
                raise ValueError("P&L adjustment requires only a non-zero net P&L delta")
        elif self.kind == FinancialCorrectionKind.FEE_ADJUSTMENT:
            if self.fee_delta == 0 or self.net_realized_pnl_delta != -self.fee_delta:
                raise ValueError("fee correction P&L delta must exactly negate the fee delta")
        elif self.kind == FinancialCorrectionKind.BROKER_TRADE_CORRECTION:
            if not self.target_trade_id or not self.corrected_fields:
                raise ValueError("broker trade correction requires target and corrected fields")
        if self.mode == FinancialMode.CONTROLLED_LIVE and (
            self.evidence_sha256 is None or not self.reconciliation_id
        ):
            raise ValueError(
                "controlled-live correction requires broker evidence and reconciliation binding"
            )
        return self

    @computed_field
    @property
    def content_sha256(self) -> str:
        return _canonical_hash(
            self.model_dump(mode="json", exclude={"content_sha256"})
        )


class FinancialCorrectionApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(default_factory=lambda: f"correction-approval:{uuid4()}")
    correction_id: str
    correction_content_sha256: str = Field(pattern=_SHA256_PATTERN)
    owner_id: str = Field(min_length=1, max_length=80)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fund_movement_authority: bool = False
    historical_rewrite_authority: bool = False

    @field_validator("owner_id")
    @classmethod
    def correction_owner_id_is_safe(cls, value: str) -> str:
        if _SAFE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("owner_id contains unsafe characters")
        return value

    @field_validator("approved_at")
    @classmethod
    def correction_approved_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("correction approval timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def correction_approval_cannot_expand_authority(self) -> FinancialCorrectionApproval:
        if self.fund_movement_authority or self.historical_rewrite_authority:
            raise ValueError("correction approval cannot move funds or rewrite history")
        return self


class CorrectedFinancialView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_realized_pnl: Decimal
    corrected_realized_pnl: Decimal
    base_fees_paid: Decimal
    corrected_fees_paid: Decimal
    approved_correction_ids: tuple[str, ...]
    trade_annotations: dict[str, tuple[dict[str, str], ...]]
    source_ledger_mutated: bool = False
    fund_movement_performed: bool = False

    @model_validator(mode="after")
    def view_is_non_mutating(self) -> CorrectedFinancialView:
        if self.source_ledger_mutated or self.fund_movement_performed:
            raise ValueError("corrected view cannot mutate source ledger or funds")
        return self
