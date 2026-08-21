from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

from aura.maintenance.authority import (
    AuthorityAction,
    AuthorityRole,
    DevelopmentAuthorityPolicy,
)
from aura.maintenance.models import (
    AppliedChangeReceipt,
    ChangeRisk,
    ChangeStage,
    CodeChangeProposal,
    OwnerApprovalReceipt,
    SandboxCheck,
    SandboxValidation,
)
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent

_REGISTRY_SCHEMA_VERSION = 1
_HEADER_EVENT = "maintenance_change_registry_initialized"
_PROPOSAL_EVENT = "maintenance_change_proposed"
_VALIDATION_EVENT = "maintenance_change_sandbox_validated"
_APPROVAL_EVENT = "maintenance_change_owner_approved"
_APPLIED_EVENT = "maintenance_change_applied_to_development"
_PR_READY_EVENT = "maintenance_change_pr_ready"

_DIFF_HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$", re.MULTILINE)
_FORBIDDEN_ADDITION = re.compile(
    r"(?i)\b(withdraw(?:al|[_-]?funds)?|deposit(?:[_-]?funds)?|add[_-]?funds|fund[_-]?transfer|"
    r"transfer[_-]?funds|cash[_-]?transfer)\b"
)
_SECRET_REDACTION = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)"
    r"\s*[:=]\s*[^\s,;]+"
)

_IMMUTABLE_PATHS = frozenset(
    {
        "aura/maintenance/authority.py",
        "aura/maintenance/change_control.py",
        "aura/maintenance/financial_corrections.py",
        "aura/maintenance/models.py",
    }
)
_IMMUTABLE_PREFIXES = (
    ".git/",
    ".github/workflows/",
    "runtime/",
    "artifacts/operator/",
)
_FINANCIAL_CORE_PREFIXES = (
    "aura/execution/",
    "aura/portfolio/",
    "aura/risk/",
    "aura/persistence/",
    "aura/ops/release_gate.py",
    "aura/ops/preflight.py",
    "deploy/",
    "scripts/",
)


class ChangeControlError(RuntimeError):
    pass


def extract_changed_files(unified_diff: str) -> tuple[str, ...]:
    if not unified_diff.strip() or "\x00" in unified_diff:
        raise ChangeControlError("patch must be non-empty text")
    matches = _DIFF_HEADER.findall(unified_diff)
    if not matches:
        raise ChangeControlError("patch must contain canonical git diff headers")
    files: list[str] = []
    for old_path, new_path in matches:
        if old_path != new_path:
            raise ChangeControlError("maintenance patches cannot rename files")
        normalized = _safe_patch_path(old_path)
        if normalized not in files:
            files.append(normalized)
    return tuple(sorted(files))


def classify_change_risk(paths: tuple[str, ...]) -> ChangeRisk:
    return (
        ChangeRisk.FINANCIAL_CORE
        if any(path.startswith(_FINANCIAL_CORE_PREFIXES) for path in paths)
        else ChangeRisk.STANDARD
    )


def validate_code_change_proposal(proposal: CodeChangeProposal) -> tuple[str, ...]:
    changed_files = extract_changed_files(proposal.unified_diff)
    if tuple(sorted(set(proposal.changed_files))) != changed_files:
        raise ChangeControlError("proposal changed_files do not match its unified diff")
    for path in changed_files:
        if _path_is_immutable(path):
            raise ChangeControlError(f"maintenance patch targets immutable path: {path}")
    added_code = "\n".join(
        line[1:]
        for line in proposal.unified_diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    if _FORBIDDEN_ADDITION.search(added_code):
        raise ChangeControlError("patch attempts to add a forbidden fund-operation capability")
    expected_risk = classify_change_risk(changed_files)
    if proposal.risk != expected_risk:
        raise ChangeControlError(
            f"proposal risk {proposal.risk.value} does not match {expected_risk.value}"
        )
    return changed_files


class DevelopmentChangeRegistry:
    """Restart-safe proposal -> sandbox -> owner -> development audit ledger."""

    def __init__(
        self,
        journal_path: Path,
        *,
        policy: DevelopmentAuthorityPolicy | None = None,
    ) -> None:
        self.journal_path = journal_path
        self.policy = policy or DevelopmentAuthorityPolicy()
        self._wal = JsonlWriteAheadLog(journal_path)
        self._proposals: dict[str, CodeChangeProposal] = {}
        self._validations: dict[str, SandboxValidation] = {}
        self._approvals: dict[str, OwnerApprovalReceipt] = {}
        self._applications: dict[str, AppliedChangeReceipt] = {}
        self._pr_ready: set[str] = set()
        self.recovered_events = 0
        self._initialize_or_replay()

    def submit(
        self,
        proposal: CodeChangeProposal,
        *,
        role: AuthorityRole = AuthorityRole.MAINTENANCE_AI,
    ) -> bool:
        self.policy.require(role, AuthorityAction.PROPOSE_CODE_CHANGE)
        validate_code_change_proposal(proposal)
        existing = self._proposals.get(proposal.proposal_id)
        if existing is not None:
            if existing != proposal:
                raise ChangeControlError("proposal identity collision")
            return False
        event = self._wal.append(
            event_type=_PROPOSAL_EVENT,
            payload={
                "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                "proposal": proposal.model_dump(mode="json", exclude={"patch_sha256"}),
            },
            correlation_id=proposal.proposal_id,
            event_id=f"{proposal.proposal_id}:proposed:{proposal.patch_sha256}",
        )
        self._apply_proposal(event)
        return True

    def record_validation(
        self,
        validation: SandboxValidation,
        *,
        role: AuthorityRole = AuthorityRole.MAINTENANCE_AI,
    ) -> bool:
        self.policy.require(role, AuthorityAction.VALIDATE_CODE_CHANGE)
        proposal = self.get(validation.proposal_id)
        _assert_validation_binding(proposal, validation)
        existing = self._validations.get(proposal.proposal_id)
        if existing is not None:
            if existing != validation:
                raise ChangeControlError("proposal already has a different validation")
            return False
        event = self._wal.append(
            event_type=_VALIDATION_EVENT,
            payload={
                "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                "validation": validation.model_dump(mode="json"),
            },
            correlation_id=proposal.proposal_id,
            event_id=f"{proposal.proposal_id}:validated:{validation.validation_id}",
        )
        self._apply_validation(event)
        return True

    def approve(
        self,
        proposal_id: str,
        *,
        role: AuthorityRole,
        owner_id: str,
        high_risk_acknowledged: bool = False,
    ) -> OwnerApprovalReceipt:
        self.policy.require(role, AuthorityAction.APPROVE_CODE_CHANGE)
        proposal = self.get(proposal_id)
        validation = self._validations.get(proposal_id)
        if validation is None or not validation.passed:
            raise ChangeControlError("owner cannot approve before passing sandbox validation")
        if proposal.risk == ChangeRisk.FINANCIAL_CORE and not high_risk_acknowledged:
            raise ChangeControlError("financial-core change requires explicit high-risk acknowledgement")
        existing = self._approvals.get(proposal_id)
        if existing is not None:
            if existing.owner_id != owner_id:
                raise ChangeControlError("proposal approval is already bound to another owner")
            return existing
        receipt = OwnerApprovalReceipt(
            proposal_id=proposal_id,
            validation_id=validation.validation_id,
            patch_sha256=proposal.patch_sha256,
            base_commit=proposal.base_commit,
            owner_id=owner_id,
            high_risk_acknowledged=high_risk_acknowledged,
        )
        event = self._wal.append(
            event_type=_APPROVAL_EVENT,
            payload={
                "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                "approval": receipt.model_dump(mode="json"),
            },
            correlation_id=proposal_id,
            event_id=f"{proposal_id}:approved:{receipt.approval_id}",
        )
        self._apply_approval(event)
        return receipt

    def record_application(
        self,
        receipt: AppliedChangeReceipt,
        *,
        role: AuthorityRole,
    ) -> bool:
        self.policy.require(role, AuthorityAction.APPLY_TO_DEVELOPMENT)
        proposal = self.get(receipt.proposal_id)
        approval = self._approvals.get(receipt.proposal_id)
        if approval is None:
            raise ChangeControlError("development apply requires owner approval")
        _assert_application_binding(proposal, approval, receipt)
        existing = self._applications.get(receipt.proposal_id)
        if existing is not None:
            if existing != receipt:
                raise ChangeControlError("proposal already has a different application receipt")
            return False
        event = self._wal.append(
            event_type=_APPLIED_EVENT,
            payload={
                "registry_schema_version": _REGISTRY_SCHEMA_VERSION,
                "application": receipt.model_dump(mode="json"),
            },
            correlation_id=proposal.proposal_id,
            event_id=f"{proposal.proposal_id}:applied:{receipt.application_id}",
        )
        self._apply_application(event)
        return True

    def mark_pr_ready(self, proposal_id: str, *, role: AuthorityRole) -> bool:
        self.policy.require(role, AuthorityAction.OPEN_PULL_REQUEST)
        if proposal_id not in self._applications:
            raise ChangeControlError("PR readiness requires a recorded development application")
        if proposal_id in self._pr_ready:
            return False
        event = self._wal.append(
            event_type=_PR_READY_EVENT,
            payload={"registry_schema_version": _REGISTRY_SCHEMA_VERSION},
            correlation_id=proposal_id,
            event_id=f"{proposal_id}:pr-ready",
        )
        self._apply_pr_ready(event)
        return True

    def get(self, proposal_id: str) -> CodeChangeProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"unknown maintenance proposal: {proposal_id}") from exc

    def stage(self, proposal_id: str) -> ChangeStage:
        self.get(proposal_id)
        if proposal_id in self._pr_ready:
            return ChangeStage.PR_READY
        if proposal_id in self._applications:
            return ChangeStage.APPLIED_TO_DEVELOPMENT
        if proposal_id in self._approvals:
            return ChangeStage.OWNER_APPROVED
        validation = self._validations.get(proposal_id)
        if validation is not None and validation.passed:
            return ChangeStage.SANDBOX_VALIDATED
        return ChangeStage.PROPOSED

    def approval(self, proposal_id: str) -> OwnerApprovalReceipt | None:
        return self._approvals.get(proposal_id)

    def validation(self, proposal_id: str) -> SandboxValidation | None:
        return self._validations.get(proposal_id)

    def _initialize_or_replay(self) -> None:
        events = self._wal.read_all()
        if not events:
            self._wal.append(
                event_type=_HEADER_EVENT,
                payload={"registry_schema_version": _REGISTRY_SCHEMA_VERSION},
                correlation_id="maintenance-change-registry",
                event_id="maintenance-change-registry:initialized:v1",
            )
            return
        header = events[0]
        self._validate_schema(header)
        if (
            header.event_type != _HEADER_EVENT
            or header.event_id != "maintenance-change-registry:initialized:v1"
            or header.correlation_id != "maintenance-change-registry"
        ):
            raise ChangeControlError("maintenance registry is missing its header")
        for event in events[1:]:
            self._validate_schema(event)
            if event.event_type == _PROPOSAL_EVENT:
                self._apply_proposal(event)
            elif event.event_type == _VALIDATION_EVENT:
                self._apply_validation(event)
            elif event.event_type == _APPROVAL_EVENT:
                self._apply_approval(event)
            elif event.event_type == _APPLIED_EVENT:
                self._apply_application(event)
            elif event.event_type == _PR_READY_EVENT:
                self._apply_pr_ready(event)
            else:
                raise ChangeControlError(f"unknown maintenance registry event: {event.event_type}")
            self.recovered_events += 1

    @staticmethod
    def _validate_schema(event: WalEvent) -> None:
        if event.payload.get("registry_schema_version") != _REGISTRY_SCHEMA_VERSION:
            raise ChangeControlError("unsupported maintenance registry schema")

    def _apply_proposal(self, event: WalEvent) -> None:
        try:
            proposal = CodeChangeProposal.model_validate(event.payload["proposal"])
            validate_code_change_proposal(proposal)
        except Exception as exc:
            raise ChangeControlError(f"invalid proposal event: {event.event_id}") from exc
        if event.correlation_id != proposal.proposal_id:
            raise ChangeControlError("proposal correlation mismatch")
        expected_id = f"{proposal.proposal_id}:proposed:{proposal.patch_sha256}"
        if event.event_id != expected_id or proposal.proposal_id in self._proposals:
            raise ChangeControlError("proposal event identity mismatch or duplicate")
        self._proposals[proposal.proposal_id] = proposal

    def _apply_validation(self, event: WalEvent) -> None:
        try:
            validation = SandboxValidation.model_validate(event.payload["validation"])
            proposal = self.get(validation.proposal_id)
            _assert_validation_binding(proposal, validation)
        except Exception as exc:
            raise ChangeControlError(f"invalid validation event: {event.event_id}") from exc
        if event.correlation_id != proposal.proposal_id:
            raise ChangeControlError("validation correlation mismatch")
        expected_id = f"{proposal.proposal_id}:validated:{validation.validation_id}"
        if event.event_id != expected_id or proposal.proposal_id in self._validations:
            raise ChangeControlError("validation event identity mismatch or duplicate")
        self._validations[proposal.proposal_id] = validation

    def _apply_approval(self, event: WalEvent) -> None:
        try:
            approval = OwnerApprovalReceipt.model_validate(event.payload["approval"])
            proposal = self.get(approval.proposal_id)
            validation = self._validations[approval.proposal_id]
        except Exception as exc:
            raise ChangeControlError(f"invalid approval event: {event.event_id}") from exc
        if not validation.passed:
            raise ChangeControlError("journal approval references failed validation")
        if (
            approval.validation_id != validation.validation_id
            or approval.patch_sha256 != proposal.patch_sha256
            or approval.base_commit != proposal.base_commit
        ):
            raise ChangeControlError("approval binding mismatch")
        if proposal.risk == ChangeRisk.FINANCIAL_CORE and not approval.high_risk_acknowledged:
            raise ChangeControlError("journal financial-core approval lacks acknowledgement")
        expected_id = f"{proposal.proposal_id}:approved:{approval.approval_id}"
        if (
            event.event_id != expected_id
            or event.correlation_id != proposal.proposal_id
            or proposal.proposal_id in self._approvals
        ):
            raise ChangeControlError("approval event identity mismatch or duplicate")
        self._approvals[proposal.proposal_id] = approval

    def _apply_application(self, event: WalEvent) -> None:
        try:
            receipt = AppliedChangeReceipt.model_validate(event.payload["application"])
            proposal = self.get(receipt.proposal_id)
            approval = self._approvals[receipt.proposal_id]
            _assert_application_binding(proposal, approval, receipt)
        except Exception as exc:
            raise ChangeControlError(f"invalid application event: {event.event_id}") from exc
        expected_id = f"{proposal.proposal_id}:applied:{receipt.application_id}"
        if (
            event.event_id != expected_id
            or event.correlation_id != proposal.proposal_id
            or proposal.proposal_id in self._applications
        ):
            raise ChangeControlError("application event identity mismatch or duplicate")
        self._applications[proposal.proposal_id] = receipt

    def _apply_pr_ready(self, event: WalEvent) -> None:
        proposal_id = event.correlation_id
        if proposal_id not in self._applications:
            raise ChangeControlError("PR-ready event precedes development application")
        if event.event_id != f"{proposal_id}:pr-ready" or proposal_id in self._pr_ready:
            raise ChangeControlError("PR-ready event identity mismatch or duplicate")
        self._pr_ready.add(proposal_id)


class SandboxPatchExecutor:
    """Apply an AI diff only inside a credential-free tracked-file copy and test it."""

    def __init__(
        self,
        *,
        checks: tuple[tuple[str, ...], ...] | None = None,
        timeout_seconds: float = 600.0,
        policy: DevelopmentAuthorityPolicy | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("sandbox timeout must be positive")
        self.checks = checks or (
            (sys.executable, "-m", "pytest", "-q"),
            (sys.executable, "-m", "ruff", "check", "."),
            (sys.executable, "-m", "compileall", "-q", "aura"),
        )
        if not self.checks or any(not command for command in self.checks):
            raise ValueError("sandbox requires at least one non-empty allowlisted check")
        self.timeout_seconds = timeout_seconds
        self.policy = policy or DevelopmentAuthorityPolicy()

    def validate(
        self,
        proposal: CodeChangeProposal,
        *,
        repository_root: Path,
        role: AuthorityRole = AuthorityRole.MAINTENANCE_AI,
    ) -> SandboxValidation:
        self.policy.require(role, AuthorityAction.VALIDATE_CODE_CHANGE)
        self.policy.require(role, AuthorityAction.RUN_ALLOWLISTED_TESTS)
        changed_files = validate_code_change_proposal(proposal)
        root = repository_root.resolve()
        _assert_git_commit(root, proposal.base_commit)
        checks: list[SandboxCheck] = []
        with tempfile.TemporaryDirectory(prefix="aura-maintenance-sandbox-") as temporary:
            sandbox = Path(temporary)
            _materialize_tracked_tree(root, proposal.base_commit, sandbox)
            environment = _sandbox_environment(sandbox)
            patch_check = _run_check(
                ("git", "apply", "--check", "--whitespace=error-all", "-"),
                cwd=sandbox,
                timeout_seconds=self.timeout_seconds,
                environment=environment,
                stdin=proposal.unified_diff,
            )
            checks.append(patch_check)
            if patch_check.passed:
                applied = subprocess.run(
                    ("git", "apply", "--whitespace=error-all", "-"),
                    cwd=sandbox,
                    input=proposal.unified_diff,
                    text=True,
                    capture_output=True,
                    env=environment,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                if applied.returncode != 0:
                    checks.append(
                        _completed_process_check(
                            ("git", "apply", "--whitespace=error-all", "-"),
                            applied,
                            duration_ms=0,
                        )
                    )
                else:
                    for command in self.checks:
                        check = _run_check(
                            command,
                            cwd=sandbox,
                            timeout_seconds=self.timeout_seconds,
                            environment=environment,
                        )
                        checks.append(check)
                        if not check.passed:
                            break
        return SandboxValidation(
            proposal_id=proposal.proposal_id,
            patch_sha256=proposal.patch_sha256,
            base_commit=proposal.base_commit,
            changed_files=changed_files,
            checks=tuple(checks),
            passed=bool(checks) and all(check.passed for check in checks),
        )

    def apply_to_development(
        self,
        proposal: CodeChangeProposal,
        approval: OwnerApprovalReceipt,
        *,
        repository_root: Path,
        role: AuthorityRole,
    ) -> AppliedChangeReceipt:
        self.policy.require(role, AuthorityAction.APPLY_TO_DEVELOPMENT)
        validate_code_change_proposal(proposal)
        if (
            approval.proposal_id != proposal.proposal_id
            or approval.patch_sha256 != proposal.patch_sha256
            or approval.base_commit != proposal.base_commit
        ):
            raise ChangeControlError("owner approval does not bind this exact patch")
        root = repository_root.resolve()
        _assert_git_commit(root, proposal.base_commit)
        status = _git(root, "status", "--porcelain", "--untracked-files=all")
        if status.stdout.strip():
            raise ChangeControlError("development worktree must be clean before patch application")
        check = subprocess.run(
            ("git", "apply", "--check", "--whitespace=error-all", "-"),
            cwd=root,
            input=proposal.unified_diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if check.returncode != 0:
            raise ChangeControlError("approved patch no longer applies cleanly")
        applied = subprocess.run(
            ("git", "apply", "--whitespace=error-all", "-"),
            cwd=root,
            input=proposal.unified_diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if applied.returncode != 0:
            raise ChangeControlError("approved patch application failed")
        resulting_diff = _git(root, "diff", "--binary", "--no-ext-diff").stdout
        return AppliedChangeReceipt(
            proposal_id=proposal.proposal_id,
            approval_id=approval.approval_id,
            patch_sha256=proposal.patch_sha256,
            base_commit=proposal.base_commit,
            resulting_diff_sha256=hashlib.sha256(resulting_diff.encode()).hexdigest(),
            applied_by_role=role.value,
        )

    def rollback_development(
        self,
        proposal: CodeChangeProposal,
        application: AppliedChangeReceipt,
        *,
        repository_root: Path,
        role: AuthorityRole,
    ) -> None:
        self.policy.require(role, AuthorityAction.ROLLBACK_DEVELOPMENT)
        if (
            application.proposal_id != proposal.proposal_id
            or application.patch_sha256 != proposal.patch_sha256
        ):
            raise ChangeControlError("rollback receipt does not bind this exact patch")
        root = repository_root.resolve()
        current_diff = _git(root, "diff", "--binary", "--no-ext-diff").stdout
        current_hash = hashlib.sha256(current_diff.encode()).hexdigest()
        if current_hash != application.resulting_diff_sha256:
            raise ChangeControlError("development diff changed after application; rollback refused")
        checked = subprocess.run(
            ("git", "apply", "--reverse", "--check", "-"),
            cwd=root,
            input=proposal.unified_diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if checked.returncode != 0:
            raise ChangeControlError("approved patch cannot be safely reversed")
        rolled_back = subprocess.run(
            ("git", "apply", "--reverse", "-"),
            cwd=root,
            input=proposal.unified_diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if rolled_back.returncode != 0:
            raise ChangeControlError("development rollback failed")


def _safe_patch_path(raw_path: str) -> str:
    path = PurePosixPath(raw_path.replace("\\", "/"))
    normalized = path.as_posix()
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or normalized == "."
        or path.name.startswith(".env")
    ):
        raise ChangeControlError(f"unsafe patch path: {raw_path!r}")
    return normalized


def _path_is_immutable(path: str) -> bool:
    return path in _IMMUTABLE_PATHS or path.startswith(_IMMUTABLE_PREFIXES)


def _assert_validation_binding(
    proposal: CodeChangeProposal,
    validation: SandboxValidation,
) -> None:
    if (
        validation.patch_sha256 != proposal.patch_sha256
        or validation.base_commit != proposal.base_commit
        or validation.changed_files != extract_changed_files(proposal.unified_diff)
    ):
        raise ChangeControlError("sandbox validation does not bind this exact proposal")


def _assert_application_binding(
    proposal: CodeChangeProposal,
    approval: OwnerApprovalReceipt,
    receipt: AppliedChangeReceipt,
) -> None:
    if (
        receipt.approval_id != approval.approval_id
        or receipt.patch_sha256 != proposal.patch_sha256
        or receipt.base_commit != proposal.base_commit
    ):
        raise ChangeControlError("development application does not bind approved patch")


def _assert_git_commit(root: Path, expected_commit: str) -> None:
    actual = _git(root, "rev-parse", "HEAD").stdout.strip()
    if actual != expected_commit:
        raise ChangeControlError(
            f"repository HEAD {actual or '<missing>'} does not match proposal base"
        )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ChangeControlError(f"git {' '.join(args)} failed")
    return result


def _materialize_tracked_tree(root: Path, commit: str, target: Path) -> None:
    listing = subprocess.run(
        ("git", "ls-tree", "-r", "-z", "--name-only", commit),
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listing.returncode != 0:
        raise ChangeControlError("unable to enumerate tracked files for sandbox")
    for raw in listing.stdout.split(b"\x00"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        safe = _safe_patch_path(relative)
        destination = target / safe
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = subprocess.run(
            ("git", "show", f"{commit}:{safe}"),
            cwd=root,
            capture_output=True,
            check=False,
        )
        if content.returncode != 0:
            raise ChangeControlError(f"unable to materialize tracked file: {safe}")
        destination.write_bytes(content.stdout)


def _sandbox_environment(sandbox: Path) -> dict[str, str]:
    home = sandbox / ".sandbox-home"
    home.mkdir()
    allowed_names = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "PATHEXT")
    environment = {name: os.environ[name] for name in allowed_names if name in os.environ}
    environment.update(
        {
            "HOME": str(home),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "AURA_MAINTENANCE_SANDBOX": "1",
            "AURA_LIVE_TRADING": "0",
            "AURA_NETWORK_DISABLED": "1",
        }
    )
    return environment


def _run_check(
    command: tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: float,
    environment: dict[str, str],
    stdin: str | None = None,
) -> SandboxCheck:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=stdin,
            text=True,
            capture_output=True,
            env=environment,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        combined = f"{exc.stdout or ''}\n{exc.stderr or ''}\nTIMEOUT"
        duration = int((time.monotonic() - started) * 1000)
        return SandboxCheck(
            command=command,
            exit_code=124,
            duration_ms=duration,
            output_sha256=hashlib.sha256(combined.encode()).hexdigest(),
            output_tail=_safe_output_tail(combined),
        )
    duration = int((time.monotonic() - started) * 1000)
    return _completed_process_check(command, completed, duration_ms=duration)


def _completed_process_check(
    command: tuple[str, ...],
    completed: subprocess.CompletedProcess[str],
    *,
    duration_ms: int,
) -> SandboxCheck:
    combined = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
    return SandboxCheck(
        command=command,
        exit_code=completed.returncode,
        duration_ms=duration_ms,
        output_sha256=hashlib.sha256(combined.encode()).hexdigest(),
        output_tail=_safe_output_tail(combined),
    )


def _safe_output_tail(value: str) -> str:
    redacted = _SECRET_REDACTION.sub("[REDACTED]", value)
    return redacted[-2000:]
