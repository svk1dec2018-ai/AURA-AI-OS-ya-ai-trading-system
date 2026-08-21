from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from aura.ai.openai_responses import OpenAIResponsesClient
from aura.maintenance.authority import (
    AuthorityAction,
    AuthorityRole,
    DevelopmentAuthorityPolicy,
)
from aura.maintenance.models import (
    ChangeRisk,
    CodeChangeProposal,
    RepairPlan,
    SystemObservation,
)

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)"
        r"\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}"),
)

_FINANCIAL_CORE_PREFIXES = (
    "aura/execution/",
    "aura/portfolio/",
    "aura/risk/",
    "aura/persistence/",
    "aura/ops/release_gate.py",
    "aura/ops/preflight.py",
    "deploy/",
)


class OpenAIMaintenanceDeveloper:
    """ChatGPT-class diagnosis and patch-proposal adapter.

    This object has no filesystem write, shell, GitHub, broker, ledger, or approval
    methods. It can only turn sanitized diagnostics and selected source excerpts
    into a typed proposal. `DevelopmentChangeRegistry` and `SandboxPatchExecutor`
    enforce all later authority boundaries.
    """

    provider_id = "openai"

    def __init__(
        self,
        client: OpenAIResponsesClient,
        *,
        policy: DevelopmentAuthorityPolicy | None = None,
        max_files: int = 12,
        max_total_source_chars: int = 180_000,
    ) -> None:
        if max_files <= 0 or max_total_source_chars <= 0:
            raise ValueError("maintenance context limits must be positive")
        self.client = client
        self.model_id = client.model_id
        self.policy = policy or DevelopmentAuthorityPolicy()
        self.max_files = max_files
        self.max_total_source_chars = max_total_source_chars

    async def propose_repair(
        self,
        *,
        observation: SystemObservation,
        base_commit: str,
        relevant_files: Mapping[str, str],
    ) -> CodeChangeProposal:
        self.policy.require(AuthorityRole.MAINTENANCE_AI, AuthorityAction.DIAGNOSE_SYSTEM)
        self.policy.require(
            AuthorityRole.MAINTENANCE_AI,
            AuthorityAction.PROPOSE_CODE_CHANGE,
        )
        context = _sanitize_relevant_files(
            relevant_files,
            max_files=self.max_files,
            max_total_chars=self.max_total_source_chars,
        )
        response = await self.client.structured(
            system_prompt=(
                "You are AURA's maintenance developer AI. Diagnose only the supplied "
                "observation and source excerpts. Produce a minimal unified Git diff. "
                "Never request or expose secrets; never add deposit, withdrawal, fund-transfer, "
                "risk-bypass, direct historical fill/trade/P&L rewrite, self-approval, direct "
                "deployment, broker-order, or arbitrary shell capabilities. Preserve AURA's "
                "risk engine and append-only accounting. Every patch requires sandbox tests and "
                "owner approval. Emit only the strict schema."
            ),
            user_payload={
                "observation": _sanitized_observation(observation),
                "base_commit": base_commit,
                "relevant_files": context,
                "authority": {
                    "can_propose": True,
                    "can_apply": False,
                    "can_approve": False,
                    "can_deploy": False,
                    "can_move_funds": False,
                    "can_rewrite_financial_history": False,
                },
            },
            schema_name="aura_maintenance_repair_plan",
            schema=RepairPlan.model_json_schema(),
        )
        plan = RepairPlan.model_validate(response.output)
        if not plan.requires_owner_approval:
            raise ValueError("maintenance model attempted to omit owner approval")
        risk = (
            ChangeRisk.FINANCIAL_CORE
            if plan.touches_financial_core
            or any(path.startswith(_FINANCIAL_CORE_PREFIXES) for path in plan.changed_files)
            else ChangeRisk.STANDARD
        )
        patch_hash = hashlib.sha256(plan.unified_diff.encode("utf-8")).hexdigest()
        proposal_seed = (
            f"{observation.fingerprint}:{base_commit}:{response.response_id}:{patch_hash}"
        )
        return CodeChangeProposal(
            proposal_id=f"change:{hashlib.sha256(proposal_seed.encode()).hexdigest()[:32]}",
            observation_id=observation.observation_id,
            provider_id=self.provider_id,
            model_id=response.model_id,
            provider_response_id=response.response_id,
            base_commit=base_commit,
            diagnosis=plan.diagnosis,
            summary=plan.proposed_change_summary,
            changed_files=plan.changed_files,
            unified_diff=plan.unified_diff,
            validation_rationale=plan.validation_rationale,
            rollback_plan=plan.rollback_plan,
            residual_risks=plan.residual_risks,
            risk=risk,
        )


def _sanitize_relevant_files(
    files: Mapping[str, str],
    *,
    max_files: int,
    max_total_chars: int,
) -> dict[str, str]:
    if not files:
        raise ValueError("at least one relevant source file is required")
    if len(files) > max_files:
        raise ValueError(f"maintenance context exceeds {max_files} files")
    sanitized: dict[str, str] = {}
    total = 0
    for raw_path, content in sorted(files.items()):
        path = _safe_source_path(raw_path)
        redacted = _redact(content)
        total += len(redacted)
        if total > max_total_chars:
            raise ValueError("maintenance source context is too large")
        sanitized[path] = redacted
    return sanitized


def _safe_source_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or normalized.startswith((".git/", "runtime/"))
        or path.name.startswith(".env")
    ):
        raise ValueError(f"unsafe maintenance source path: {raw_path!r}")
    return path.as_posix()


def _redact(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _sanitized_observation(observation: SystemObservation) -> dict[str, object]:
    payload = observation.model_dump(mode="json")
    payload["summary"] = _redact(str(payload["summary"]))
    payload["symptoms"] = [_redact(str(item)) for item in payload["symptoms"]]
    payload["evidence"] = {
        key: _redact(value) if isinstance(value, str) else value
        for key, value in payload["evidence"].items()
    }
    return payload
