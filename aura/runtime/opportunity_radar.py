from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aura.domain.models import SignalIntent
from aura.runtime.scanner import MarketScanResult, ScanCandidate
from aura.strategy.features import FeatureSnapshot, UnifiedFeatureEngine


@dataclass(frozen=True, slots=True)
class OpportunityRadarItem:
    rank: int
    symbol: str
    venue: str
    timeframe: str
    intent: SignalIntent
    score: float
    ceo_confidence: float
    actionable: bool
    quorum_met: bool
    supporting_agents: tuple[str, ...]
    opposing_agents: tuple[str, ...]
    abstaining_agents: tuple[str, ...]
    risk_flags: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    data_quality_safe: bool | None
    disagreement_ratio: float | None
    technical_alignment: float
    features: FeatureSnapshot
    rationale: str
    as_of: datetime

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "intent": self.intent.value,
            "score": round(self.score, 4),
            "ceo_confidence": round(self.ceo_confidence, 4),
            "actionable": self.actionable,
            "quorum_met": self.quorum_met,
            "supporting_agents": list(self.supporting_agents),
            "opposing_agents": list(self.opposing_agents),
            "abstaining_agents": list(self.abstaining_agents),
            "risk_flags": list(self.risk_flags),
            "blocked_reasons": list(self.blocked_reasons),
            "data_quality_safe": self.data_quality_safe,
            "disagreement_ratio": (
                None if self.disagreement_ratio is None else round(self.disagreement_ratio, 4)
            ),
            "technical_alignment": round(self.technical_alignment, 4),
            "features": self.features.to_json_dict(),
            "rationale": self.rationale,
            "as_of": self.as_of.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OpportunityRadarSnapshot:
    items: tuple[OpportunityRadarItem, ...]
    as_of: datetime | None

    @property
    def actionable(self) -> tuple[OpportunityRadarItem, ...]:
        return tuple(item for item in self.items if item.actionable)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "as_of": None if self.as_of is None else self.as_of.isoformat(),
            "count": len(self.items),
            "actionable_count": len(self.actionable),
            "items": [item.to_json_dict() for item in self.items],
        }


class OpportunityRadar:
    """Deterministically rank CEO scan candidates without creating orders.

    Ranking combines already-governed CEO confidence, specialist agreement and a
    small set of canonical feature confirmations. Financial position sizing and
    execution remain exclusively downstream of the independent RiskEngine.
    """

    def __init__(self, feature_engine: UnifiedFeatureEngine | None = None) -> None:
        self.feature_engine = feature_engine or UnifiedFeatureEngine()

    def rank(self, scan: MarketScanResult) -> OpportunityRadarSnapshot:
        if not scan.candidates:
            return OpportunityRadarSnapshot(items=(), as_of=None)

        provisional = [self._build(candidate) for candidate in scan.candidates]
        provisional.sort(
            key=lambda item: (
                not item.actionable,
                -item.score,
                -item.ceo_confidence,
                item.symbol,
                item.timeframe,
            )
        )
        ranked = tuple(
            OpportunityRadarItem(
                rank=index,
                symbol=item.symbol,
                venue=item.venue,
                timeframe=item.timeframe,
                intent=item.intent,
                score=item.score,
                ceo_confidence=item.ceo_confidence,
                actionable=item.actionable,
                quorum_met=item.quorum_met,
                supporting_agents=item.supporting_agents,
                opposing_agents=item.opposing_agents,
                abstaining_agents=item.abstaining_agents,
                risk_flags=item.risk_flags,
                blocked_reasons=item.blocked_reasons,
                data_quality_safe=item.data_quality_safe,
                disagreement_ratio=item.disagreement_ratio,
                technical_alignment=item.technical_alignment,
                features=item.features,
                rationale=item.rationale,
                as_of=item.as_of,
            )
            for index, item in enumerate(provisional, start=1)
        )
        return OpportunityRadarSnapshot(
            items=ranked,
            as_of=max(item.as_of for item in ranked),
        )

    def _build(self, candidate: ScanCandidate) -> OpportunityRadarItem:
        features = self.feature_engine.compute(
            candidate.context.candles,
            decision_time=candidate.context.created_at,
        )
        memo = candidate.memo
        support_total = (
            len(memo.supporting_agents)
            + len(memo.opposing_agents)
            + len(memo.abstaining_agents)
        )
        support_ratio = (
            len(memo.supporting_agents) / support_total if support_total else 0.0
        )
        technical_alignment = _technical_alignment(memo.intent, features)
        disagreement = (
            candidate.deliberation.disagreement_ratio
            if candidate.deliberation is not None
            else 0.0
        )
        score = (
            memo.confidence * 60.0
            + support_ratio * 20.0
            + technical_alignment * 20.0
            - disagreement * 20.0
            - min(len(memo.risk_flags) * 5.0, 20.0)
        )
        score = max(0.0, min(100.0, score))

        blocked_reasons: list[str] = []
        if candidate.agent_policy is not None and not candidate.agent_policy.allowed:
            blocked_reasons.extend(candidate.agent_policy.reasons)
        if candidate.data_quality is not None and not candidate.data_quality.safe_for_decision:
            blocked_reasons.append("market data quality gate blocked the candidate")
        if not memo.quorum_met:
            blocked_reasons.append("CEO quorum not met")
        if memo.intent == SignalIntent.FLAT:
            blocked_reasons.append("CEO decision is neutral/flat")

        quality_safe = (
            None
            if candidate.data_quality is None
            else candidate.data_quality.safe_for_decision
        )
        return OpportunityRadarItem(
            rank=0,
            symbol=candidate.context.symbol,
            venue=candidate.context.candles[-1].venue,
            timeframe=candidate.context.decision_timeframe,
            intent=memo.intent,
            score=score,
            ceo_confidence=memo.confidence,
            actionable=candidate.actionable,
            quorum_met=memo.quorum_met,
            supporting_agents=memo.supporting_agents,
            opposing_agents=memo.opposing_agents,
            abstaining_agents=memo.abstaining_agents,
            risk_flags=tuple(sorted(set(memo.risk_flags))),
            blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
            data_quality_safe=quality_safe,
            disagreement_ratio=(
                None
                if candidate.deliberation is None
                else candidate.deliberation.disagreement_ratio
            ),
            technical_alignment=technical_alignment,
            features=features,
            rationale=memo.rationale,
            as_of=candidate.context.created_at,
        )


def _technical_alignment(intent: SignalIntent, features: FeatureSnapshot) -> float:
    if intent == SignalIntent.FLAT:
        return 0.0
    expected = 1 if intent == SignalIntent.LONG else -1
    checks: list[bool] = []
    if features.ema_8 is not None and features.ema_21 is not None:
        checks.append((features.ema_8 > features.ema_21) == (expected == 1))
    if features.vwap is not None:
        checks.append((features.close > features.vwap) == (expected == 1))
    if features.macd_histogram is not None:
        checks.append((features.macd_histogram > 0) == (expected == 1))
    if features.rsi_14 is not None:
        checks.append((features.rsi_14 >= 50) == (expected == 1))
    if features.supertrend_direction is not None:
        checks.append(features.supertrend_direction == expected)
    if not checks:
        return 0.0
    return sum(1 for check in checks if check) / len(checks)
