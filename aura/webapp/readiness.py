from __future__ import annotations

from typing import Any

from aura.webapp.catalog import capability_catalog


def build_readiness(
    runtime: dict[str, Any],
    mt5_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a truthful release-readiness view for the owner/client UI.

    Readiness is split into software capability, current runtime evidence and
    external release gates.  A green DEMO runtime is never represented as proof
    that unrestricted real-money deployment is approved.
    """

    catalog = capability_catalog()
    items = {item["id"]: item for item in catalog["items"]}
    preflight = mt5_preflight or {}
    status = runtime.get("status") or {}
    brain = runtime.get("brain") or {}
    safety = runtime.get("safety") or {}

    def code_ready(*ids: str) -> bool:
        ready = {"ui_connected", "backend_ready"}
        return all(items.get(item_id, {}).get("status") in ready for item_id in ids)

    checks: list[dict[str, Any]] = [
        _check(
            "owner_app",
            "Owner command center",
            code_ready("command_center", "mobile_pwa"),
            "code",
            "Installable owner workspace and controls are implemented.",
        ),
        _check(
            "mt5_demo_preflight",
            "MT5 DEMO connection",
            bool(preflight.get("ok") and preflight.get("demo_verified")),
            "runtime",
            str(preflight.get("error") or "Verified DEMO terminal/account required."),
        ),
        _check(
            "symbol_universe",
            "Tradable broker symbol universe",
            int(preflight.get("tradable_symbol_count", 0) or 0) > 0,
            "runtime",
            f"{int(preflight.get('tradable_symbol_count', 0) or 0)} tradable symbols discovered.",
        ),
        _check(
            "market_clock",
            "Broker market timestamp",
            preflight.get("market_clock_ok") is True,
            "runtime",
            str((preflight.get("market_clock") or {}).get("error")
                or "Broker timestamps are safe for point-in-time decisions."),
        ),
        _check(
            "market_intelligence",
            "Scanner + technical/SMC/volume/regime intelligence",
            code_ready(
                "market_scanner",
                "technical_intelligence",
                "smc_ict",
                "volume_vwap",
                "regime_engine",
            ),
            "code",
            "Multi-market intelligence stack is implemented; live coverage follows connected feeds.",
        ),
        _check(
            "reasoning",
            "Specialist agents + CEO synthesis",
            code_ready("specialist_agents", "adversarial_reasoning", "ceo_orchestrator"),
            "code",
            "Structured evidence and disagreement feed the CEO decision layer.",
        ),
        _check(
            "risk_execution",
            "RiskEngine + protected MT5 DEMO execution",
            code_ready("risk_engine", "autonomous_demo", "order_state", "reconciliation"),
            "code",
            "Only RiskEngine-approved orders can reach the protected DEMO broker adapter.",
        ),
        _check(
            "self_learning",
            "Forward self-learning / challenger research",
            code_ready("self_learning", "shadow_learning", "champion_challenger"),
            "code",
            "Forward outcomes may create challengers; no automatic unrestricted live promotion.",
        ),
        _check(
            "brain_runtime",
            "Learning runtime active",
            bool(brain.get("state") and brain.get("state") not in {"stopped", "idle"}),
            "runtime",
            f"Brain state: {brain.get('state', 'not started')}.",
        ),
        _check(
            "research_validation",
            "Algo Studio + causal validation stack",
            code_ready(
                "algo_studio",
                "backtest",
                "walk_forward",
                "monte_carlo",
                "holdout",
                "parameter_stability",
                "regime_validation",
            ),
            "code",
            "Strategy candidates remain research-only until the validation chain and forward evidence pass.",
        ),
        _check(
            "fund_movement_block",
            "Fund transfer / withdrawal blocked",
            safety.get("fund_transfers_enabled") is False
            and safety.get("withdrawals_enabled") is False,
            "safety",
            "AURA has no automated fund-transfer or withdrawal authority.",
        ),
    ]

    software_ready = all(item["passed"] for item in checks if item["scope"] in {"code", "safety"})
    mt5_runtime_ready = all(
        item["passed"]
        for item in checks
        if item["id"] in {"mt5_demo_preflight", "symbol_universe", "market_clock"}
    )
    runtime_active = bool(runtime.get("runtime_running"))
    app_kill_locked = bool(runtime.get("app_kill_locked"))
    risk_kill = bool(status.get("risk_kill_switch"))

    if app_kill_locked or risk_kill:
        demo_state = "BLOCKED_BY_KILL_SWITCH"
    elif software_ready and mt5_runtime_ready and runtime_active:
        demo_state = "MT5_DEMO_RUNNING"
    elif software_ready and mt5_runtime_ready:
        demo_state = "MT5_DEMO_READY_TO_START"
    elif software_ready:
        demo_state = "SOFTWARE_READY_MT5_RUNTIME_REQUIRED"
    else:
        demo_state = "SOFTWARE_VALIDATION_REQUIRED"

    return {
        "ok": True,
        "release": "AURA_AI_OS_0.2",
        "demo_state": demo_state,
        "software_ready": software_ready,
        "mt5_runtime_ready": mt5_runtime_ready,
        "runtime_active": runtime_active,
        "self_learning_runtime_active": runtime_active and next(
            (item["passed"] for item in checks if item["id"] == "brain_runtime"),
            False,
        ),
        "checks": checks,
        "external_gates": [
            {
                "id": "forward_broker_evidence",
                "name": "Long-duration broker-forward validation",
                "required": True,
                "satisfied": False,
                "reason": "Requires elapsed real DEMO/paper observations, broker fills/rejects/reconnects and reconciliation evidence.",
            },
            {
                "id": "real_money_canary",
                "name": "Controlled real-money canary",
                "required": True,
                "satisfied": False,
                "reason": "Intentionally locked until release gates and explicit human approval pass.",
            },
        ],
        "real_money_enabled": False,
        "unrestricted_live_approved": False,
    }


def _check(
    check_id: str,
    name: str,
    passed: bool,
    scope: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "passed": bool(passed),
        "scope": scope,
        "detail": detail,
    }
