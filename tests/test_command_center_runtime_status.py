from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aura.interface.runtime_status import FileRuntimeStatusSource
from aura.interface.web_command_center import CommandCenterConfig, CommandCenterService

NOW = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)


def _write_status(path, **changes) -> None:
    payload = {
        "mode": "NO_KEY_PUBLIC_LIVE_MULTI_AI_COUNCIL",
        "updated_at": NOW.isoformat(),
        "real_money_enabled": False,
        "broker_orders_enabled": False,
        "symbols": ["BTC-USD", "ETH-USD"],
        "risk_kill_switch": False,
        "risk_kill_switch_reason": None,
        "latest": {
            "correlation_id": "decision-1",
            "symbol": "BTC-USD",
            "timeframe": "5m",
            "intent": "LONG",
            "confidence": 0.72,
            "actionable": True,
            "risk_flags": ["spread elevated"],
            "rationale": "Validated multi-agent evidence.",
            "portfolio_equity": "10000",
            "gross_exposure": "1250",
            "drawdown_pct": "1.2",
            "agent_evidence": [
                {
                    "agent_id": "technical",
                    "role": "technical",
                    "intent": "LONG",
                    "confidence": 0.74,
                    "thesis": "closed candle trend",
                    "secret": "must-not-leak",
                }
            ],
            "secret": "must-not-leak",
            "unsupported_metric": float("nan"),
        },
        "api_key": "must-not-leak",
    }
    payload.update(changes)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_fresh_runtime_status_is_validated_and_allowlisted(tmp_path) -> None:
    path = tmp_path / "status.json"
    _write_status(path)
    view = FileRuntimeStatusSource(path).read(now=NOW + timedelta(seconds=30))

    assert view.available is True
    assert view.state == "fresh"
    assert view.market["symbol"] == "BTC-USD"
    assert view.risk["kill_switch"] is False
    assert view.portfolio["portfolio_equity"] == "10000"
    assert view.explanation["agent_evidence"][0]["agent_id"] == "technical"
    serialized = view.model_dump_json()
    assert "must-not-leak" not in serialized
    assert "api_key" not in serialized


def test_missing_stale_invalid_and_oversized_status_fail_closed(tmp_path) -> None:
    path = tmp_path / "status.json"
    source = FileRuntimeStatusSource(path, max_age_seconds=60, max_bytes=1024)
    assert source.read(now=NOW).state == "missing"

    _write_status(path, updated_at=(NOW - timedelta(seconds=61)).isoformat())
    assert source.read(now=NOW).state == "stale"

    path.write_text("not-json", encoding="utf-8")
    assert source.read(now=NOW).state == "invalid"

    path.write_text("x" * 1025, encoding="utf-8")
    assert source.read(now=NOW).state == "oversized"


def test_live_money_status_is_never_exposed(tmp_path) -> None:
    path = tmp_path / "status.json"
    _write_status(path, real_money_enabled=True)
    view = FileRuntimeStatusSource(path).read(now=NOW)
    assert view.available is False
    assert view.state == "unsafe_mode"
    assert view.market == {}


def test_naive_or_missing_required_timestamp_is_invalid(tmp_path) -> None:
    path = tmp_path / "status.json"
    _write_status(path, updated_at="2026-08-20T16:00:00")
    assert FileRuntimeStatusSource(path).read(now=NOW).state == "invalid"


def test_nonfinite_allowlisted_metric_is_omitted(tmp_path) -> None:
    path = tmp_path / "status.json"
    _write_status(
        path,
        latest={
            "symbol": "BTC-USD",
            "confidence": float("nan"),
            "portfolio_equity": float("inf"),
        },
    )

    view = FileRuntimeStatusSource(path).read(now=NOW)

    assert view.available is True
    assert "confidence" not in view.market
    assert "portfolio_equity" not in view.portfolio


def test_command_center_routes_only_available_runtime_domains(tmp_path, monkeypatch) -> None:
    path = tmp_path / "status.json"
    _write_status(path, updated_at=datetime.now(UTC).isoformat())
    service = CommandCenterService(
        CommandCenterConfig(
            queue_path=tmp_path / "queue.jsonl",
            runtime_status_path=path,
        )
    )

    market_status, market = service.handle_command("scan market")
    risk_status, risk = service.handle_command("risk status")
    portfolio_status, portfolio = service.handle_command("analyze portfolio")
    explain_status, explanation = service.handle_command("explain latest signal")

    assert market_status == 200
    assert market["payload"]["symbol"] == "BTC-USD"
    assert risk_status == 200
    assert risk["payload"]["kill_switch"] is False
    assert portfolio_status == 200
    assert portfolio["payload"]["portfolio_equity"] == "10000"
    assert explain_status == 200
    assert explanation["payload"]["rationale"] == "Validated multi-agent evidence."


def test_domain_without_values_remains_unavailable(tmp_path) -> None:
    path = tmp_path / "status.json"
    _write_status(
        path,
        updated_at=datetime.now(UTC).isoformat(),
        latest={"symbol": "BTC-USD", "timeframe": "5m"},
        risk_kill_switch=None,
    )
    service = CommandCenterService(
        CommandCenterConfig(
            queue_path=tmp_path / "queue.jsonl",
            runtime_status_path=path,
        )
    )

    status, result = service.handle_command("analyze portfolio")
    assert status == 503
    assert result["payload"]["source_available"] is False
    assert result["payload"]["source_state"] == "fresh"
