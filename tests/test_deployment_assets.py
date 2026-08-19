from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_paper_service_is_fail_closed() -> None:
    compose = (ROOT / "compose.paper.yml").read_text(encoding="utf-8")
    assert "run_free_public_autonomy.py" in compose
    assert 'AURA_LIVE_TRADING_ENABLED: ""' in compose
    assert 'AURA_HUMAN_LIVE_APPROVAL_ID: ""' in compose
    assert "restart: unless-stopped" in compose
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
