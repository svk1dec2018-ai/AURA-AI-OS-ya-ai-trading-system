from __future__ import annotations

import asyncio
import os

from aura.agents.openai_provider import OpenAIReasoningProvider
from aura.ai.openai_chat_compatible import GeminiOpenAIChatClient
from aura.ai.openai_responses import OpenAIResponsesClient


class _CompatibleReasoningProvider(OpenAIReasoningProvider):
    provider_id = "compatible"
    responses_provider_id = "compatible"

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 90.0,
        request_limiter: asyncio.Semaphore | None = None,
        max_candles: int = 80,
    ) -> None:
        client = OpenAIResponsesClient(
            model_id,
            api_key=api_key,
            provider_id=self.responses_provider_id,
            timeout_seconds=timeout_seconds,
            request_limiter=request_limiter,
        )
        super().__init__(
            model_id,
            client=client,
            timeout_seconds=timeout_seconds,
            request_limiter=request_limiter,
            max_candles=max_candles,
        )


class GroqReasoningProvider(_CompatibleReasoningProvider):
    provider_id = "groq"
    responses_provider_id = "groq"


class OpenRouterReasoningProvider(_CompatibleReasoningProvider):
    provider_id = "openrouter"
    responses_provider_id = "openrouter"


class GeminiReasoningProvider(OpenAIReasoningProvider):
    provider_id = "gemini"

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 90.0,
        request_limiter: asyncio.Semaphore | None = None,
        max_candles: int = 80,
    ) -> None:
        client = GeminiOpenAIChatClient(
            model_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            request_limiter=request_limiter,
        )
        super().__init__(
            model_id,
            client=client,
            timeout_seconds=timeout_seconds,
            request_limiter=request_limiter,
            max_candles=max_candles,
        )


def build_groq_providers_from_env() -> tuple[GroqReasoningProvider, ...]:
    return _build_provider_group(
        model_env="AURA_GROQ_MODELS",
        key_env="GROQ_API_KEY",
        timeout_env="AURA_GROQ_TIMEOUT_SECONDS",
        concurrency_env="AURA_GROQ_MAX_CONCURRENCY",
        provider_type=GroqReasoningProvider,
    )



def build_gemini_providers_from_env() -> tuple[GeminiReasoningProvider, ...]:
    raw = os.getenv("AURA_GEMINI_MODELS", "")
    models = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not models:
        return ()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key.strip():
        return ()
    timeout = float(os.getenv("AURA_GEMINI_TIMEOUT_SECONDS", "90"))
    max_concurrency = _positive_int_env("AURA_GEMINI_MAX_CONCURRENCY", default=2)
    limiter = asyncio.Semaphore(max_concurrency)
    return tuple(
        GeminiReasoningProvider(
            model,
            api_key=api_key,
            timeout_seconds=timeout,
            request_limiter=limiter,
        )
        for model in models
    )

def build_openrouter_providers_from_env() -> tuple[OpenRouterReasoningProvider, ...]:
    return _build_provider_group(
        model_env="AURA_OPENROUTER_MODELS",
        key_env="OPENROUTER_API_KEY",
        timeout_env="AURA_OPENROUTER_TIMEOUT_SECONDS",
        concurrency_env="AURA_OPENROUTER_MAX_CONCURRENCY",
        provider_type=OpenRouterReasoningProvider,
    )


def _build_provider_group(
    *,
    model_env: str,
    key_env: str,
    timeout_env: str,
    concurrency_env: str,
    provider_type: type[_CompatibleReasoningProvider],
) -> tuple[_CompatibleReasoningProvider, ...]:
    raw = os.getenv(model_env, "")
    models = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not models:
        return ()
    api_key = os.getenv(key_env, "")
    if not api_key.strip():
        return ()
    timeout = float(os.getenv(timeout_env, "90"))
    max_concurrency = _positive_int_env(concurrency_env, default=2)
    limiter = asyncio.Semaphore(max_concurrency)
    return tuple(
        provider_type(
            model,
            api_key=api_key,
            timeout_seconds=timeout,
            request_limiter=limiter,
        )
        for model in models
    )


def _positive_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
