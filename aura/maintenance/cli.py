from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from aura.ai.openai_responses import OpenAIResponsesClient
from aura.maintenance.authority import AuthorityRole, DevelopmentAuthorityPolicy
from aura.maintenance.change_control import (
    ChangeControlError,
    DevelopmentChangeRegistry,
    SandboxPatchExecutor,
)
from aura.maintenance.financial_corrections import AuditedFinancialCorrectionLedger
from aura.maintenance.models import (
    FinancialCorrectionKind,
    FinancialCorrectionRequest,
    FinancialMode,
    MaintenanceSeverity,
    SystemObservation,
)
from aura.maintenance.openai_developer import OpenAIMaintenanceDeveloper

_DEFAULT_CHANGE_JOURNAL = Path("runtime/maintenance/change_registry.jsonl")
_DEFAULT_CORRECTION_JOURNAL = Path("runtime/maintenance/financial_corrections.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aura-maintenance",
        description="Owner-controlled AURA monitoring, repair and correction plane",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("policy", help="print the machine-readable authority matrix")

    probe = subparsers.add_parser("probe", help="run credential-free repository health checks")
    probe.add_argument("--repository", type=Path, default=Path.cwd())

    propose = subparsers.add_parser(
        "propose",
        help="ask OpenAI for a patch and validate it in the credential-free sandbox",
    )
    propose.add_argument("--repository", type=Path, default=Path.cwd())
    propose.add_argument("--journal", type=Path, default=_DEFAULT_CHANGE_JOURNAL)
    propose.add_argument("--component", required=True)
    propose.add_argument(
        "--severity",
        choices=[item.value for item in MaintenanceSeverity],
        default=MaintenanceSeverity.DEGRADED.value,
    )
    propose.add_argument("--summary", required=True)
    propose.add_argument("--source", action="append", required=True)
    propose.add_argument("--model", default=os.getenv("AURA_MAINTENANCE_OPENAI_MODEL", "gpt-5.4-mini"))

    apply_command = subparsers.add_parser(
        "approve-apply",
        help="owner-approve an exact validated patch and apply it to a clean development worktree",
    )
    apply_command.add_argument("--repository", type=Path, default=Path.cwd())
    apply_command.add_argument("--journal", type=Path, default=_DEFAULT_CHANGE_JOURNAL)
    apply_command.add_argument("--proposal-id", required=True)
    apply_command.add_argument("--expected-patch-sha256", required=True)
    apply_command.add_argument("--owner-id", required=True)
    apply_command.add_argument("--ack-financial-core", action="store_true")

    status = subparsers.add_parser("status", help="show one change proposal's governed stage")
    status.add_argument("--journal", type=Path, default=_DEFAULT_CHANGE_JOURNAL)
    status.add_argument("--proposal-id", required=True)

    request = subparsers.add_parser(
        "correction-request",
        help="append a typed P&L/trade reporting correction request",
    )
    request.add_argument("--journal", type=Path, default=_DEFAULT_CORRECTION_JOURNAL)
    request.add_argument("--mode", choices=[item.value for item in FinancialMode], required=True)
    request.add_argument(
        "--kind",
        choices=[item.value for item in FinancialCorrectionKind],
        required=True,
    )
    request.add_argument("--target-trade-id")
    request.add_argument("--pnl-delta", type=Decimal, default=Decimal(0))
    request.add_argument("--fee-delta", type=Decimal, default=Decimal(0))
    request.add_argument("--field", action="append", default=[])
    request.add_argument("--reason", required=True)
    request.add_argument("--requester", required=True)
    request.add_argument("--evidence-sha256")
    request.add_argument("--reconciliation-id")

    approve = subparsers.add_parser(
        "correction-approve",
        help="owner-approve one exact append-only reporting correction",
    )
    approve.add_argument("--journal", type=Path, default=_DEFAULT_CORRECTION_JOURNAL)
    approve.add_argument("--correction-id", required=True)
    approve.add_argument("--expected-content-sha256", required=True)
    approve.add_argument("--owner-id", required=True)

    view = subparsers.add_parser(
        "correction-view",
        help="derive a corrected view without mutating fills, cash or positions",
    )
    view.add_argument("--journal", type=Path, default=_DEFAULT_CORRECTION_JOURNAL)
    view.add_argument("--base-realized-pnl", type=Decimal, required=True)
    view.add_argument("--base-fees-paid", type=Decimal, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "policy":
            _emit(
                {
                    "authority": [
                        item.model_dump(mode="json")
                        for item in DevelopmentAuthorityPolicy().matrix()
                    ],
                    "fund_operations_available": False,
                }
            )
            return 0
        if args.command == "probe":
            return _probe(args.repository)
        if args.command == "propose":
            return asyncio.run(_propose(args))
        if args.command == "approve-apply":
            return _approve_apply(args)
        if args.command == "status":
            registry = DevelopmentChangeRegistry(_resolve_journal(args.journal, Path.cwd()))
            proposal = registry.get(args.proposal_id)
            _emit(
                {
                    "proposal_id": proposal.proposal_id,
                    "patch_sha256": proposal.patch_sha256,
                    "risk": proposal.risk.value,
                    "stage": registry.stage(proposal.proposal_id).value,
                    "fund_movement_allowed": False,
                    "live_deploy_authority": False,
                }
            )
            return 0
        if args.command == "correction-request":
            return _correction_request(args)
        if args.command == "correction-approve":
            return _correction_approve(args)
        if args.command == "correction-view":
            return _correction_view(args)
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
        return 2
    return 2


def _probe(repository: Path) -> int:
    root = repository.resolve()
    checks = (
        ("git_diff_check", ("git", "diff", "--check")),
        ("python_compile", (sys.executable, "-m", "compileall", "-q", "aura")),
    )
    results = []
    for name, command in checks:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
            env=_probe_environment(root),
        )
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        results.append(
            {
                "component": name,
                "healthy": completed.returncode == 0,
                "exit_code": completed.returncode,
                "detail": output[-1000:],
            }
        )
    healthy = all(item["healthy"] for item in results)
    _emit(
        {
            "ok": healthy,
            "repository": str(root),
            "checks": results,
            "credentials_used": False,
            "broker_connection_used": False,
            "fund_operations_available": False,
        }
    )
    return 0 if healthy else 1


async def _propose(args: argparse.Namespace) -> int:
    root = args.repository.resolve()
    _load_local_openai_key(root)
    commit = _git_output(root, "rev-parse", "HEAD")
    files = _load_tracked_sources(root, args.source)
    observed_at = datetime.now(UTC)
    observation = SystemObservation(
        observation_id=(
            f"manual:{args.component}:"
            f"{int(observed_at.timestamp() * 1_000_000)}"
        ),
        component=args.component,
        severity=MaintenanceSeverity(args.severity),
        summary=args.summary,
        symptoms=(args.summary,),
        evidence={"source": "authenticated_local_owner_cli"},
        observed_at=observed_at,
    )
    client = OpenAIResponsesClient(args.model)
    developer = OpenAIMaintenanceDeveloper(client)
    proposal = await developer.propose_repair(
        observation=observation,
        base_commit=commit,
        relevant_files=files,
    )
    journal = _resolve_journal(args.journal, root)
    registry = DevelopmentChangeRegistry(journal)
    registry.submit(proposal, role=AuthorityRole.MAINTENANCE_AI)
    validation = SandboxPatchExecutor().validate(proposal, repository_root=root)
    registry.record_validation(validation, role=AuthorityRole.MAINTENANCE_AI)
    _emit(
        {
            "ok": validation.passed,
            "proposal_id": proposal.proposal_id,
            "patch_sha256": proposal.patch_sha256,
            "changed_files": proposal.changed_files,
            "risk": proposal.risk.value,
            "stage": registry.stage(proposal.proposal_id).value,
            "sandbox_checks": [check.model_dump(mode="json") for check in validation.checks],
            "owner_approval_required": True,
            "auto_apply_allowed": False,
            "live_deploy_authority": False,
            "fund_movement_allowed": False,
        }
    )
    return 0 if validation.passed else 1


def _approve_apply(args: argparse.Namespace) -> int:
    root = args.repository.resolve()
    registry = DevelopmentChangeRegistry(_resolve_journal(args.journal, root))
    proposal = registry.get(args.proposal_id)
    if proposal.patch_sha256 != args.expected_patch_sha256:
        raise ChangeControlError("expected patch hash does not match the reviewed proposal")
    approval = registry.approve(
        proposal.proposal_id,
        role=AuthorityRole.OWNER,
        owner_id=args.owner_id,
        high_risk_acknowledged=args.ack_financial_core,
    )
    executor = SandboxPatchExecutor()
    application = executor.apply_to_development(
        proposal,
        approval,
        repository_root=root,
        role=AuthorityRole.OWNER,
    )
    registry.record_application(application, role=AuthorityRole.OWNER)
    _emit(
        {
            "ok": True,
            "proposal_id": proposal.proposal_id,
            "application_id": application.application_id,
            "stage": registry.stage(proposal.proposal_id).value,
            "committed": False,
            "pushed": False,
            "deployed": False,
            "fund_movement_allowed": False,
        }
    )
    return 0


def _correction_request(args: argparse.Namespace) -> int:
    fields = _parse_fields(args.field)
    correction = FinancialCorrectionRequest(
        mode=FinancialMode(args.mode),
        kind=FinancialCorrectionKind(args.kind),
        target_trade_id=args.target_trade_id,
        net_realized_pnl_delta=args.pnl_delta,
        fee_delta=args.fee_delta,
        corrected_fields=fields,
        reason=args.reason,
        requested_by=args.requester,
        evidence_sha256=args.evidence_sha256,
        reconciliation_id=args.reconciliation_id,
    )
    ledger = AuditedFinancialCorrectionLedger(
        _resolve_journal(args.journal, Path.cwd())
    )
    ledger.request(correction, role=AuthorityRole.OWNER)
    _emit(
        {
            "ok": True,
            "correction_id": correction.correction_id,
            "content_sha256": correction.content_sha256,
            "approved": False,
            "source_ledger_mutated": False,
            "fund_movement_allowed": False,
        }
    )
    return 0


def _correction_approve(args: argparse.Namespace) -> int:
    ledger = AuditedFinancialCorrectionLedger(
        _resolve_journal(args.journal, Path.cwd())
    )
    approval = ledger.approve(
        args.correction_id,
        role=AuthorityRole.OWNER,
        owner_id=args.owner_id,
        expected_content_sha256=args.expected_content_sha256,
    )
    _emit(
        {
            "ok": True,
            "correction_id": approval.correction_id,
            "approval_id": approval.approval_id,
            "fund_movement_authority": False,
            "historical_rewrite_authority": False,
        }
    )
    return 0


def _correction_view(args: argparse.Namespace) -> int:
    ledger = AuditedFinancialCorrectionLedger(
        _resolve_journal(args.journal, Path.cwd())
    )
    view = ledger.corrected_view(
        base_realized_pnl=args.base_realized_pnl,
        base_fees_paid=args.base_fees_paid,
    )
    _emit({"ok": True, "view": view.model_dump(mode="json")})
    return 0


def _load_tracked_sources(root: Path, raw_paths: list[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for raw in raw_paths:
        normalized = PurePosixPath(raw.replace("\\", "/")).as_posix()
        if not normalized or normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
            raise ValueError(f"unsafe source path: {raw!r}")
        tracked = subprocess.run(
            ("git", "ls-files", "--error-unmatch", "--", normalized),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0:
            raise ValueError(f"maintenance source must be tracked: {normalized}")
        path = root / normalized
        if path.is_symlink() or not path.is_file() or path.name.startswith(".env"):
            raise ValueError(f"unsafe maintenance source: {normalized}")
        sources[normalized] = path.read_text(encoding="utf-8")
    return sources


def _load_local_openai_key(root: Path) -> None:
    if os.getenv("OPENAI_API_KEY", "").strip():
        return
    path = root / ".env.local"
    if not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise ValueError(".env.local must be a regular non-symlink file")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == "OPENAI_API_KEY" and value.strip():
            os.environ["OPENAI_API_KEY"] = value.strip().strip('"').strip("'")
            return


def _parse_fields(values: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--field values must use key=value")
        key, item = value.split("=", 1)
        key = key.strip()
        if not key or key in fields:
            raise ValueError("correction field keys must be non-empty and unique")
        fields[key] = item.strip()
    return fields


def _resolve_journal(path: Path, root: Path) -> Path:
    return path if path.is_absolute() else root / path


def _git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ChangeControlError(f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def _probe_environment(root: Path) -> dict[str, str]:
    probe_home = root / "runtime" / "maintenance" / "probe-home"
    probe_home.mkdir(parents=True, exist_ok=True)
    allowed = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "PATHEXT")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment.update(
        {
            "HOME": str(probe_home),
            "PYTHONNOUSERSITE": "1",
            "AURA_LIVE_TRADING": "0",
            "AURA_NETWORK_DISABLED": "1",
        }
    )
    return environment


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
