from __future__ import annotations

import asyncio
import os

from aura.agents.openai_provider import OpenAIReasoningProvider
from aura.ai.openai_chat_compatible import NvidiaOpenAIChatClient


class NvidiaReasoningProvider(OpenAIReasoningProvider):
    """NVIDIA NIM advisory specialist using NVIDIA's fixed chat endpoint."""

    provider_id = "nvidia"

    def __init__(
        self,
        model_id: str = "openai/gpt-oss-20b",
        *,
        client: NvidiaOpenAIChatClient | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 90.0,
        request_limiter: asyncio.Semaphore | None = None,
        max_candles: int = 80,
    ) -> None:
        effective_client = client or NvidiaOpenAIChatClient(
            model_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            request_limiter=request_limiter,
        )
        super().__init__(
            model_id,
            client=effective_client,
            timeout_seconds=timeout_seconds,
            request_limiter=request_limiter,
            max_candles=max_candles,
        )


def build_nvidia_providers_from_env() -> tuple[NvidiaReasoningProvider, ...]:
    raw = os.getenv("AURA_NVIDIA_MODELS", "")
    models = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not models:
        return ()
    api_key = os.getenv("NVIDIA_API_KEY", "")
    if not api_key.strip():
        return ()
    timeout = float(os.getenv("AURA_NVIDIA_TIMEOUT_SECONDS", "90"))
    max_concurrency = _positive_int_env("AURA_NVIDIA_MAX_CONCURRENCY", default=2)
    limiter = asyncio.Semaphore(max_concurrency)
    return tuple(
        NvidiaReasoningProvider(
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
