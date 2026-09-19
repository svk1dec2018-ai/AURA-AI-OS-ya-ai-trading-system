from __future__ import annotations

from aura.domain.models import SignalIntent
from aura.evolution.brain_policy import BrainPolicyGate
from aura.runtime.brain_scanner import BrainPolicyScanner
from aura.runtime.scanner import MarketScanResult, MultiMarketIntelligenceScanner, ScanCandidate


class LearningBrainPolicyScanner(BrainPolicyScanner):
    """Apply evolvable brain policy while retaining raw evidence for learning.

    The raw scan is preserved so shadow outcome and missed-opportunity auditors can
    learn from decisions the evolvable policy filtered out. Non-evolvable data and
    AgentRiskPolicy safety controls remain attached to each candidate downstream.
    """

    def __init__(self, scanner: MultiMarketIntelligenceScanner, gate: BrainPolicyGate) -> None:
        super().__init__(scanner, gate)
        self.last_raw_scan = MarketScanResult(candidates=())

    async def scan(self, contexts) -> MarketScanResult:
        raw = await self.scanner.scan(contexts)
        self.last_raw_scan = raw
        candidates: list[ScanCandidate] = []
        for candidate in raw.candidates:
            decision = self.gate.evaluate(
                round_result=candidate.round,
                memo=candidate.memo,
                deliberation=candidate.deliberation,
            )
            if decision.allowed or candidate.memo.intent == SignalIntent.FLAT:
                candidates.append(candidate)
                continue
            memo = candidate.memo.model_copy(
                update={
                    "intent": SignalIntent.FLAT,
                    "confidence": 0.0,
                    "risk_flags": tuple(
                        dict.fromkeys(
                            (*candidate.memo.risk_flags, "brain_policy_block")
                        )
                    ),
                    "rationale": (
                        f"{candidate.memo.rationale}; brain policy blocked: "
                        f"{decision.reason}"
                    ),
                }
            )
            candidates.append(
                ScanCandidate(
                    context=candidate.context,
                    round=candidate.round,
                    memo=memo,
                    data_quality=candidate.data_quality,
                    agent_policy=candidate.agent_policy,
                    deliberation=candidate.deliberation,
                )
            )
        return MarketScanResult(candidates=tuple(candidates))
