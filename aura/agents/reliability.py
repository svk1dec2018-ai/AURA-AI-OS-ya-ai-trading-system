from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aura.agents.models import AgentContext, AgentEvidence, AgentRole, AgentRound
from aura.domain.models import SignalIntent


class AgentReliabilityObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    role: AgentRole
    model_key: str | None = None
    market: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    predicted_intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    realized_intent: SignalIntent
    decision_time: datetime
    outcome_observed_at: datetime

    @field_validator("decision_time", "outcome_observed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reliability timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_directional_observation(self) -> AgentReliabilityObservation:
        directional = {SignalIntent.LONG, SignalIntent.SHORT}
        if self.predicted_intent not in directional:
            raise ValueError("reliability observations require a directional prediction")
        if self.realized_intent not in directional:
            raise ValueError("reliability observations require a material directional outcome")
        if self.outcome_observed_at <= self.decision_time:
            raise ValueError("reliability outcome must be observed after the prediction")
        return self

    @property
    def correct(self) -> bool:
        return self.predicted_intent == self.realized_intent


@dataclass(slots=True, frozen=True)
class AgentReliabilitySummary:
    key: str
    market: str
    regime: str
    samples: int
    hit_rate: float
    brier_score: float
    posterior_reliability: float
    vote_weight: float


class AgentReliabilityTracker:
    """Learn contextual vote reliability from forward-observed outcomes.

    Reliability is tracked independently for agent identities and AI model/role
    combinations. This prevents a model that is strong at one mandate (for example
    macro) from borrowing that reputation for a different mandate (for example
    execution quality). The tracker has no execution authority.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        prior_mean: float = 0.50,
        prior_strength: float = 20.0,
        min_vote_weight: float = 0.50,
        max_vote_weight: float = 1.50,
    ) -> None:
        if not 0 <= prior_mean <= 1:
            raise ValueError("prior_mean must be between 0 and 1")
        if prior_strength <= 0:
            raise ValueError("prior_strength must be positive")
        if not 0 < min_vote_weight <= 1 <= max_vote_weight:
            raise ValueError("vote-weight bounds must contain 1.0")
        self.path = path
        self.prior_mean = prior_mean
        self.prior_strength = prior_strength
        self.min_vote_weight = min_vote_weight
        self.max_vote_weight = max_vote_weight
        self._observations: dict[str, AgentReliabilityObservation] = {}
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    def record(self, observation: AgentReliabilityObservation) -> bool:
        existing = self._observations.get(observation.observation_id)
        if existing is not None:
            if existing != observation:
                raise ValueError(
                    f"reliability observation_id collision: {observation.observation_id}"
                )
            return False
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(observation.model_dump_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        self._observations[observation.observation_id] = observation
        return True

    def record_evidence_outcome(
        self,
        evidence: AgentEvidence,
        *,
        observation_prefix: str,
        market: str,
        regime: str,
        realized_intent: SignalIntent,
        decision_time: datetime,
        outcome_observed_at: datetime,
    ) -> bool:
        if evidence.intent not in {SignalIntent.LONG, SignalIntent.SHORT}:
            return False
        provider_id = evidence.features.get("provider_id")
        model_id = evidence.features.get("model_id")
        model_key = (
            f"{provider_id}:{model_id}"
            if isinstance(provider_id, str)
            and provider_id
            and isinstance(model_id, str)
            and model_id
            else None
        )
        return self.record(
            AgentReliabilityObservation(
                observation_id=f"{observation_prefix}:{evidence.agent_id}",
                agent_id=evidence.agent_id,
                role=evidence.role,
                model_key=model_key,
                market=market,
                regime=regime,
                predicted_intent=evidence.intent,
                confidence=evidence.confidence,
                realized_intent=realized_intent,
                decision_time=decision_time,
                outcome_observed_at=outcome_observed_at,
            )
        )

    def vote_weight(
        self,
        evidence: AgentEvidence,
        *,
        market: str,
        regime: str,
    ) -> float:
        agent_summary = self.summarize_agent(
            evidence.agent_id,
            market=market,
            regime=regime,
        )
        reliabilities = [agent_summary.posterior_reliability]
        provider_id = evidence.features.get("provider_id")
        model_id = evidence.features.get("model_id")
        if (
            isinstance(provider_id, str)
            and provider_id
            and isinstance(model_id, str)
            and model_id
        ):
            model_summary = self.summarize_model_role(
                f"{provider_id}:{model_id}",
                role=evidence.role,
                market=market,
                regime=regime,
            )
            reliabilities.append(model_summary.posterior_reliability)
        reliability = sum(reliabilities) / len(reliabilities)
        return max(
            self.min_vote_weight,
            min(self.max_vote_weight, 0.5 + reliability),
        )

    def summarize_agent(
        self,
        agent_id: str,
        *,
        market: str,
        regime: str,
    ) -> AgentReliabilitySummary:
        items = [
            item
            for item in self._observations.values()
            if item.agent_id == agent_id
            and item.market == market
            and item.regime == regime
        ]
        return self._summary(agent_id, market, regime, items)

    def summarize_model(
        self,
        model_key: str,
        *,
        market: str,
        regime: str,
    ) -> AgentReliabilitySummary:
        """Aggregate one model across roles. Prefer summarize_model_role for routing."""
        items = [
            item
            for item in self._observations.values()
            if item.model_key == model_key
            and item.market == market
            and item.regime == regime
        ]
        return self._summary(model_key, market, regime, items)

    def summarize_model_role(
        self,
        model_key: str,
        *,
        role: AgentRole,
        market: str,
        regime: str | None,
    ) -> AgentReliabilitySummary:
        """Summarize a model for one specialist mandate.

        `regime=None` intentionally aggregates all observed regimes within the
        market. The adaptive router uses that as a fallback until enough exact
        regime evidence exists.
        """
        items = [
            item
            for item in self._observations.values()
            if item.model_key == model_key
            and item.role == role
            and item.market == market
            and (regime is None or item.regime == regime)
        ]
        regime_key = regime if regime is not None else "*"
        return self._summary(
            f"{model_key}:{role.value}",
            market,
            regime_key,
            items,
        )

    def leaderboard(
        self,
        *,
        market: str,
        regime: str,
    ) -> tuple[AgentReliabilitySummary, ...]:
        agent_ids = sorted(
            {
                item.agent_id
                for item in self._observations.values()
                if item.market == market and item.regime == regime
            }
        )
        summaries = [
            self.summarize_agent(agent_id, market=market, regime=regime)
            for agent_id in agent_ids
        ]
        summaries.sort(
            key=lambda item: (-item.vote_weight, -item.samples, item.key)
        )
        return tuple(summaries)

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    def _summary(
        self,
        key: str,
        market: str,
        regime: str,
        items: list[AgentReliabilityObservation],
    ) -> AgentReliabilitySummary:
        if not items:
            reliability = self.prior_mean
            return AgentReliabilitySummary(
                key=key,
                market=market,
                regime=regime,
                samples=0,
                hit_rate=0.0,
                brier_score=0.25,
                posterior_reliability=reliability,
                vote_weight=max(
                    self.min_vote_weight,
                    min(self.max_vote_weight, 0.5 + reliability),
                ),
            )
        correct = [float(item.correct) for item in items]
        hit_rate = sum(correct) / len(items)
        brier = sum(
            (item.confidence - realized) ** 2
            for item, realized in zip(items, correct, strict=True)
        ) / len(items)
        calibration = max(0.0, 1.0 - brier)
        empirical = 0.60 * hit_rate + 0.40 * calibration
        posterior = (
            self.prior_strength * self.prior_mean + len(items) * empirical
        ) / (self.prior_strength + len(items))
        weight = max(
            self.min_vote_weight,
            min(self.max_vote_weight, 0.5 + posterior),
        )
        return AgentReliabilitySummary(
            key=key,
            market=market,
            regime=regime,
            samples=len(items),
            hit_rate=hit_rate,
            brier_score=brier,
            posterior_reliability=posterior,
            vote_weight=weight,
        )

    def _load(self) -> None:
        assert self.path is not None
        if not self.path.exists():
            return
        for line_number, raw in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw.strip():
                continue
            try:
                item = AgentReliabilityObservation.model_validate_json(raw)
            except Exception as exc:
                raise ValueError(
                    f"invalid agent reliability record at line {line_number}"
                ) from exc
            existing = self._observations.get(item.observation_id)
            if existing is not None and existing != item:
                raise ValueError(
                    f"reliability observation collision at line {line_number}"
                )
            self._observations[item.observation_id] = item


def reliability_market_key(context: AgentContext) -> str:
    configured = context.metadata.get("market")
    if isinstance(configured, str) and configured.strip():
        return configured.strip().upper()
    return context.candles[-1].venue.upper()


def reliability_regime_key(round_result: AgentRound, context: AgentContext) -> str:
    for evidence in round_result.evidence:
        if evidence.role != AgentRole.REGIME:
            continue
        value = evidence.features.get("regime")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    configured = context.metadata.get("regime")
    if isinstance(configured, str) and configured.strip():
        return configured.strip().lower()
    return "unknown"
