from pathlib import Path

from aura.ops.final_doctor import build_report


def test_final_doctor_repository_profile_is_software_ready(monkeypatch) -> None:
    monkeypatch.delenv("AURA_LIVE_TRADING_ENABLED", raising=False)
    root = Path(__file__).resolve().parents[1]
    report = build_report(root, profile="repository")
    assert report.ready is True
    assert report.software_production_ready is True
    assert report.live_money_eligible is False
    checks = {item.check_id: item for item in report.checks}
    assert checks["governance-ledger"].passed is True
    assert checks["software-phases"].passed is True
    assert checks["live-money-default-lock"].passed is True
    assert checks["live-phases-11-15"].blocking is False


def test_final_doctor_fails_closed_if_live_ack_leaks_into_non_live(monkeypatch) -> None:
    monkeypatch.setenv(
        "AURA_LIVE_TRADING_ENABLED",
        "I_UNDERSTAND_AND_APPROVE_LIVE_RISK",
    )
    root = Path(__file__).resolve().parents[1]
    report = build_report(root, profile="repository")
    checks = {item.check_id: item for item in report.checks}
    assert checks["live-money-default-lock"].passed is False
    assert checks["live-money-default-lock"].blocking is True
    assert report.ready is False


def test_final_production_launchers_and_env_loader_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = (
        "FINAL_SETUP_AURA.cmd",
        "CONFIGURE_AURA.cmd",
        "START_AURA_PRODUCTION.cmd",
        "AURA_PRODUCTION_DOCTOR.cmd",
        "STOP_AURA_PRODUCTION.cmd",
        "INSTALL_FREE_UNLIMITED_AI.cmd",
        "scripts/aura_env.ps1",
        "scripts/sync_aura_env.ps1",
        "scripts/final_setup_aura.ps1",
        "scripts/start_aura_production.ps1",
        "scripts/stop_aura_production.ps1",
        "scripts/install_free_unlimited_ai.ps1",
    )
    for relative in expected:
        assert (root / relative).exists(), relative

    configure = (root / "CONFIGURE_AURA.cmd").read_text(encoding="utf-8")
    assert "sync_aura_env.ps1" in configure

    loader = (root / "scripts" / "aura_env.ps1").read_text(encoding="utf-8")
    assert "Invoke-Expression" not in loader
    assert "SetEnvironmentVariable" in loader

    start = (root / "scripts" / "start_aura_production.ps1").read_text(
        encoding="utf-8"
    )
    assert "start_aura_fleet.ps1" in start
    assert "start_aura2_dashboard.ps1" in start
    assert "--profile all-market" in start
    assert "I_UNDERSTAND_AND_APPROVE_LIVE_RISK" in start

    setup = (root / "scripts" / "final_setup_aura.ps1").read_text(
        encoding="utf-8"
    )
    assert "AURA_FREE_AI_PRESET" in setup
    assert "Running hermetic AURA test suite" in setup
    assert "aura.ops.repository_audit --check" in setup

    local_ai = (root / "scripts" / "install_free_unlimited_ai.ps1").read_text(
        encoding="utf-8"
    )
    assert "Ollama.Ollama" in local_ai
    assert "qwen3.5:4b" in local_ai
    assert "deepseek-r1:8b" in local_ai
    assert "AURA_FREE_AI_PRESET=balanced5" in local_ai


def test_private_env_file_is_gitignored() -> None:
    root = Path(__file__).resolve().parents[1]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".env.local" in ignore


def test_fresh_template_keeps_local_ai_off_until_installed() -> None:
    root = Path(__file__).resolve().parents[1]
    env = (root / ".env.example").read_text(encoding="utf-8")
    assert "AURA_FREE_AI_PRESET=off" in env


def test_free_cloud_env_defaults_are_safe_and_free_first() -> None:
    root = Path(__file__).resolve().parents[1]
    env = (root / ".env.example").read_text(encoding="utf-8")
    assert "NVIDIA_API_KEY=" in env
    assert "AURA_NVIDIA_MODELS=openai/gpt-oss-20b" in env
    assert "GROQ_API_KEY=" in env
    assert (
        "AURA_GROQ_MODELS=openai/gpt-oss-20b,openai/gpt-oss-120b,"
        "qwen/qwen3.8-27b"
    ) in env
    assert "OPENROUTER_API_KEY=" in env
    assert "AURA_OPENROUTER_MODELS=openrouter/free" in env
    assert "GEMINI_API_KEY=" in env
    assert "AURA_GEMINI_MODELS=gemini-3.8-flash" in env
