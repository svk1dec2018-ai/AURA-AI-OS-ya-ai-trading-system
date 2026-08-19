from __future__ import annotations

from pathlib import Path, PurePosixPath

from aura.ops.repository_audit import (
    _is_audit_excluded,
    build_repository_audit,
    check_repository_audit,
)


def test_repository_audit_classifies_every_module_and_asset() -> None:
    root = Path(__file__).resolve().parents[1]
    audit, tests, _ = build_repository_audit(root)

    assert audit["gate"]["decision"] == "PASS"
    assert all(audit["gate"]["criteria"].values())
    assert audit["unclassified_modules"] == []
    assert audit["unknown_assets"] == []
    assert audit["broken_components"] == {
        "parse_errors": [],
        "unresolved_internal_imports": [],
    }
    assert tests["summary"]["test_modules"] > 0
    assert tests["summary"]["static_test_functions"] > 0


def test_audit_includes_git_tracked_runtime_despite_generic_ignore_rule() -> None:
    root = Path(__file__).resolve().parents[1]
    audit, _, _ = build_repository_audit(root)
    modules = {item["path"]: item for item in audit["modules"]}

    assert modules["aura/runtime/paper.py"]["component"] == "runtime"
    assert modules["aura/runtime/paper.py"]["primary_phase"] == 12


def test_audit_exposes_stub_candidates_without_calling_them_completed() -> None:
    root = Path(__file__).resolve().parents[1]
    audit, _, _ = build_repository_audit(root)
    findings = audit["stub_and_incomplete_candidates"]

    assert findings
    assert {item["classification"] for item in findings} <= {
        "intentional",
        "review-required",
    }
    assert any(item["classification"] == "review-required" for item in findings)


def test_generated_phase_zero_artifacts_are_current() -> None:
    root = Path(__file__).resolve().parents[1]
    assert check_repository_audit(root) == ()


def test_packaging_outputs_are_excluded_but_source_is_not() -> None:
    assert _is_audit_excluded(PurePosixPath("aura_ai_os.egg-info/PKG-INFO")) is True
    assert _is_audit_excluded(PurePosixPath("build/lib/aura/ops/preflight.py")) is True
    assert _is_audit_excluded(PurePosixPath("dist/aura_ai_os.whl")) is True
    assert _is_audit_excluded(PurePosixPath("aura/ops/preflight.py")) is False
