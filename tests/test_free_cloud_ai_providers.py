from __future__ import annotations

import json

import pytest

from aura.agents.compatible_cloud_providers import (
    build_gemini_providers_from_env,
    build_groq_providers_from_env,
    build_openrouter_providers_from_env,
)
from aura.ai.openai_chat_compatible import GeminiOpenAIChatClient
from aura.ai.openai_responses import OpenAIResponsesClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_id", "model_id", "expected_url"),
    (
        ("groq", "openai/gpt-oss-20b", "https://api.groq.com/openai/v1/responses"),
        ("openrouter", "openrouter/free", "https://openrouter.ai/api/v1/responses"),
    ),
)
async def test_fixed_responses_provider_endpoints(
    provider_id: str,
    model_id: str,
    expected_url: str,
) -> None:
    captured: dict = {}

    async def transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {
            "id": "resp_1",
            "model": model_id,
            "output_text": json.dumps({"status": "ok"}),
        }

    client = OpenAIResponsesClient(
        model_id,
        api_key="test-key-never-log",
        provider_id=provider_id,
        transport=transport,
    )
    result = await client.structured(
        system_prompt="Return JSON.",
        user_payload={"ping": True},
        schema_name="status",
        schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )
    assert captured["url"] == expected_url
    assert captured["headers"]["Authorization"] == "Bearer test-key-never-log"
    assert result.output == {"status": "ok"}


@pytest.mark.asyncio
async def test_gemini_uses_fixed_google_openai_compatible_endpoint() -> None:
    captured: dict = {}

    async def transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {
            "id": "gemini_1",
            "model": "gemini-3.8-flash",
            "choices": [
                {"message": {"content": json.dumps({"status": "ok"})}}
            ],
        }

    client = GeminiOpenAIChatClient(
        "gemini-3.8-flash",
        api_key="gemini-test-key",
        transport=transport,
    )
    result = await client.structured(
        system_prompt="Return JSON.",
        user_payload={"ping": True},
        schema_name="status",
        schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )
    assert (
        captured["url"]
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert result.output == {"status": "ok"}


@pytest.mark.parametrize(
    ("model_env", "key_env", "builder", "model"),
    (
        ("AURA_GROQ_MODELS", "GROQ_API_KEY", build_groq_providers_from_env, "openai/gpt-oss-20b"),
        ("AURA_OPENROUTER_MODELS", "OPENROUTER_API_KEY", build_openrouter_providers_from_env, "openrouter/free"),
        ("AURA_GEMINI_MODELS", "GEMINI_API_KEY", build_gemini_providers_from_env, "gemini-3.8-flash"),
    ),
)
def test_cloud_provider_keys_are_not_reused_from_openai(
    monkeypatch,
    model_env,
    key_env,
    builder,
    model,
) -> None:
    monkeypatch.setenv(model_env, model)
    monkeypatch.delenv(key_env, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-provider-key")
    with pytest.raises(ValueError, match=key_env):
        builder()


def test_optional_cloud_providers_are_disabled_when_model_lists_blank(monkeypatch) -> None:
    for name in (
        "AURA_GROQ_MODELS",
        "AURA_OPENROUTER_MODELS",
        "AURA_GEMINI_MODELS",
    ):
        monkeypatch.setenv(name, "")
    assert build_groq_providers_from_env() == ()
    assert build_openrouter_providers_from_env() == ()
    assert build_gemini_providers_from_env() == ()
