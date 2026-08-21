from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from aura.maintenance.cli import build_parser, main


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def test_policy_command_exposes_hard_denials(capsys) -> None:
    assert main(["policy"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fund_operations_available"] is False
    owner_withdrawal = next(
        item
        for item in payload["authority"]
        if item["role"] == "owner" and item["action"] == "withdraw_funds"
    )
    assert owner_withdrawal["allowed"] is False


def test_probe_runs_without_credentials_or_broker_connection(tmp_path: Path, capsys) -> None:
    root = tmp_path / "repo"
    (root / "aura").mkdir(parents=True)
    (root / "aura" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "AURA Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "add", "aura/sample.py")
    _git(root, "commit", "-qm", "baseline")

    assert main(["probe", "--repository", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["credentials_used"] is False
    assert payload["broker_connection_used"] is False
    assert payload["fund_operations_available"] is False


def test_correction_cli_requires_separate_exact_owner_approval(tmp_path: Path, capsys) -> None:
    journal = tmp_path / "corrections.jsonl"
    result = main(
        [
            "correction-request",
            "--journal",
            str(journal),
            "--mode",
            "PAPER",
            "--kind",
            "PNL_ADJUSTMENT",
            "--pnl-delta=-2.50",
            "--reason",
            "correct paper reporting discrepancy",
            "--requester",
            "owner",
        ]
    )
    requested = json.loads(capsys.readouterr().out)
    assert result == 0
    assert requested["approved"] is False
    assert requested["source_ledger_mutated"] is False

    assert (
        main(
            [
                "correction-approve",
                "--journal",
                str(journal),
                "--correction-id",
                requested["correction_id"],
                "--expected-content-sha256",
                requested["content_sha256"],
                "--owner-id",
                "owner",
            ]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    assert approved["fund_movement_authority"] is False
    assert approved["historical_rewrite_authority"] is False

    assert (
        main(
            [
                "correction-view",
                "--journal",
                str(journal),
                "--base-realized-pnl",
                "100",
                "--base-fees-paid",
                "5",
            ]
        )
        == 0
    )
    view = json.loads(capsys.readouterr().out)["view"]
    assert view["corrected_realized_pnl"] == "97.50"
    assert view["source_ledger_mutated"] is False
    assert view["fund_movement_performed"] is False


def test_cli_has_no_fund_operation_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["withdraw-funds"])
