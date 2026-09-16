from pathlib import Path

from aura.webapp import server


def test_pwa_static_assets_exist() -> None:
    expected = {
        "index.html",
        "manifest.webmanifest",
        "sw.js",
        "icon.svg",
    }
    present = {path.name for path in server.STATIC_DIR.iterdir() if path.is_file()}
    assert expected.issubset(present)


def test_dashboard_keeps_demo_only_safety_copy() -> None:
    html = (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "DEMO ONLY" in html
    assert "Real-money disabled" in html
    assert "/api/start" in html
    assert "/api/kill" in html


def test_controller_status_is_safe_without_runtime_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "KILL_LOCK_PATH", tmp_path / "kill_switch.json")
    monkeypatch.setattr(server, "LOG_PATH", tmp_path / "daemon.log")
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    payload = controller.status()
    assert payload["ok"] is True
    assert payload["runtime_running"] is False
    assert payload["safety"]["demo_only"] is True
    assert payload["safety"]["real_money_enabled"] is False
    assert payload["safety"]["credentials_accepted_by_web_ui"] is False
