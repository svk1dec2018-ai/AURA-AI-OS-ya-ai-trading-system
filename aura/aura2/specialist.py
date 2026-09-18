from __future__ import annotations

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import SignalIntent


class AURA2MTFSpecialist(SpecialistAgent):
    """Advisory M1-D1 consensus vote for the existing AURA CEO."""

    agent_id = "aura2:mtf-consensus:v1"
    role = AgentRole.HTF_BIAS

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        latest = context.candles[-1]
        raw = context.metadata.get("aura2_mtf")
        source = EvidenceSource(
            source_id=(
                f"aura2-mtf:{latest.venue}:{latest.symbol}:"
                f"{latest.close_time.isoformat()}"
            ),
            source_type=EvidenceSourceType.MARKET_DATA,
            observed_at=latest.close_time,
            trust_score=1.0,
            point_in_time_safe=True,
        )
        if not isinstance(raw, dict):
            return AgentEvidence(
                agent_id=self.agent_id,
                role=self.role,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                thesis="AURA 2 multi-timeframe consensus is not warm yet",
                risk_flags=("aura2_mtf_warmup",),
                sources=(source,),
                generated_at=context.created_at,
            )

        direction = str(raw.get("direction", "FLAT")).upper()
        intent = {
            "BUY": SignalIntent.LONG,
            "SELL": SignalIntent.SHORT,
        }.get(direction, SignalIntent.FLAT)
        confidence = min(
            1.0,
            max(0.0, float(raw.get("confidence", 0.0)))
            * max(0.0, float(raw.get("agreement", 0.0))),
        )
        execution_alignment = float(raw.get("execution_alignment", 0.0))
        higher_alignment = float(raw.get("higher_timeframe_alignment", 0.0))
        frame_count = int(raw.get("frame_count", 0))
        flags: list[str] = []
        if frame_count < 3:
            flags.append("aura2_mtf_partial")
        if execution_alignment < 0.50:
            flags.append("aura2_execution_tf_conflict")
        if higher_alignment < 0.50:
            flags.append("aura2_higher_tf_conflict")
        if intent == SignalIntent.FLAT:
            confidence = 0.0

        thesis = (
            f"AURA 2 MTF {direction}; regime={raw.get('regime', 'UNKNOWN')}; "
            f"agreement={float(raw.get('agreement', 0.0)):.2f}; "
            f"execution={execution_alignment:.2f}; HTF={higher_alignment:.2f}; "
            f"frames={','.join(str(item) for item in raw.get('timeframes', ())) or 'none'}"
        )
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=confidence,
            thesis=thesis,
            risk_flags=tuple(flags),
            sources=(source,),
            features={
                "aura2_mtf": raw,
                "execution_authority": False,
                "risk_authority": False,
            },
            generated_at=context.created_at,
        )
