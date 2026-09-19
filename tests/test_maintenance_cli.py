from __future__ import annotations

import json
import os
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from aura.ai.ollama_structured import OllamaStructuredClient
from aura.maintenance.cli import _maintenance_client, build_parser, main


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


def test_free_preset_selects_local_maintenance_ai_without_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AURA_FREE_AI_PRESET", "balanced5")
    monkeypatch.setenv("AURA_OLLAMA_MODELS", "")
    monkeypatch.delenv("AURA_MAINTENANCE_AI_PROVIDER", raising=False)
    monkeypatch.delenv("AURA_MAINTENANCE_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = _maintenance_client(
        Namespace(provider="auto", model=None),
        tmp_path,
    )
    assert isinstance(client, OllamaStructuredClient)
    assert client.model_id == "qwen3.5:4b"
    assert client.keep_alive == 0
    assert client.provider_id == "ollama"


def test_safe_local_env_file_can_select_free_maintenance_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("AURA_FREE_AI_PRESET", raising=False)
    monkeypatch.delenv("AURA_MAINTENANCE_AI_PROVIDER", raising=False)
    monkeypatch.delenv("AURA_MAINTENANCE_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env.local").write_text(
        "AURA_FREE_AI_PRESET=balanced5\n"
        "AURA_MAINTENANCE_AI_PROVIDER=ollama\n"
        "AURA_MAINTENANCE_OLLAMA_MODEL=gemma3:4b\n"
        "UNTRUSTED_SETTING=must-not-load\n",
        encoding="utf-8",
    )

    client = _maintenance_client(
        Namespace(provider="auto", model=None),
        tmp_path,
    )
    os.environ.pop("AURA_FREE_AI_PRESET", None)
    os.environ.pop("AURA_MAINTENANCE_AI_PROVIDER", None)
    os.environ.pop("AURA_MAINTENANCE_OLLAMA_MODEL", None)

    assert isinstance(client, OllamaStructuredClient)
    assert client.model_id == "gemma3:4b"
    assert "UNTRUSTED_SETTING" not in os.environ
