import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from aura.webapp import server


def test_windows_stop_terminates_worker_tree(tmp_path: Path, monkeypatch) -> None:
    controller = server.AuraWebController(state_dir=tmp_path / "state")
    process = Mock(pid=123, returncode=0)
    process.poll.return_value = None
    controller._process = process
    run = Mock()
    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.subprocess, "run", run)
    assert controller.stop()["stopped"] is True
    assert run.call_args.args[0] == ["taskkill", "/PID", "123", "/T", "/F"]
    assert run.call_args.kwargs["check"] is True
    process.terminate.assert_not_called()
    process.wait.assert_called_once_with(timeout=10)


def test_windows_stop_does_not_claim_success_when_tree_stop_fails(tmp_path: Path, monkeypatch):
    controller = server.AuraWebController(state_dir=tmp_path / "state")
    process = Mock(pid=123)
    process.poll.return_value = None
    controller._process = process
    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.subprocess, "run", Mock(
        side_effect=server.subprocess.CalledProcessError(1, "taskkill")
    ))
    with pytest.raises(server.subprocess.CalledProcessError):
        controller.stop()


def test_pwa_static_assets_exist() -> None:
    expected = {
        "index.html",
        "styles.css",
        "app.js",
        "manifest.webmanifest",
        "sw.js",
        "icon.svg",
    }
    present = {path.name for path in server.STATIC_DIR.iterdir() if path.is_file()}
    assert expected.issubset(present)


def test_pwa_static_assets_are_included_in_distribution() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert "static/*" in package_data["aura.webapp"]


def test_javascript_and_css_require_revalidation(tmp_path: Path) -> None:
    handler_source = Path(server.__file__).read_text(encoding="utf-8")
    assert 'candidate.suffix in {".js", ".css"}' in handler_source


def test_dashboard_keeps_safety_copy_and_owner_surfaces() -> None:
    html = (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "DEMO ONLY" in html
    assert "Real-money disabled" in html
    assert "Fund transfer" in html
    assert "withdrawal" in html.lower()
    assert "Owner Control" in html
    assert "ONE-CLICK STRATEGY → ALGO" in html
    assert "/styles.css" in html
    assert "/app.js" in html
    assert "/api/start" in html
    assert "/api/kill" in html
    assert "chartForm" in html
    assert "backtestForm" in html
    assert "fake-line" not in html
    assert "simulated performance curve" in html


def test_dashboard_does_not_render_fabricated_agent_percentages() -> None:
    javascript = (server.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "72-i*5" not in javascript
    assert "implemented" in javascript
    assert "/api/chart" in javascript
    assert "/api/backtest/run" in javascript


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
    assert payload["safety"]["ai_direct_broker_authority"] is False


def test_capability_catalog_is_truthful_and_has_blocked_money_actions() -> None:
    catalog = server.capability_catalog()
    by_id = {item["id"]: item for item in catalog["items"]}
    assert catalog["release_boundary"].startswith("PAPER_DEMO_RESEARCH")
    assert by_id["algo_studio"]["status"] == "ui_connected"
    assert by_id["aura_chat"]["status"] == "ui_connected"
    assert by_id["owner_authority"]["status"] == "ui_connected"
    assert by_id["live_money"]["status"] == "external_gate"
    assert by_id["fund_transfer"]["status"] == "blocked"
    assert by_id["withdrawal"]["status"] == "blocked"
    assert by_id["wake_word"]["status"] == "pending"


def test_workspace_exposes_runtime_capabilities_and_algo_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(server, "KILL_LOCK_PATH", tmp_path / "kill_switch.json")
    monkeypatch.setattr(server, "LOG_PATH", tmp_path / "daemon.log")
    monkeypatch.setattr(server, "ALGO_DIR", tmp_path / "algo_candidates")
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    workspace = controller.workspace()
    assert workspace["ok"] is True
    assert workspace["runtime"]["safety"]["real_money_enabled"] is False
    assert workspace["capabilities"]["items"]
    assert workspace["algo"]["new_candidates_begin_stage"] == "RESEARCH"
    assert workspace["algo"]["auto_live_deploy"] is False


def test_algo_builder_creates_research_only_compiled_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    assert result["stage"] == "RESEARCH"
    assert result["research_only"] is True
    assert result["live_approved"] is False
    assert result["algorithm"]["compilable"] is True
    assert result["validation"]["completed"] == ["compile"]
    assert result["validation"]["next_required"] == "causal_backtest"
    assert result["validation"]["can_auto_deploy_live"] is False
    assert result["safety"]["portfolio_risk_owned_by_candidate"] is False
    assert result["safety"]["broker_authority"] is False
    assert result["safety"]["fund_transfer_authority"] is False
    assert result["safety"]["withdrawal_authority"] is False
    assert len(controller.algo_candidates()) == 1


def test_algo_builder_rejects_non_allowlisted_component(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "ALGO_DIR", tmp_path / "algo_candidates")
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    with pytest.raises(ValueError, match="unsupported entries primitive"):
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


def test_algo_options_do_not_expose_arbitrary_code_or_live_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(server, "ALGO_DIR", tmp_path / "algo_candidates")
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    options = controller.algo_options()
    assert options["mode"] == "RESEARCH_ONLY"
    assert "ema_trend" in options["entries"]
    assert "atr_stop" in options["exits"]
    assert options["constraints"]["portfolio_risk_parameters_allowed"] is False
    assert options["constraints"]["broker_credentials_allowed"] is False
    assert options["constraints"]["live_approval_allowed"] is False
    assert options["constraints"]["arbitrary_code_allowed"] is False


def test_chart_surface_delegates_to_demo_read_model(tmp_path: Path, monkeypatch) -> None:
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    monkeypatch.setattr(
        server,
        "mt5_chart_snapshot",
        lambda symbol, timeframe, bars: {
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": bars,
            "candles": [],
        },
    )
    assert controller.chart(symbol="XAUUSD", timeframe="5m", bars=300) == {
        "ok": True,
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "bars": 300,
        "candles": [],
    }


def test_chart_symbol_resolves_shortest_tradable_broker_suffix() -> None:
    from types import SimpleNamespace

    from aura.webapp.charting import resolve_chart_symbol

    class Gateway:
        rows = (
            SimpleNamespace(name="XAUUSD247m", trade_mode=4),
            SimpleNamespace(name="XAUUSDm", trade_mode=4),
            SimpleNamespace(name="XAUUSD-disabled", trade_mode=0),
        )

        def symbol_info(self, symbol):
            return next((row for row in self.rows if row.name == symbol), None)

        def symbols_get(self):
            return self.rows

    assert resolve_chart_symbol(Gateway(), "XAUUSD") == "XAUUSDm"


def test_runtime_start_archives_stale_log_before_new_process(tmp_path: Path, monkeypatch) -> None:
    runtime_dir = tmp_path / "aura_web"
    log_path = runtime_dir / "daemon.log"
    runtime_dir.mkdir()
    log_path.write_text("old failure\n", encoding="utf-8")
    monkeypatch.setattr(server, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(server, "LOG_PATH", log_path)
    monkeypatch.setattr(server, "KILL_LOCK_PATH", runtime_dir / "kill_switch.json")

    class Process:
        pid = 123
        returncode = None

        def poll(self):
            return None

    monkeypatch.setattr(server.subprocess, "Popen", lambda *args, **kwargs: Process())
    controller = server.AuraWebController(state_dir=tmp_path / "state")
    result = controller.start(max_symbols=1, max_batches=1)
    controller._close_log()

    assert result["started"] is True
    assert log_path.read_text(encoding="utf-8") == ""
    archived = tuple(runtime_dir.glob("daemon-*.log"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "old failure\n"


def test_backtest_surface_persists_research_only_result(tmp_path: Path, monkeypatch) -> None:
    candidate = {"candidate_id": "candidate-1", "research_only": True}
    monkeypatch.setattr(server, "BACKTEST_DIR", tmp_path / "backtests")
    monkeypatch.setattr(server.AuraWebController, "algo_candidates", lambda self: [candidate])
    monkeypatch.setattr(
        server,
        "run_candidate_backtest",
        lambda selected, **kwargs: {
            "ok": True,
            "research_only": True,
            "live_approved": False,
            "artifact_hash": "abc123",
            "candidate_id": selected["candidate_id"],
            "inputs": kwargs,
        },
    )
    controller = server.AuraWebController(state_dir=tmp_path / "mt5_state")
    result = controller.run_backtest(
        {"candidate_id": "candidate-1", "symbol": "XAUUSD", "timeframe": "5m", "bars": 500}
    )
    assert result["research_only"] is True
    assert result["live_approved"] is False
    assert result["artifact_file"] == "abc123.json"
    assert (tmp_path / "backtests" / "abc123.json").exists()
