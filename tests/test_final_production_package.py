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
        "scripts/aura_env.ps1",
        "scripts/final_setup_aura.ps1",
        "scripts/start_aura_production.ps1",
        "scripts/stop_aura_production.ps1",
    )
    for relative in expected:
        assert (root / relative).exists(), relative

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


def test_private_env_file_is_gitignored() -> None:
    root = Path(__file__).resolve().parents[1]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".env.local" in ignore
