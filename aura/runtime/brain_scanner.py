from __future__ import annotations

from aura.domain.models import SignalIntent
from aura.evolution.brain_policy import BrainPolicyGate
from aura.runtime.scanner import MarketScanResult, MultiMarketIntelligenceScanner, ScanCandidate


class BrainPolicyScanner:
    """Apply an evolvable advisory policy after agents/CEO, before financial risk.

    A rejected opportunity is converted to an explicit FLAT CEO memo with a risk
    flag. The original specialist round and adversarial deliberation stay intact
    for audit/learning, and the independent RiskEngine remains downstream.
    """

    def __init__(
        self,
        scanner: MultiMarketIntelligenceScanner,
        gate: BrainPolicyGate,
    ) -> None:
        self.scanner = scanner
        self.gate = gate

    async def scan(self, contexts) -> MarketScanResult:
        raw = await self.scanner.scan(contexts)
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
