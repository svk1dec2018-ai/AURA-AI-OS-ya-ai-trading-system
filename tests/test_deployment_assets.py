from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_openai_secret_files_are_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert ".env.local" in gitignore
    assert ".env*" in dockerignore
    assert "OPENAI_API_KEY=" in example
    assert "AURA_FREE_AI_PRESET=balanced5" in example
    assert "AURA_OLLAMA_MODELS=" in example
    assert "AURA_OLLAMA_KEEP_ALIVE=0" in example
    assert "AURA_MAINTENANCE_AI_PROVIDER=ollama" in example
    assert "AURA_ANGEL_ONE_API_KEY=" in example
    assert "sk-" not in example


def test_compose_paper_service_is_fail_closed() -> None:
    compose = (ROOT / "compose.paper.yml").read_text(encoding="utf-8")
    assert "run_free_public_autonomy.py" in compose
    assert 'AURA_LIVE_TRADING_ENABLED: ""' in compose
    assert 'AURA_HUMAN_LIVE_APPROVAL_ID: ""' in compose
    assert "restart: unless-stopped" in compose
    assert "AURA_FREE_AI_PRESET" in compose
    assert "AURA_OLLAMA_KEEP_ALIVE" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose


def test_systemd_service_runs_preflight_before_paper_autonomy() -> None:
    unit = (ROOT / "deploy/systemd/aura-paper.service.in").read_text(encoding="utf-8")
    preflight = unit.index("ExecStartPre=")
    runtime = unit.index("ExecStart=")
    assert preflight < runtime
    assert "--mode paper --connector public" in unit
    assert "AURA_LIVE_TRADING_ENABLED=" in unit
    assert "AURA_HUMAN_LIVE_APPROVAL_ID=" in unit
    assert "NoNewPrivileges=true" in unit


def test_service_installers_do_not_enable_live_authority() -> None:
    linux = (ROOT / "scripts/install_aura_user_service.sh").read_text(encoding="utf-8")
    windows = (ROOT / "scripts/install_aura_windows_task.ps1").read_text(encoding="utf-8")
    assert "--mode paper" in linux
    assert "--mode paper" in windows
    assert "AURA_LIVE_TRADING_ENABLED" not in windows
    assert "AURA_HUMAN_LIVE_APPROVAL_ID" not in windows


def test_windows_launcher_uses_resource_safe_balanced_five_preset() -> None:
    launcher = (ROOT / "scripts/start_aura_ollama.ps1").read_text(encoding="utf-8")
    for model in (
        "qwen3.5:4b",
        "deepseek-r1:8b",
        "llama3.1:8b",
        "gemma3:4b",
        "phi4-mini:3.8b",
    ):
        assert model in launcher
    assert '$env:AURA_OLLAMA_MAX_CONCURRENCY = "1"' in launcher
    assert '$env:AURA_OLLAMA_KEEP_ALIVE = "0"' in launcher
    assert "$SkipModelPull" in launcher
    assert '$env:AURA_LIVE_TRADING_ENABLED = ""' in launcher
    assert '$env:AURA_HUMAN_LIVE_APPROVAL_ID = ""' in launcher
