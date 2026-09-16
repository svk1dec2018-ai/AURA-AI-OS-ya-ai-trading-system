from __future__ import annotations

from typing import Any

from aura.interface.command_center import AssistantIntent, CommandRouter

_ROUTER = CommandRouter(
    allow_research=True,
    allow_development=True,
    allow_financial_correction=True,
    allow_paper_control=True,
    allow_live_control=False,
)


def answer_owner_query(
    text: str,
    *,
    runtime: dict[str, Any],
    decisions: dict[str, Any],
    learning: dict[str, Any],
    intelligence: dict[str, Any],
    candidates: list[dict[str, Any]],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Return an auditable, governed local assistant answer.

    This is intentionally deterministic. It gives the PWA a useful command
    surface even when no optional LLM is connected, while preserving the same
    intent/privilege classification used by AURA's Command Center. LLM-backed
    phrasing may be layered on top later, but it must not change these authority
    decisions.
    """

    command = _ROUTER.parse(text)
    status = runtime.get("status") or {}
    latest = status.get("latest") or {}
    counters = status.get("counters") or {}
    safety = runtime.get("safety") or {}
    brain = learning.get("status") or {}
    decision_items = decisions.get("items") or []
    intelligence_items = intelligence.get("items") or []

    if command.intent == AssistantIntent.FUND_CONTROL:
        return _result(
            command,
            accepted=False,
            answer=(
                "Fund deposit, withdrawal and transfer commands are permanently disabled in AURA. "
                "I can show portfolio/risk state, but I cannot move money."
            ),
            human_approval_required=True,
        )
    if command.intent == AssistantIntent.LIVE_CONTROL:
        return _result(
            command,
            accepted=False,
            answer=(
                "Unrestricted live-money control is locked. AURA can run governed PAPER/DEMO workflows; "
                "a future live canary requires broker-origin evidence, release gates and explicit human approval."
            ),
            risk_gate_required=True,
            human_approval_required=True,
        )
    if command.intent == AssistantIntent.MARKET_SCAN:
        opportunities = latest.get("opportunities") or []
        return _result(
            command,
            accepted=True,
            answer=(
                f"Latest runtime snapshot has {len(opportunities)} visible opportunities and "
                f"{counters.get('opportunities', 0)} cumulative opportunities. "
                "Use Market Scanner for symbol/timeframe/intent/confidence and CEO Decisions for full evidence."
                if opportunities
                else "No fresh opportunity snapshot is available yet. Start the protected DEMO runtime or wait for the next closed-candle batch."
            ),
            payload={"opportunities": opportunities[:20]},
        )
    if command.intent == AssistantIntent.RISK_STATUS:
        return _result(
            command,
            accepted=True,
            answer=(
                f"Drawdown: {latest.get('drawdown_pct', '—')}; gross exposure: "
                f"{latest.get('gross_exposure', '—')}; risk kill switch: "
                f"{'ENGAGED' if status.get('risk_kill_switch') else 'clear'}. "
                "Independent RiskEngine remains final financial authority."
            ),
            payload={
                "drawdown_pct": latest.get("drawdown_pct"),
                "gross_exposure": latest.get("gross_exposure"),
                "kill_switch": status.get("risk_kill_switch", False),
                "kill_switch_reason": status.get("risk_kill_switch_reason"),
            },
        )
    if command.intent == AssistantIntent.POSITIONS:
        return _result(
            command,
            accepted=True,
            answer=(
                f"Portfolio equity: {latest.get('portfolio_equity', '—')}; gross exposure: "
                f"{latest.get('gross_exposure', '—')}; fills: {counters.get('fills', 0)}. "
                "The Portfolio page shows the current runtime read model."
            ),
            payload={"latest": latest, "counters": counters},
        )
    if command.intent == AssistantIntent.EXPLAIN:
        latest_decision = decision_items[0] if decision_items else None
        if latest_decision is None:
            answer = "No persisted CEO decision is available yet. AURA will explain the next audited agent round after the runtime produces one."
        else:
            answer = (
                f"Latest audited CEO view: {latest_decision.get('symbol', '—')} "
                f"{latest_decision.get('timeframe', '—')} → {latest_decision.get('intent', '—')} "
                f"at confidence {latest_decision.get('confidence', '—')}. "
                f"Thesis: {latest_decision.get('thesis') or 'No thesis text recorded.'} "
                f"Opposing view: {latest_decision.get('opposing_view') or 'None recorded.'}"
            )
        return _result(command, accepted=True, answer=answer, payload={"decision": latest_decision})
    if command.intent == AssistantIntent.RESEARCH_REQUEST:
        return _result(
            command,
            accepted=True,
            answer=(
                f"Research request accepted as an owner research intent. There are {len(candidates)} local Algo Studio candidates. "
                "Use Algo Studio to compile allow-listed components; every candidate remains RESEARCH-only until the full validation chain passes."
            ),
            payload={"candidate_count": len(candidates), "request": command.parameters.get("request")},
        )
    if command.intent == AssistantIntent.DEVELOPMENT_REQUEST:
        return _result(
            command,
            accepted=True,
            answer=(
                "Development request recognized. AURA's maintenance authority may diagnose/propose/sandbox-test changes, "
                "but it cannot silently merge, deploy, bypass RiskEngine, transfer funds or withdraw money."
            ),
            payload={"request": command.parameters.get("request")},
            human_approval_required=True,
        )
    if command.intent == AssistantIntent.FINANCIAL_CORRECTION_REQUEST:
        return _result(
            command,
            accepted=True,
            answer=(
                "Financial correction intent recognized. Only append-only audited reporting corrections are allowed; "
                "original broker fills and broker truth are not rewritten."
            ),
            payload={"request": command.parameters.get("request")},
            human_approval_required=True,
        )
    if command.intent == AssistantIntent.PAPER_CONTROL:
        return _result(
            command,
            accepted=True,
            answer=(
                "PAPER/DEMO control is permitted through the protected runtime controls. "
                "Use Start/Stop/Emergency Lock in Trading Desk; orders still require the independent risk chain."
            ),
            risk_gate_required=True,
        )

    counts = capabilities.get("counts") or {}
    answer = (
        f"AURA runtime is {'ACTIVE' if runtime.get('runtime_running') else 'STOPPED'}"
        f"{' with emergency lock engaged' if runtime.get('app_kill_locked') else ''}. "
        f"Capability inventory: {counts.get('ui_connected', 0)} UI-connected, "
        f"{counts.get('backend_ready', 0)} backend-ready, {counts.get('partial', 0)} partial, "
        f"{counts.get('external_gate', 0)} externally gated. "
        f"Learning state: {brain.get('state', 'not started')}; cached intelligence shown: {len(intelligence_items)}. "
        f"Real money enabled: {bool(safety.get('real_money_enabled', False))}."
    )
    return _result(command, accepted=True, answer=answer)


def _result(
    command,
    *,
    accepted: bool,
    answer: str,
    payload: dict[str, Any] | None = None,
    risk_gate_required: bool = False,
    human_approval_required: bool = False,
) -> dict[str, Any]:
    return {
        "ok": True,
        "command_id": command.command_id,
        "intent": command.intent.value,
        "privilege": command.privilege.value,
        "accepted": accepted,
        "answer": answer,
        "payload": payload or {},
        "risk_gate_required": risk_gate_required,
        "human_approval_required": human_approval_required,
        "execution_authority": False,
    }
