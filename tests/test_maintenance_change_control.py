from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aura.maintenance.authority import AuthorityDeniedError, AuthorityRole
from aura.maintenance.change_control import (
    ChangeControlError,
    DevelopmentChangeRegistry,
    SandboxPatchExecutor,
    validate_code_change_proposal,
)
from aura.maintenance.models import ChangeRisk, ChangeStage, CodeChangeProposal


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    (root / "aura" / "risk").mkdir(parents=True)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "aura" / "risk" / "rules.py").write_text(
        "LIMIT = 3\n",
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "AURA Test")
    _git(root, "config", "user.email", "aura-test@example.invalid")
    _git(root, "add", "app.py", "aura/risk/rules.py")
    _git(root, "commit", "-qm", "baseline")
    return root, _git(root, "rev-parse", "HEAD")


def _proposal(base_commit: str, *, financial: bool = False) -> CodeChangeProposal:
    if financial:
        path = "aura/risk/rules.py"
        old = "LIMIT = 3"
        new = "LIMIT = 4"
        risk = ChangeRisk.FINANCIAL_CORE
    else:
        path = "app.py"
        old = "VALUE = 1"
        new = "VALUE = 2"
        risk = ChangeRisk.STANDARD
    diff = (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )
    return CodeChangeProposal(
        proposal_id=f"change:{'financial' if financial else 'standard'}",
        observation_id="incident:test",
        provider_id="openai",
        model_id="gpt-5.4-mini",
        provider_response_id="resp_test",
        base_commit=base_commit,
        diagnosis="a deterministic regression requires a bounded repair",
        summary="change the tested constant",
        changed_files=(path,),
        unified_diff=diff,
        validation_rationale=("compile the patched source",),
        rollback_plan="reverse the exact patch",
        residual_risks=(),
        risk=risk,
        created_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
    )


def _executor() -> SandboxPatchExecutor:
    return SandboxPatchExecutor(
        checks=((sys.executable, "-m", "compileall", "-q", "."),),
        timeout_seconds=30,
    )


def test_patch_moves_through_sandbox_owner_and_restart_safe_registry(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path)
    proposal = _proposal(commit)
    registry = DevelopmentChangeRegistry(tmp_path / "change-registry.jsonl")
    executor = _executor()

    assert registry.submit(proposal, role=AuthorityRole.MAINTENANCE_AI)
    validation = executor.validate(proposal, repository_root=root)
    assert validation.passed
    assert registry.record_validation(validation)
    assert registry.stage(proposal.proposal_id) == ChangeStage.SANDBOX_VALIDATED
    with pytest.raises(AuthorityDeniedError):
        registry.approve(
            proposal.proposal_id,
            role=AuthorityRole.MAINTENANCE_AI,
            owner_id="owner",
        )

    approval = registry.approve(
        proposal.proposal_id,
        role=AuthorityRole.OWNER,
        owner_id="owner",
    )
    application = executor.apply_to_development(
        proposal,
        approval,
        repository_root=root,
        role=AuthorityRole.DEVELOPER,
    )
    assert (root / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert not application.committed
    assert not application.pushed
    assert not application.deployed
    registry.record_application(application, role=AuthorityRole.DEVELOPER)
    registry.mark_pr_ready(proposal.proposal_id, role=AuthorityRole.DEVELOPER)

    recovered = DevelopmentChangeRegistry(tmp_path / "change-registry.jsonl")
    assert recovered.recovered_events == 5
    assert recovered.stage(proposal.proposal_id) == ChangeStage.PR_READY


def test_applied_development_patch_can_be_exactly_rolled_back(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path)
    proposal = _proposal(commit)
    registry = DevelopmentChangeRegistry(tmp_path / "registry.jsonl")
    executor = _executor()
    registry.submit(proposal)
    validation = executor.validate(proposal, repository_root=root)
    registry.record_validation(validation)
    approval = registry.approve(
        proposal.proposal_id,
        role=AuthorityRole.OWNER,
        owner_id="owner",
    )
    application = executor.apply_to_development(
        proposal,
        approval,
        repository_root=root,
        role=AuthorityRole.DEVELOPER,
    )

    executor.rollback_development(
        proposal,
        application,
        repository_root=root,
        role=AuthorityRole.DEVELOPER,
    )
    assert (root / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _git(root, "status", "--porcelain") == ""


def test_financial_core_patch_needs_explicit_owner_high_risk_ack(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path)
    proposal = _proposal(commit, financial=True)
    registry = DevelopmentChangeRegistry(tmp_path / "registry.jsonl")
    registry.submit(proposal)
    validation = _executor().validate(proposal, repository_root=root)
    registry.record_validation(validation)

    with pytest.raises(ChangeControlError, match="high-risk"):
        registry.approve(
            proposal.proposal_id,
            role=AuthorityRole.OWNER,
            owner_id="owner",
        )
    approval = registry.approve(
        proposal.proposal_id,
        role=AuthorityRole.OWNER,
        owner_id="owner",
        high_risk_acknowledged=True,
    )
    assert approval.high_risk_acknowledged


def test_fund_capability_and_guard_self_modification_patches_are_rejected() -> None:
    fund_patch = CodeChangeProposal(
        proposal_id="change:fund",
        observation_id="incident:test",
        provider_id="openai",
        model_id="gpt-5.4-mini",
        provider_response_id="resp",
        base_commit="a" * 40,
        diagnosis="bad request",
        summary="forbidden fund method",
        changed_files=("app.py",),
        unified_diff=(
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
            "@@ -1 +1,2 @@\n VALUE = 1\n+def withdraw_funds(): pass\n"
        ),
        validation_rationale=("none",),
        rollback_plan="reverse",
        residual_risks=(),
        risk=ChangeRisk.STANDARD,
    )
    with pytest.raises(ChangeControlError, match="fund-operation"):
        validate_code_change_proposal(fund_patch)

    guard_patch = fund_patch.model_copy(
        update={
            "proposal_id": "change:guard",
            "changed_files": ("aura/maintenance/authority.py",),
            "unified_diff": (
                "diff --git a/aura/maintenance/authority.py "
                "b/aura/maintenance/authority.py\n"
                "--- a/aura/maintenance/authority.py\n"
                "+++ b/aura/maintenance/authority.py\n"
                "@@ -1 +1 @@\n-old = True\n+old = False\n"
            ),
        }
    )
    with pytest.raises(ChangeControlError, match="immutable path"):
        validate_code_change_proposal(guard_patch)
