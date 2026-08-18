from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.knowledge.firewall import KnowledgeFirewall, KnowledgeSourceType


class OptionsVolatilitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    underlying_symbol: str = Field(min_length=1)
    observed_at: datetime
    implied_volatility: float | None = Field(default=None, ge=0.0)
    iv_percentile: float | None = Field(default=None, ge=0.0, le=100.0)
    put_call_oi_ratio: float | None = Field(default=None, ge=0.0)
    put_call_volume_ratio: float | None = Field(default=None, ge=0.0)
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("options observed_at must be timezone-aware")
        return value


class CrossMarketObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    related_symbol: str = Field(min_length=1)
    observed_at: datetime
    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cross-market observed_at must be timezone-aware")
        return value


def _ema(values: list[Decimal], period: int) -> Decimal:
    if period <= 0 or len(values) < period:
        raise ValueError("EMA requires enough values")
    value = sum(values[:period], Decimal(0)) / Decimal(period)
    alpha = Decimal(2) / Decimal(period + 1)
    for item in values[period:]:
        value = alpha * item + (Decimal(1) - alpha) * value
    return value


def _abstain(
    *,
    agent_id: str,
    role: AgentRole,
    context: AgentContext,
    thesis: str,
    flag: str,
    source_type: EvidenceSourceType,
    source_id: str,
) -> AgentEvidence:
    return AgentEvidence(
        agent_id=agent_id,
        role=role,
        intent=SignalIntent.FLAT,
        confidence=0.0,
        thesis=thesis,
        risk_flags=(flag,),
        sources=(
            EvidenceSource(
                source_id=source_id,
                source_type=source_type,
                observed_at=context.candles[-1].close_time,
                trust_score=1.0,
            ),
        ),
        generated_at=context.created_at,
    )


class HigherTimeframeBiasSpecialist(SpecialistAgent):
    agent_id = "deterministic:htf_bias:v1"
    role = AgentRole.HTF_BIAS

    def __init__(self, *, fast_ema: int = 8, slow_ema: int = 21) -> None:
        if fast_ema <= 0 or slow_ema <= fast_ema:
            raise ValueError("require 0 < fast_ema < slow_ema")
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raw = context.metadata.get("htf_candles")
        if not raw:
            return self._abstain(context, "higher-timeframe candles are missing", "htf_missing")
        candles = tuple(NormalizedCandle.model_validate(item) for item in raw)
        if any(not candle.closed for candle in candles):
            return self._abstain(context, "higher-timeframe series contains open candle", "htf_open_candle")
        if any(candle.symbol != context.symbol for candle in candles):
            return self._abstain(context, "higher-timeframe symbol mismatch", "htf_symbol_mismatch")
        if any(candle.close_time > context.created_at for candle in candles):
            return self._abstain(context, "higher-timeframe series contains future data", "htf_future_data")
        if len(candles) < self.slow_ema:
            return self._abstain(
                context,
                f"higher-timeframe warmup incomplete: {len(candles)}/{self.slow_ema}",
                "htf_warmup",
            )

        closes = [candle.close for candle in candles]
        fast = _ema(closes, self.fast_ema)
        slow = _ema(closes, self.slow_ema)
        if fast > slow:
            intent = SignalIntent.LONG
            thesis = f"HTF EMA{self.fast_ema} above EMA{self.slow_ema}"
        elif fast < slow:
            intent = SignalIntent.SHORT
            thesis = f"HTF EMA{self.fast_ema} below EMA{self.slow_ema}"
        else:
            intent = SignalIntent.FLAT
            thesis = "higher-timeframe EMAs are equal"
        distance = abs(fast - slow) / closes[-1]
        confidence = min(float(distance * Decimal(100)), 1.0) if intent != SignalIntent.FLAT else 0.0
        latest = candles[-1]
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=confidence,
            thesis=thesis,
            sources=(
                EvidenceSource(
                    source_id=f"market:{latest.venue}:{latest.symbol}:{latest.timeframe}:htf",
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=latest.close_time,
                    trust_score=1.0,
                ),
            ),
            features={
                "htf_timeframe": latest.timeframe,
                "fast_ema": str(fast),
                "slow_ema": str(slow),
            },
            generated_at=context.created_at,
        )

    def _abstain(self, context: AgentContext, thesis: str, flag: str) -> AgentEvidence:
        return _abstain(
            agent_id=self.agent_id,
            role=self.role,
            context=context,
            thesis=thesis,
            flag=flag,
            source_type=EvidenceSourceType.MARKET_DATA,
            source_id=f"market:{context.symbol}:htf:missing-or-invalid",
        )


class OptionsVolatilitySpecialist(SpecialistAgent):
    """Volatility/risk advisory specialist; it does not invent directional options flow."""

    agent_id = "deterministic:options_volatility:v1"
    role = AgentRole.OPTIONS_VOLATILITY

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raw = context.metadata.get("options_snapshot")
        if raw is None:
            return self._abstain(context, "options/volatility snapshot is missing", "options_missing")
        snapshot = OptionsVolatilitySnapshot.model_validate(raw)
        expected_underlying = str(
            context.metadata.get("underlying_symbol") or context.symbol
        )
        if snapshot.underlying_symbol != expected_underlying:
            return self._abstain(
                context,
                "options underlying symbol mismatch",
                "options_symbol_mismatch",
            )
        if snapshot.observed_at > context.created_at:
            return self._abstain(context, "options snapshot is from the future", "options_future_data")

        flags: list[str] = []
        confidence_components: list[float] = []
        if snapshot.iv_percentile is not None:
            if snapshot.iv_percentile >= 80:
                flags.append("high_implied_volatility")
            elif snapshot.iv_percentile <= 20:
                flags.append("low_implied_volatility")
            confidence_components.append(
                min(abs(snapshot.iv_percentile - 50.0) / 50.0, 1.0)
            )
        if snapshot.put_call_oi_ratio is not None:
            if snapshot.put_call_oi_ratio >= 1.8 or snapshot.put_call_oi_ratio <= 0.5:
                flags.append("extreme_put_call_open_interest_ratio")
            confidence_components.append(
                min(abs(snapshot.put_call_oi_ratio - 1.0), 1.0)
            )
        if snapshot.put_call_volume_ratio is not None:
            if (
                snapshot.put_call_volume_ratio >= 1.8
                or snapshot.put_call_volume_ratio <= 0.5
            ):
                flags.append("extreme_put_call_volume_ratio")
            confidence_components.append(
                min(abs(snapshot.put_call_volume_ratio - 1.0), 1.0)
            )

        state_confidence = max(
            confidence_components,
            default=0.1 if snapshot.implied_volatility is not None else 0.0,
        )
        iv_text = (
            f"{snapshot.iv_percentile:.1f}"
            if snapshot.iv_percentile is not None
            else "n/a"
        )
        pcr_oi_text = (
            f"{snapshot.put_call_oi_ratio:.2f}"
            if snapshot.put_call_oi_ratio is not None
            else "n/a"
        )
        pcr_volume_text = (
            f"{snapshot.put_call_volume_ratio:.2f}"
            if snapshot.put_call_volume_ratio is not None
            else "n/a"
        )
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=SignalIntent.FLAT,
            confidence=state_confidence,
            thesis=(
                f"options volatility advisory: IV percentile {iv_text}, "
                f"PCR(OI) {pcr_oi_text}, PCR(volume) {pcr_volume_text}"
            ),
            risk_flags=tuple(sorted(flags)),
            sources=(
                EvidenceSource(
                    source_id=snapshot.source_id,
                    source_type=EvidenceSourceType.DERIVATIVES,
                    observed_at=snapshot.observed_at,
                    trust_score=snapshot.trust_score,
                ),
            ),
            features={
                "implied_volatility": snapshot.implied_volatility,
                "iv_percentile": snapshot.iv_percentile,
                "put_call_oi_ratio": snapshot.put_call_oi_ratio,
                "put_call_volume_ratio": snapshot.put_call_volume_ratio,
            },
            generated_at=context.created_at,
        )

    def _abstain(self, context: AgentContext, thesis: str, flag: str) -> AgentEvidence:
        return _abstain(
            agent_id=self.agent_id,
            role=self.role,
            context=context,
            thesis=thesis,
            flag=flag,
            source_type=EvidenceSourceType.DERIVATIVES,
            source_id=f"derivatives:{context.symbol}:missing-or-invalid",
        )


class CrossMarketSpecialist(SpecialistAgent):
    agent_id = "deterministic:cross_market:v1"
    role = AgentRole.CROSS_MARKET

    def __init__(self, *, min_margin: float = 0.2) -> None:
        if not 0 <= min_margin <= 1:
            raise ValueError("min_margin must be between 0 and 1")
        self.min_margin = min_margin

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        raw = context.metadata.get("cross_market_observations")
        if not raw:
            return self._abstain(context, "cross-market observations are missing", "cross_market_missing")
        observations = tuple(CrossMarketObservation.model_validate(item) for item in raw)
        if any(item.observed_at > context.created_at for item in observations):
            return self._abstain(context, "cross-market observations contain future data", "cross_market_future")

        long_score = sum(
            item.confidence * item.trust_score
            for item in observations
            if item.intent == SignalIntent.LONG
        )
        short_score = sum(
            item.confidence * item.trust_score
            for item in observations
            if item.intent == SignalIntent.SHORT
        )
        total = long_score + short_score
        margin = abs(long_score - short_score) / total if total > 0 else 0.0
        if total <= 0 or margin < self.min_margin:
            intent = SignalIntent.FLAT
            thesis = f"cross-market evidence is inconclusive; directional margin {margin:.3f}"
        else:
            intent = SignalIntent.LONG if long_score > short_score else SignalIntent.SHORT
            thesis = (
                f"cross-market evidence favors {intent.value}; long={long_score:.3f}, "
                f"short={short_score:.3f}, margin={margin:.3f}"
            )
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=min(margin, 1.0) if intent != SignalIntent.FLAT else 0.0,
            thesis=thesis,
            sources=tuple(
                EvidenceSource(
                    source_id=item.source_id,
                    source_type=EvidenceSourceType.MARKET_DATA,
                    observed_at=item.observed_at,
                    trust_score=item.trust_score,
                )
                for item in observations
            ),
            features={
                "long_score": long_score,
                "short_score": short_score,
                "related_symbols": [item.related_symbol for item in observations],
            },
            generated_at=context.created_at,
        )

    def _abstain(self, context: AgentContext, thesis: str, flag: str) -> AgentEvidence:
        return _abstain(
            agent_id=self.agent_id,
            role=self.role,
            context=context,
            thesis=thesis,
            flag=flag,
            source_type=EvidenceSourceType.MARKET_DATA,
            source_id=f"cross-market:{context.symbol}:missing-or-invalid",
        )


class KnowledgeMacroSentimentSpecialist(SpecialistAgent):
    agent_id = "knowledge:macro_sentiment:v1"
    role = AgentRole.MACRO_SENTIMENT

    def __init__(
        self,
        firewall: KnowledgeFirewall,
        *,
        claim_key: str = "market.bias",
        required_tags: tuple[str, ...] = (),
    ) -> None:
        self.firewall = firewall
        self.claim_key = claim_key
        self.required_tags = required_tags

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        bundle = self.firewall.build_bundle(
            as_of=context.created_at,
            required_tags=self.required_tags,
        )
        if not bundle.items:
            return self._abstain(context, "no trusted point-in-time macro knowledge", "macro_missing")
        if not bundle.safe_for_decision:
            keys = ",".join(item.claim_key for item in bundle.contradictions)
            return self._abstain(
                context,
                f"macro knowledge contradictions detected: {keys}",
                "macro_contradiction",
            )

        claim_items = [item for item in bundle.items if self.claim_key in item.claims]
        if not claim_items:
            return self._abstain(
                context,
                f"trusted knowledge has no structured {self.claim_key} claim",
                "macro_bias_missing",
            )
        values = {item.claims[self.claim_key].upper() for item in claim_items}
        if len(values) != 1 or next(iter(values)) not in {"LONG", "SHORT", "FLAT"}:
            return self._abstain(context, "macro bias claims are not normalized", "macro_bias_invalid")

        intent = SignalIntent(next(iter(values)))
        confidence = sum(item.confidence * item.trust_score for item in claim_items) / len(claim_items)
        source_type_map = {
            KnowledgeSourceType.NEWS: EvidenceSourceType.NEWS,
            KnowledgeSourceType.MACRO: EvidenceSourceType.MACRO,
        }
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=min(confidence, 1.0),
            thesis=f"trusted point-in-time knowledge consensus: {self.claim_key}={intent.value}",
            sources=tuple(
                EvidenceSource(
                    source_id=item.item_id,
                    source_type=source_type_map.get(item.source_type, EvidenceSourceType.RESEARCH),
                    observed_at=item.observed_at,
                    trust_score=item.trust_score,
                )
                for item in claim_items
            ),
            features={"knowledge_items": [item.item_id for item in claim_items]},
            generated_at=context.created_at,
        )

    def _abstain(self, context: AgentContext, thesis: str, flag: str) -> AgentEvidence:
        return _abstain(
            agent_id=self.agent_id,
            role=self.role,
            context=context,
            thesis=thesis,
            flag=flag,
            source_type=EvidenceSourceType.RESEARCH,
            source_id="knowledge-firewall:abstention",
        )
