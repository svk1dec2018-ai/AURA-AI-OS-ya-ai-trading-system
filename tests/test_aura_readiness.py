from aura.webapp.readiness import build_readiness


def _runtime(*, running: bool = False, brain_state: str = "stopped") -> dict:
    return {
        "runtime_running": running,
        "app_kill_locked": False,
        "status": {"risk_kill_switch": False},
        "brain": {"state": brain_state},
        "safety": {
            "fund_transfers_enabled": False,
            "withdrawals_enabled": False,
        },
    }


def test_readiness_requires_live_mt5_demo_runtime_evidence() -> None:
    payload = build_readiness(
        _runtime(),
        {
            "ok": False,
            "demo_verified": False,
            "tradable_symbol_count": 0,
            "error": "terminal not connected",
        },
    )
    assert payload["software_ready"] is True
    assert payload["mt5_runtime_ready"] is False
    assert payload["demo_state"] == "SOFTWARE_READY_MT5_RUNTIME_REQUIRED"
    assert payload["real_money_enabled"] is False
    assert payload["unrestricted_live_approved"] is False


def test_readiness_marks_verified_demo_as_ready_to_start() -> None:
    payload = build_readiness(
        _runtime(),
        {
            "ok": True,
            "demo_verified": True,
            "tradable_symbol_count": 250,
            "market_clock_ok": True,
        },
    )
    assert payload["software_ready"] is True
    assert payload["mt5_runtime_ready"] is True
    assert payload["demo_state"] == "MT5_DEMO_READY_TO_START"


def test_readiness_marks_active_self_learning_demo_runtime() -> None:
    payload = build_readiness(
        _runtime(running=True, brain_state="running"),
        {
            "ok": True,
            "demo_verified": True,
            "tradable_symbol_count": 250,
            "market_clock_ok": True,
        },
    )
    assert payload["demo_state"] == "MT5_DEMO_RUNNING"
    assert payload["self_learning_runtime_active"] is True
    assert payload["external_gates"][0]["satisfied"] is False
    assert payload["external_gates"][1]["satisfied"] is False


def test_readiness_fail_closes_on_kill_switch() -> None:
    runtime = _runtime(running=True, brain_state="running")
    runtime["app_kill_locked"] = True
    payload = build_readiness(
        runtime,
        {
            "ok": True,
            "demo_verified": True,
            "tradable_symbol_count": 250,
            "market_clock_ok": True,
        },
    )
    assert payload["demo_state"] == "BLOCKED_BY_KILL_SWITCH"


def test_readiness_blocks_future_broker_timestamp() -> None:
    payload = build_readiness(
        _runtime(),
        {
            "ok": True,
            "demo_verified": True,
            "tradable_symbol_count": 250,
            "market_clock_ok": False,
            "market_clock": {"error": "broker timestamp is in the future"},
        },
    )
    assert payload["mt5_runtime_ready"] is False
    assert payload["demo_state"] == "SOFTWARE_READY_MT5_RUNTIME_REQUIRED"
    assert next(item for item in payload["checks"] if item["id"] == "market_clock") == {
        "id": "market_clock",
        "name": "Broker market timestamp",
        "passed": False,
        "scope": "runtime",
        "detail": "broker timestamp is in the future",
    }
