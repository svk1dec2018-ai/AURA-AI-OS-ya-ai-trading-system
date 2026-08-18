from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from aura.agents.models import AgentRole, AgentRound, CEODecisionMemo
from aura.domain.models import SignalIntent


class AgentPolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reasons: tuple[str, ...]
    hard_block_flags: tuple[str, ...] = ()
    missing_required_roles: tuple[AgentRole, ...] = ()
    failed_required_roles: tuple[AgentRole, ...] = ()
    unavailable_required_roles: tuple[AgentRole, ...] = ()


@dataclass(slots=True, frozen=True)
class AgentRiskPolicy:
    """Pre-execution evidence policy for multi-agent CEO candidates.

    This policy validates the integrity/availability of the intelligence round.
    It does not replace the independent financial RiskEngine. An allowed CEO
    candidate must still pass portfolio sizing, exposure, drawdown and kill-switch
    controls before an order can exist.
    """

    required_roles: frozenset[AgentRole] = frozenset(
        {
            AgentRole.HTF_BIAS,
            AgentRole.SMC_ICT,
            AgentRole.TECHNICAL,
            AgentRole.VOLUME_VWAP,
            AgentRole.REGIME,
        }
    )
    unavailable_evidence_flags: frozenset[str] = frozenset(
        {
            "htf_missing",
            "htf_warmup",
            "htf_open_candle",
            "htf_symbol_mismatch",
            "htf_future_data",
            "structure_warmup",
            "technical_warmup",
            "volume_warmup",
            "missing_volume",
            "regime_warmup",
        }
    )
    hard_block_flags: frozenset[str] = frozenset(
        {
            "market_data_quality_block",
            "htf_future_data",
            "options_future_data",
            "cross_market_future",
            "execution_quality_future",
            "macro_contradiction",
            "macro_future_data",
            "spread_too_wide",
            "estimated_slippage_too_high",
            "top_of_book_liquidity_too_low",
        }
    )
    min_directional_supporters: int = 2

    def __post_init__(self) -> None:
        if self.min_directional_supporters < 1:
            raise ValueError("min_directional_supporters must be at least 1")

    def evaluate(
        self,
        *,
        round_result: AgentRound,
        memo: CEODecisionMemo,
    ) -> AgentPolicyDecision:
        evidence_roles = {item.role for item in round_result.evidence}
        failed_roles = {failure.role for failure in round_result.failures}
        missing_required = tuple(sorted(self.required_roles - evidence_roles, key=lambda role: role.value))
        failed_required = tuple(sorted(self.required_roles & failed_roles, key=lambda role: role.value))

        unavailable_roles = {
            item.role
            for item in round_result.evidence
            if item.role in self.required_roles
            and set(item.risk_flags) & self.unavailable_evidence_flags
        }
        unavailable_required = tuple(sorted(unavailable_roles, key=lambda role: role.value))

        observed_flags = {flag for item in round_result.evidence for flag in item.risk_flags}
        observed_flags.update(memo.risk_flags)
        blocked_flags = tuple(sorted(observed_flags & self.hard_block_flags))

        reasons: list[str] = []
        if missing_required:
            reasons.append(
                "missing required specialist roles: "
                + ", ".join(role.value for role in missing_required)
            )
        if failed_required:
            reasons.append(
                "required specialist failures: "
                + ", ".join(role.value for role in failed_required)
            )
        if unavailable_required:
            reasons.append(
                "required specialist evidence unavailable: "
                + ", ".join(role.value for role in unavailable_required)
            )
        if blocked_flags:
            reasons.append("hard-block evidence flags: " + ", ".join(blocked_flags))
        if not memo.quorum_met:
            reasons.append("CEO quorum not met")
        if memo.intent != SignalIntent.FLAT and len(memo.supporting_agents) < self.min_directional_supporters:
            reasons.append(
                "insufficient directional specialist support: "
                f"{len(memo.supporting_agents)} < {self.min_directional_supporters}"
            )

        return AgentPolicyDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            hard_block_flags=blocked_flags,
            missing_required_roles=missing_required,
            failed_required_roles=failed_required,
            unavailable_required_roles=unavailable_required,
        )
