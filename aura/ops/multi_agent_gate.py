from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.agents.base import SpecialistAgent
from aura.agents.models import AgentContext, AgentEvidence, AgentRole
from aura.agents.orchestrator import MultiAgentOrchestrator
from aura.agents.team import build_default_agent_team
from aura.domain.models import NormalizedCandle
from aura.knowledge.firewall import KnowledgeFirewall, KnowledgeItem, KnowledgeSourceType
from aura.ops.backtest_gate import PHASE_SIX_EVIDENCE
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.knowledge_rag_gate import PHASE_EIGHT_EVIDENCE
from aura.ops.market_data_gate import PHASE_FIVE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.risk_engine_gate import PHASE_THREE_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE
from aura.ops.strategy_research_gate import PHASE_SEVEN_EVIDENCE

OUTPUT_DIR = Path("artifacts/governance")
AGENT_REPORT = OUTPUT_DIR / "agent_consistency_report.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_NINE_EVIDENCE = {"Agent consistency report": AGENT_REPORT.as_posix()}

_START = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)


class _FreeFormAgent(SpecialistAgent):
    agent_id = "invalid:free-form"
    role = AgentRole.TECHNICAL

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        return {"intent": "LONG", "execute": True}  # type: ignore[return-value]


def build_agent_consistency_report() -> dict[str, Any]:
    context = _context()
    first = build_default_agent_team(
        _firewall(), include_env_ai=False, timeout_seconds=1
    )
    second = build_default_agent_team(
        _firewall(), include_env_ai=False, timeout_seconds=1
    )
    first_round = asyncio.run(first.orchestrator.run_round(context))
    second_round = asyncio.run(second.orchestrator.run_round(context))
    if first_round.failures or second_round.failures:
        raise RuntimeError("Phase 9 default specialist round contained failures")

    first_payload = [item.model_dump(mode="json") for item in first_round.evidence]
    second_payload = [item.model_dump(mode="json") for item in second_round.evidence]
    roles = {item.role for item in first_round.evidence}
    all_roles_present = roles == set(AgentRole)
    deterministic_outputs = first_payload == second_payload
    registry_complete = (
        len(first.registry.registrations) == len(first.agents) == len(AgentRole)
        and first.registry.roles == frozenset(AgentRole)
    )
    advisory_only = all(
        item.authority == "advisory_only"
        and not item.broker_access
        and not item.portfolio_mutation
        and not item.strategy_approval
        for item in first.registry.registrations
    ) and all(not item.execution_authority for item in first_round.evidence)
    free_form_output_blocked = asyncio.run(_free_form_output_is_blocked(context))
    probes = {
        "all_roles_present": all_roles_present,
        "registry_complete": registry_complete,
        "outputs_deterministic": deterministic_outputs,
        "outputs_match_agent_evidence_schema": all(
            isinstance(item, AgentEvidence) for item in first_round.evidence
        ),
        "registry_is_advisory_only": advisory_only,
        "free_form_output_blocked": free_form_output_blocked,
    }
    if not all(probes.values()):
        raise RuntimeError("Phase 9 agent consistency probe failed")

    report: dict[str, Any] = {
        "schema_version": 1,
        "phase": 9,
        "decision": "PASS",
        "fixture_type": "deterministic_internal_multi_agent_fixture",
        "specialists": {
            "count": len(first.agents),
            "roles": sorted(role.value for role in roles),
            "registry": [
                item.model_dump(mode="json") for item in first.registry.registrations
            ],
        },
        "consistency": {
            "first_round_hash": _sha256(first_payload),
            "second_round_hash": _sha256(second_payload),
            "evidence_packets_per_round": len(first_round.evidence),
            "probes": probes,
        },
        "authority_boundary": {
            "specialists_can_submit_orders": False,
            "specialists_can_mutate_portfolio": False,
            "specialists_can_approve_strategies": False,
            "specialists_can_bypass_risk": False,
        },
        "claims": {
            "external_ai_called": False,
            "external_market_data_used": False,
            "trading_action_performed": False,
            "live_money_enabled": False,
        },
    }
    report["deterministic_fingerprint"] = _sha256(report)
    return report


async def _free_form_output_is_blocked(context: AgentContext) -> bool:
    result = await MultiAgentOrchestrator([_FreeFormAgent()]).run_round(context)
    return (
        not result.evidence
        and len(result.failures) == 1
        and result.failures[0].error_type == "TypeError"
        and "AgentEvidence schema" in result.failures[0].message
    )


def _context() -> AgentContext:
    candles = tuple(_candle(index) for index in range(30))
    observed_at = candles[-1].close_time
    return AgentContext(
        correlation_id="phase9:all-specialists",
        symbol="AURA-PHASE9-FIXTURE",
        decision_timeframe="5m",
        candles=candles,
        created_at=observed_at,
        metadata={
            "htf_candles": [_htf_candle(index).model_dump(mode="json") for index in range(25)],
            "options_snapshot": {
                "source_id": "fixture:options",
                "underlying_symbol": "AURA-PHASE9-FIXTURE",
                "observed_at": observed_at,
                "implied_volatility": 0.25,
                "iv_percentile": 50.0,
                "put_call_oi_ratio": 1.0,
                "put_call_volume_ratio": 1.0,
                "trust_score": 1.0,
            },
            "cross_market_observations": [
                {
                    "source_id": "fixture:cross-market",
                    "related_symbol": "AURA-RELATED-FIXTURE",
                    "observed_at": observed_at,
                    "intent": "LONG",
                    "confidence": 0.8,
                    "trust_score": 1.0,
                    "rationale": "deterministic related-market fixture",
                }
            ],
            "execution_quality": {
                "source_id": "fixture:book",
                "observed_at": observed_at,
                "spread_bps": 2.0,
                "estimated_slippage_bps": 3.0,
                "top_of_book_notional": 100000.0,
                "trust_score": 1.0,
            },
        },
    )


def _candle(index: int) -> NormalizedCandle:
    opened = _START + timedelta(minutes=5 * index)
    open_price = Decimal(100 + index)
    close_price = open_price + Decimal(1)
    return NormalizedCandle(
        symbol="AURA-PHASE9-FIXTURE",
        venue="INTERNAL_FIXTURE",
        timeframe="5m",
        open_time=opened,
        close_time=opened + timedelta(minutes=5),
        open=open_price,
        high=close_price + Decimal(1),
        low=open_price - Decimal(1),
        close=close_price,
        volume=Decimal(300 if index == 29 else 100),
        closed=True,
    )


def _htf_candle(index: int) -> NormalizedCandle:
    opened = _START - timedelta(days=2) + timedelta(hours=index)
    price = Decimal(80 + index)
    return NormalizedCandle(
        symbol="AURA-PHASE9-FIXTURE",
        venue="INTERNAL_FIXTURE",
        timeframe="1h",
        open_time=opened,
        close_time=opened + timedelta(hours=1),
        open=price,
        high=price + Decimal(2),
        low=price - Decimal(1),
        close=price + Decimal(1),
        volume=Decimal(500),
        closed=True,
    )


def _firewall() -> KnowledgeFirewall:
    firewall = KnowledgeFirewall(min_trust_score=0.7)
    observed_at = _START + timedelta(minutes=150)
    firewall.ingest(
        KnowledgeItem.from_text(
            item_id="phase9-macro",
            source_id="fixture:macro",
            source_type=KnowledgeSourceType.INTERNAL,
            title="Phase 9 macro fixture",
            content="Deterministic macro context for the internal consistency fixture.",
            publication_date=observed_at,
            observed_at=observed_at,
            confidence=0.8,
            trust_score=0.9,
            tags=("macro", "AURA-PHASE9-FIXTURE"),
            claims={"market.bias": "LONG"},
        )
    )
    return firewall


def write_multi_agent_artifacts(root: Path) -> None:
    root = root.resolve()
    _write_json(root / AGENT_REPORT, build_agent_consistency_report())
    records = build_sequential_phase_records(
        root,
        {
            0: PHASE_ZERO_EVIDENCE,
            1: PHASE_ONE_EVIDENCE,
            2: PHASE_TWO_EVIDENCE,
            3: PHASE_THREE_EVIDENCE,
            4: PHASE_FOUR_EVIDENCE,
            5: PHASE_FIVE_EVIDENCE,
            6: PHASE_SIX_EVIDENCE,
            7: PHASE_SEVEN_EVIDENCE,
            8: PHASE_EIGHT_EVIDENCE,
            9: PHASE_NINE_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_multi_agent_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_agent_consistency_report())
    path = root / AGENT_REPORT
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 9 evidence: {AGENT_REPORT.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 9 evidence: {AGENT_REPORT.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 9):
        errors.append("Phase 9 is not PASS in the governance ledger")
    return tuple(errors)


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-9 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_multi_agent_artifacts(root)
        print("Phase 9: PASS")
        return 0
    errors = check_multi_agent_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 9 multi-agent artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
