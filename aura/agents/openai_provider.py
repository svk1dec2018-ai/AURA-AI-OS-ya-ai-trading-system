from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.models import AgentContext, AgentRole, EvidenceSource, EvidenceSourceType
from aura.agents.providers import ProviderAnalysis, ReasoningProvider
from aura.ai.openai_responses import OpenAIResponsesClient
from aura.domain.models import SignalIntent


class _OpenAIDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str = Field(min_length=1, max_length=1200)
    risk_flags: tuple[str, ...]
    key_factors: tuple[str, ...]
    invalidation: str = Field(max_length=700)


_ROLE_MANDATES: dict[AgentRole, str] = {
    AgentRole.HTF_BIAS: "Judge higher-timeframe directional bias and structure.",
    AgentRole.SMC_ICT: "Judge liquidity, structure shifts, displacement and imbalance.",
    AgentRole.TECHNICAL: "Judge trend, momentum, volatility and mean reversion.",
    AgentRole.VOLUME_VWAP: "Judge participation, volume behavior and VWAP acceptance.",
    AgentRole.FORECAST: "Judge probabilistic direction and abstain under high uncertainty.",
    AgentRole.OPTIONS_VOLATILITY: "Judge supplied options, volatility and Greeks evidence.",
    AgentRole.MACRO_SENTIMENT: "Judge only supplied point-in-time macro and sentiment evidence.",
    AgentRole.CROSS_MARKET: "Judge supplied cross-market confirmation and divergence.",
    AgentRole.REGIME: "Judge trend, chop and volatility regime.",
    AgentRole.EXECUTION_QUALITY: "Judge supplied spread, liquidity and slippage evidence.",
}


class OpenAIReasoningProvider(ReasoningProvider):
    """Optional ChatGPT-class specialist using the official OpenAI Responses API.

    The adapter receives market evidence, never broker credentials or order methods.
    Strict structured output is revalidated locally before it can become advisory
    `AgentEvidence`; downstream deterministic risk and execution gates remain final.
    """

    provider_id = "openai"

    def __init__(
        self,
        model_id: str = "gpt-5.4-mini",
        *,
        client: OpenAIResponsesClient | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 90.0,
        request_limiter: asyncio.Semaphore | None = None,
        max_candles: int = 80,
    ) -> None:
        if max_candles < 10:
            raise ValueError("max_candles must be at least 10")
        self.model_id = model_id.strip()
        self.client = client or OpenAIResponsesClient(
            self.model_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            request_limiter=request_limiter,
        )
        self.max_candles = max_candles

    async def analyze(self, *, role: AgentRole, context: AgentContext) -> ProviderAnalysis:
        response = await self.client.structured(
            system_prompt=(
                "You are one advisory specialist inside AURA AI OS. Use only supplied "
                "point-in-time evidence. Return FLAT when evidence is insufficient or "
                "contradictory. Never size positions, place orders, change risk limits, "
                "request secrets, or claim guaranteed accuracy. Emit only the strict schema."
            ),
            user_payload={
                "role": role.value,
                "mandate": _ROLE_MANDATES[role],
                "market": _market_context(context, max_candles=self.max_candles),
            },
            schema_name="aura_market_specialist_decision",
            schema=_OpenAIDecision.model_json_schema(),
        )
        parsed = _OpenAIDecision.model_validate(response.output)
        latest = context.candles[-1]
        source = EvidenceSource(
            source_id=(
                f"ai:{self.provider_id}:{self.model_id}:{role.value}:"
                f"{context.correlation_id}:{response.response_id}"
            ),
            source_type=EvidenceSourceType.RESEARCH,
            observed_at=latest.close_time,
            trust_score=0.65,
            point_in_time_safe=True,
        )
        return ProviderAnalysis(
            intent=parsed.intent,
            confidence=parsed.confidence,
            thesis=parsed.thesis,
            risk_flags=tuple(sorted(set(parsed.risk_flags))),
            sources=(source,),
            features={
                "key_factors": parsed.key_factors,
                "invalidation": parsed.invalidation,
                "provider_response_id": response.response_id,
                "internal_thinking_discarded": True,
                "context_created_at": context.created_at.isoformat(),
            },
        )


def build_openai_providers_from_env() -> tuple[OpenAIReasoningProvider, ...]:
    raw = os.getenv("AURA_OPENAI_MODELS", "")
    models = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not models:
        return ()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key.strip():
        raise ValueError("AURA_OPENAI_MODELS requires OPENAI_API_KEY")
    timeout = float(os.getenv("AURA_OPENAI_TIMEOUT_SECONDS", "90"))
    max_concurrency = _positive_int_env("AURA_OPENAI_MAX_CONCURRENCY", default=2)
    limiter = asyncio.Semaphore(max_concurrency)
    return tuple(
        OpenAIReasoningProvider(
            model,
            api_key=api_key,
            timeout_seconds=timeout,
            request_limiter=limiter,
        )
        for model in models
    )


def _market_context(context: AgentContext, *, max_candles: int) -> dict[str, Any]:
    safe_metadata_keys = (
        "htf_candles",
        "options_snapshot",
        "forecast_ensemble",
        "cross_market",
        "execution_quality",
        "live_intelligence",
        "retrieved_knowledge",
        "underlying_symbol",
        "runtime",
        "venue",
    )
    metadata = {
        key: _compact(context.metadata[key])
        for key in safe_metadata_keys
        if key in context.metadata
    }
    return {
        "symbol": context.symbol,
        "timeframe": context.decision_timeframe,
        "decision_time": context.created_at.isoformat(),
        "candles": [
            {
                "t": candle.close_time.isoformat(),
                "o": str(candle.open),
                "h": str(candle.high),
                "l": str(candle.low),
                "c": str(candle.close),
                "v": str(candle.volume),
            }
            for candle in context.candles[-max_candles:]
        ],
        "metadata": metadata,
    }


def _compact(value: Any, *, max_chars: int = 8000) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, separators=(",", ":"), default=str)
    if len(encoded) <= max_chars:
        return json.loads(encoded)
    return {"truncated": True, "preview": encoded[:max_chars]}


def _positive_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
