from __future__ import annotations

import json

import pytest

from aura.agents.nvidia_provider import build_nvidia_providers_from_env
from aura.ai.openai_chat_compatible import NvidiaOpenAIChatClient


@pytest.mark.asyncio
async def test_nvidia_chat_client_uses_fixed_nvidia_endpoint() -> None:
    captured: dict = {}

    async def transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {
            "id": "chatcmpl_nvidia_1",
            "model": "openai/gpt-oss-20b",
            "choices": [
                {"message": {"content": json.dumps({"status": "ok"})}}
            ],
        }

    client = NvidiaOpenAIChatClient(
        "openai/gpt-oss-20b",
        api_key="unit-test-value",
        transport=transport,
    )
    response = await client.structured(
        system_prompt="Return a status object.",
        user_payload={"check": "health"},
        schema_name="test_status",
        schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )

    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["payload"]["model"] == "openai/gpt-oss-20b"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    assert "unit-test-value" not in repr(client)
    assert response.output == {"status": "ok"}


def test_nvidia_models_require_separate_nvidia_key(monkeypatch) -> None:
    monkeypatch.setenv("AURA_NVIDIA_MODELS", "openai/gpt-oss-20b")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "different-provider-value")
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        build_nvidia_providers_from_env()


def test_nvidia_model_builds_without_openai_key(monkeypatch) -> None:
    monkeypatch.setenv("AURA_NVIDIA_MODELS", "openai/gpt-oss-20b")
    monkeypatch.setenv("NVIDIA_API_KEY", "unit-test-value")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    providers = build_nvidia_providers_from_env()
    assert len(providers) == 1
    assert providers[0].provider_id == "nvidia"
    assert providers[0].model_id == "openai/gpt-oss-20b"
