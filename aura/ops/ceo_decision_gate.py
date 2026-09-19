from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    AgentRound,
    DecisionReasonCode,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.orchestrator import CEOAggregator
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.ops.backtest_gate import PHASE_SIX_EVIDENCE
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.knowledge_rag_gate import PHASE_EIGHT_EVIDENCE
from aura.ops.market_data_gate import PHASE_FIVE_EVIDENCE
from aura.ops.multi_agent_gate import PHASE_NINE_EVIDENCE
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
DECISION_TRACE_LOGS = OUTPUT_DIR / "decision_trace_logs.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_TEN_EVIDENCE = {"Decision trace logs": DECISION_TRACE_LOGS.as_posix()}

_NOW = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)


def build_decision_trace_logs() -> dict[str, Any]:
    context = _context()
    evidence = _directional_evidence()
    round_result = _round(evidence)
    reversed_round = _round(tuple(reversed(evidence)))
    ceo = CEOAggregator(min_agents=4, min_distinct_roles=4)

    first = ceo.synthesize(round_result, context=context)
    repeated = ceo.synthesize(round_result, context=context)
    reordered = ceo.synthesize(reversed_round, context=context)
    if first.decision_trace is None:
        raise RuntimeError("Phase 10 CEO decision did not produce a trace")

    disagreement = CEOAggregator(
        min_agents=3,
        min_distinct_roles=3,
        min_directional_margin=0.15,
    ).synthesize(_round(_disagreement_evidence()), context=context)
    no_quorum = CEOAggregator(min_agents=4, min_distinct_roles=4).synthesize(
        _round(evidence[:2]),
        context=context,
    )

    trace = first.decision_trace
    probes = {
        "identical_input_is_reproducible": first == repeated,
        "evidence_order_is_irrelevant": first == reordered,
        "every_evidence_packet_is_traced": (
            trace.evidence_count
            == len(trace.contributions)
            == len(round_result.evidence)
        ),
        "contributions_are_schema_bound": all(
            contribution.source_ids
            and contribution.effective_score >= 0
            for contribution in trace.contributions
        ),
        "support_opposition_and_abstention_are_preserved": (
            set(first.supporting_agents) == {"technical", "volume"}
            and first.opposing_agents == ("macro",)
            and first.abstaining_agents == ("execution",)
        ),
        "risk_flags_are_preserved": first.risk_flags == ("wide_spread",),
        "disagreement_becomes_no_trade": (
            disagreement.intent == SignalIntent.FLAT
            and disagreement.decision_trace is not None
            and disagreement.decision_trace.reason_code
            == DecisionReasonCode.DIRECTIONAL_DISAGREEMENT
        ),
        "missing_quorum_becomes_no_trade": (
            no_quorum.intent == SignalIntent.FLAT
            and not no_quorum.quorum_met
            and no_quorum.decision_trace is not None
            and no_quorum.decision_trace.reason_code
            == DecisionReasonCode.QUORUM_NOT_MET
        ),
        "ceo_has_no_execution_authority": (
            not first.execution_authority
            and not trace.execution_authority
            and disagreement.execution_authority is False
        ),
    }
    if not all(probes.values()):
        raise RuntimeError("Phase 10 CEO decision probe failed")

    report: dict[str, Any] = {
        "schema_version": 1,
        "phase": 10,
        "decision": "PASS",
        "fixture_type": "deterministic_internal_evidence_fusion_fixture",
        "primary_decision": first.model_dump(mode="json"),
        "no_trade_cases": {
            "directional_disagreement": disagreement.model_dump(mode="json"),
            "quorum_not_met": no_quorum.model_dump(mode="json"),
        },
        "reproducibility": {
            "first_fingerprint": trace.decision_fingerprint,
            "repeated_fingerprint": repeated.decision_trace.decision_fingerprint
            if repeated.decision_trace is not None
            else None,
            "reordered_fingerprint": reordered.decision_trace.decision_fingerprint
            if reordered.decision_trace is not None
            else None,
            "probes": probes,
        },
        "authority_boundary": {
            "ceo_can_submit_orders": False,
            "ceo_can_size_positions": False,
            "ceo_can_bypass_risk": False,
            "ceo_can_approve_strategies": False,
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


def _context() -> AgentContext:
    candle = NormalizedCandle(
        symbol="AURA-PHASE10-FIXTURE",
        venue="INTERNAL_FIXTURE",
        timeframe="5m",
        open_time=_NOW - timedelta(minutes=5),
        close_time=_NOW,
        open=Decimal(100),
        high=Decimal(102),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(1000),
        closed=True,
    )
    return AgentContext(
        correlation_id="phase10:decision-trace",
        symbol=candle.symbol,
        decision_timeframe=candle.timeframe,
        candles=(candle,),
        metadata={"market": "INTERNAL_FIXTURE", "regime": "trend"},
        created_at=_NOW,
    )


def _evidence(
    agent_id: str,
    role: AgentRole,
    intent: SignalIntent,
    confidence: float,
    trust_score: float,
    *,
    risk_flags: tuple[str, ...] = (),
) -> AgentEvidence:
    return AgentEvidence(
        agent_id=agent_id,
        role=role,
        intent=intent,
        confidence=confidence,
        thesis=f"deterministic {role.value} fixture",
        risk_flags=risk_flags,
        sources=(
            EvidenceSource(
                source_id=f"fixture:{agent_id}",
                source_type=EvidenceSourceType.MARKET_DATA,
                observed_at=_NOW,
                trust_score=trust_score,
            ),
        ),
        generated_at=_NOW,
    )


def _directional_evidence() -> tuple[AgentEvidence, ...]:
    return (
        _evidence("technical", AgentRole.TECHNICAL, SignalIntent.LONG, 0.8, 0.9),
        _evidence("volume", AgentRole.VOLUME_VWAP, SignalIntent.LONG, 0.7, 0.9),
        _evidence("macro", AgentRole.MACRO_SENTIMENT, SignalIntent.SHORT, 0.4, 0.8),
        _evidence(
            "execution",
            AgentRole.EXECUTION_QUALITY,
            SignalIntent.FLAT,
            0.7,
            1.0,
            risk_flags=("wide_spread",),
        ),
    )


def _disagreement_evidence() -> tuple[AgentEvidence, ...]:
    return (
        _evidence("technical", AgentRole.TECHNICAL, SignalIntent.LONG, 0.8, 1.0),
        _evidence("macro", AgentRole.MACRO_SENTIMENT, SignalIntent.SHORT, 0.8, 1.0),
        _evidence("regime", AgentRole.REGIME, SignalIntent.FLAT, 0.5, 1.0),
    )


def _round(evidence: tuple[AgentEvidence, ...]) -> AgentRound:
    return AgentRound(
        correlation_id="phase10:decision-trace",
        evidence=evidence,
        started_at=_NOW,
        completed_at=_NOW,
    )


def write_ceo_decision_artifacts(root: Path) -> None:
    root = root.resolve()
    _write_json(root / DECISION_TRACE_LOGS, build_decision_trace_logs())
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
            10: PHASE_TEN_EVIDENCE,
        },
    )
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_ceo_decision_artifacts(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_decision_trace_logs())
    path = root / DECISION_TRACE_LOGS
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 10 evidence: {DECISION_TRACE_LOGS.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 10 evidence: {DECISION_TRACE_LOGS.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 10):
        errors.append("Phase 10 is not PASS in the governance ledger")
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
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-10 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_ceo_decision_artifacts(root)
        print("Phase 10: PASS")
        return 0
    errors = check_ceo_decision_artifacts(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 10 CEO decision artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
