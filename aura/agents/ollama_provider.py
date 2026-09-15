from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from aura.agents.models import (
    AgentContext,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.agents.providers import ProviderAnalysis, ReasoningProvider
from aura.ai.free_models import configured_ollama_model_ids, parse_ollama_keep_alive
from aura.domain.models import SignalIntent

JsonTransport = Callable[[str, dict[str, Any], float], Awaitable[dict[str, Any]]]


class OllamaProviderError(RuntimeError):
    pass


class OllamaHTTPError(OllamaProviderError):
    """HTTP failure returned by the local Ollama API."""

    def __init__(self, status_code: int, response_body: str = "") -> None:
        self.status_code = status_code
        self.response_body = response_body
        detail = _ollama_error_detail(response_body)
        suffix = f": {detail}" if detail else ""
        super().__init__(f"Ollama HTTP {status_code}{suffix}")


class _StructuredDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str = Field(min_length=1, max_length=1200)
    risk_flags: tuple[str, ...] = ()
    key_factors: tuple[str, ...] = ()
    invalidation: str = Field(default="", max_length=700)


_ROLE_MANDATES: dict[AgentRole, str] = {
    AgentRole.HTF_BIAS: "Judge higher-timeframe directional bias and structural alignment.",
    AgentRole.SMC_ICT: "Judge liquidity sweeps, BOS/CHoCH-like structure, displacement and imbalance evidence.",
    AgentRole.TECHNICAL: "Judge technical trend, momentum, volatility and mean-reversion evidence.",
    AgentRole.VOLUME_VWAP: "Judge participation, volume behavior, VWAP context and price acceptance/rejection.",
    AgentRole.FORECAST: "Judge probabilistic forward direction and uncertainty; abstain when uncertainty is high.",
    AgentRole.OPTIONS_VOLATILITY: "Judge options/IV/OI/Greeks evidence and volatility risk; do not invent missing flow.",
    AgentRole.MACRO_SENTIMENT: "Judge only timestamp-safe macro/news/sentiment evidence supplied in context.",
    AgentRole.CROSS_MARKET: "Judge cross-market confirmations/divergences and intermarket consistency.",
    AgentRole.REGIME: "Judge trend/chop/volatility regime and whether directional conviction is justified.",
    AgentRole.EXECUTION_QUALITY: "Judge spread, liquidity, slippage and execution conditions; abstain if data is missing.",
}


class OllamaReasoningProvider(ReasoningProvider):
    """Local/free Ollama reasoning adapter with structured, auditable conclusions.

    Models may use internal thinking, but AURA deliberately discards the provider's
    raw thinking field and stores only the validated conclusion. This keeps the
    audit journal concise and avoids treating hidden reasoning text as evidence.
    """

    provider_id = "ollama"

    def __init__(
        self,
        model_id: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120.0,
        think: bool | str = False,
        keep_alive: str | int = 0,
        transport: JsonTransport | None = None,
        max_candles: int = 80,
        request_limiter: asyncio.Semaphore | None = None,
    ) -> None:
        model_id = model_id.strip()
        if not model_id:
            raise ValueError("Ollama model_id is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_candles < 10:
            raise ValueError("max_candles must be at least 10")
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.think = think
        self.keep_alive = parse_ollama_keep_alive(keep_alive)
        self.transport = transport or _default_json_transport
        self.max_candles = max_candles
        self.request_limiter = request_limiter

    async def analyze(self, *, role: AgentRole, context: AgentContext) -> ProviderAnalysis:
        payload = self._payload(role, context)
        response, compatibility_mode = await self._request(payload)
        message = response.get("message")
        if not isinstance(message, dict):
            raise OllamaProviderError("Ollama response missing message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaProviderError("Ollama response missing structured content")
        try:
            parsed = _StructuredDecision.model_validate_json(content)
        except Exception as exc:
            raise OllamaProviderError("Ollama returned invalid structured decision") from exc

        latest = context.candles[-1]
        source = EvidenceSource(
            source_id=f"ai:{self.provider_id}:{self.model_id}:{role.value}:{context.correlation_id}",
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
                "internal_thinking_discarded": True,
                "ollama_compatibility_mode": compatibility_mode,
                "context_created_at": context.created_at.isoformat(),
            },
        )

    async def _request(
        self,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        if self.request_limiter is None:
            return await self._request_with_compatibility(payload)
        async with self.request_limiter:
            return await self._request_with_compatibility(payload)

    async def _request_with_compatibility(
        self,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        url = f"{self.base_url}/api/chat"
        try:
            response = await self.transport(url, payload, self.timeout_seconds)
            return response, False
        except OllamaHTTPError as exc:
            if exc.status_code != 400:
                raise

        # Older Ollama builds may only accept format="json", while models such
        # as Llama 3.1 and Qwen 2.5 do not support the `think` capability. Keep
        # the full schema in the prompt, remove thinking, and retry once using
        # the broad JSON mode so mixed local model councils remain compatible.
        fallback = dict(payload)
        fallback.pop("think", None)
        fallback["format"] = "json"
        try:
            response = await self.transport(url, fallback, self.timeout_seconds)
        except OllamaProviderError as exc:
            raise OllamaProviderError(
                f"Ollama compatibility retry failed: {exc}"
            ) from exc
        return response, True

    def _payload(self, role: AgentRole, context: AgentContext) -> dict[str, Any]:
        schema = _StructuredDecision.model_json_schema()
        prompt = {
            "role": role.value,
            "mandate": _ROLE_MANDATES[role],
            "rules": [
                "Use only supplied point-in-time context; never assume future data.",
                "Return FLAT when evidence is insufficient or contradictory.",
                "Do not size positions, place orders, change risk limits, or claim guaranteed accuracy.",
                "Do not reveal chain-of-thought. Return only the requested structured conclusion.",
                "List concise key factors and a concrete invalidation condition when directional.",
            ],
            "market": _market_context(context, max_candles=self.max_candles),
            "output_schema": schema,
        }
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are one independent specialist inside AURA AI OS. "
                        "Reason privately, stay skeptical, and emit only a concise JSON decision."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, separators=(",", ":"), default=str),
                },
            ],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.15},
            "keep_alive": self.keep_alive,
        }
        if self.think is not False:
            payload["think"] = self.think
        return payload


def build_ollama_providers_from_env() -> tuple[OllamaReasoningProvider, ...]:
    """Build configured local AI models without requiring broker credentials."""

    models = configured_ollama_model_ids()
    if not models:
        return ()
    base_url = os.getenv("AURA_OLLAMA_URL", "http://127.0.0.1:11434")
    timeout = float(os.getenv("AURA_OLLAMA_TIMEOUT_SECONDS", "120"))
    think = _parse_think(os.getenv("AURA_OLLAMA_THINK", "false"))
    keep_alive = parse_ollama_keep_alive(os.getenv("AURA_OLLAMA_KEEP_ALIVE", "0"))
    max_concurrency = _positive_int_env("AURA_OLLAMA_MAX_CONCURRENCY", default=1)
    request_limiter = asyncio.Semaphore(max_concurrency)
    return tuple(
        OllamaReasoningProvider(
            model,
            base_url=base_url,
            timeout_seconds=timeout,
            think=think,
            keep_alive=keep_alive,
            request_limiter=request_limiter,
        )
        for model in models
    )


def _market_context(context: AgentContext, *, max_candles: int) -> dict[str, Any]:
    candles = context.candles[-max_candles:]
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
            for candle in candles
        ],
        "metadata": metadata,
    }


def _compact(value: Any, *, max_chars: int = 8000) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    try:
        encoded = json.dumps(value, separators=(",", ":"), default=str)
    except TypeError:
        encoded = json.dumps(str(value))
    if len(encoded) <= max_chars:
        return json.loads(encoded)
    return {"truncated": True, "preview": encoded[:max_chars]}


def _parse_think(value: str) -> bool | str:
    normalized = value.strip().lower()
    if normalized in {"false", "0", "off", "no"}:
        return False
    if normalized in {"true", "1", "on", "yes"}:
        return True
    if normalized in {"low", "medium", "high"}:
        return normalized
    raise ValueError("AURA_OLLAMA_THINK must be true/false/low/medium/high")


def _positive_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


async def _default_json_transport(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    return await asyncio.to_thread(_sync_json_post, url, payload, timeout_seconds)


def _sync_json_post(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        raise OllamaHTTPError(exc.code, body) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise OllamaProviderError(f"Ollama request failed: {exc}") from exc
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaProviderError("Ollama returned non-JSON HTTP response") from exc
    if not isinstance(result, dict):
        raise OllamaProviderError("Ollama response must be a JSON object")
    return result


def _ollama_error_detail(response_body: str, *, max_chars: int = 500) -> str:
    if not response_body.strip():
        return ""
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        detail = response_body.strip()
    else:
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            detail = payload["error"].strip()
        else:
            detail = json.dumps(payload, separators=(",", ":"), default=str)
    return detail[:max_chars]
