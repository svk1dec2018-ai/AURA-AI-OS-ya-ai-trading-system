from pathlib import Path

from aura.webapp import server


def test_pwa_static_assets_exist() -> None:
    expected = {
        "index.html",
        "app.css",
        "app.js",
        "manifest.webmanifest",
        "sw.js",
        "icon.svg",
    }
    present = {path.name for path in server.STATIC_DIR.iterdir() if path.is_file()}
    assert expected.issubset(present)


def test_dashboard_keeps_safety_copy_and_new_owner_surfaces() -> None:
    html = (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "DEMO / RESEARCH" in html
    assert "Fund transfer" in html
    assert "Withdrawal" in html
    assert "AURA A→Z Capability Matrix" in html
    assert "ONE-CLICK ALGO STUDIO" in html
    assert "/app.css" in html
    assert "/app.js" in html


def test_controller_status_is_safe_without_runtime_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "KILL_LOCK_PATH", tmp_path / "kill_switch.json")
    monkeypatch.setattr(server, "LOG_PATH", tmp_path / "daemon.log")
    monkeypatch.setattr(server, "ALGO_DIR", tmp_path / "algo_candidates")
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    payload = controller.status()
    assert payload["ok"] is True
    assert payload["runtime_running"] is False
    assert payload["safety"]["demo_only"] is True
    assert payload["safety"]["real_money_enabled"] is False
    assert payload["safety"]["credentials_accepted_by_web_ui"] is False
    assert payload["safety"]["fund_transfers_enabled"] is False
    assert payload["safety"]["withdrawals_enabled"] is False
    assert payload["safety"]["risk_engine_bypass_allowed"] is False


def test_capability_catalog_is_truthful_and_has_blocked_money_actions() -> None:
    catalog = server.capability_catalog()
    by_id = {item["id"]: item for item in catalog["items"]}
    assert catalog["release_boundary"].startswith("PAPER_DEMO_RESEARCH")
    assert by_id["algo_studio"]["status"] == "ui_connected"
    assert by_id["live_money"]["status"] == "external_gate"
    assert by_id["fund_transfer"]["status"] == "blocked"
    assert by_id["withdrawal"]["status"] == "blocked"


def test_algo_builder_creates_research_only_compiled_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "KILL_LOCK_PATH", tmp_path / "kill_switch.json")
    monkeypatch.setattr(server, "LOG_PATH", tmp_path / "daemon.log")
    monkeypatch.setattr(server, "ALGO_DIR", tmp_path / "algo_candidates")
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")

    result = controller.build_algo_candidate(
        {
            "name": "Owner Trend Test",
            "thesis": "Test whether trend plus momentum survives realistic validation.",
            "markets": ["XAUUSD", "BTCUSD"],
            "timeframes": ["5m", "15m"],
            "entries": ["ema_trend", "macd_momentum"],
            "confirmations": ["rsi_state", "regime"],
            "exits": ["atr_stop", "risk_reward_target"],
        }
    )

    assert result["ok"] is True
    assert result["stage"] == "research"
    assert result["research_only"] is True
    assert result["live_approved"] is False
    assert result["algorithm"]["compilable"] is True
    assert result["validation"]["next_required"] == "causal_backtest"
    assert result["validation"]["can_auto_deploy_live"] is False
    assert result["safety"]["broker_authority"] is False
    assert result["safety"]["fund_transfer_authority"] is False
    assert result["safety"]["withdrawal_authority"] is False
    assert len(controller.algo_candidates()) == 1


def test_algo_builder_rejects_non_allowlisted_component(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "ALGO_DIR", tmp_path / "algo_candidates")
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    try:
        controller.build_algo_candidate(
            {
                "name": "Unsafe",
                "thesis": "Reject arbitrary component.",
                "markets": ["XAUUSD"],
                "timeframes": ["5m"],
                "entries": ["arbitrary_python"],
                "confirmations": [],
                "exits": ["atr_stop"],
            }
        )
    except ValueError as exc:
        assert "unsupported entries primitive" in str(exc)
    else:
        raise AssertionError("non-allowlisted component should be rejected")
