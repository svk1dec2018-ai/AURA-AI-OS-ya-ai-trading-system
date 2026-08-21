from __future__ import annotations

import json

import pytest

from aura.ai.ollama_structured import (
    OllamaStructuredClient,
    OllamaStructuredError,
    OllamaStructuredHTTPError,
)

SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}


@pytest.mark.asyncio
async def test_local_structured_client_uses_schema_and_resource_safe_defaults() -> None:
    captured: dict = {}

    async def transport(url: str, payload: dict, timeout: float) -> dict:
        captured.update(url=url, payload=payload, timeout=timeout)
        return {
            "model": "qwen3.5:4b",
            "message": {"content": json.dumps({"status": "ok"})},
            "done": True,
        }

    client = OllamaStructuredClient("qwen3.5:4b", transport=transport)
    response = await client.structured(
        system_prompt="Return one status object.",
        user_payload={"component": "health"},
        schema_name="health_status",
        schema=SCHEMA,
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["payload"]["format"] == SCHEMA
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["options"]["temperature"] == 0
    assert captured["payload"]["keep_alive"] == 0
    assert "think" not in captured["payload"]
    assert response.output == {"status": "ok"}
    assert response.response_id.startswith("ollama:")
    assert response.model_id == "qwen3.5:4b"


@pytest.mark.asyncio
async def test_local_response_identifier_is_deterministic_and_auditable() -> None:
    async def transport(url: str, payload: dict, timeout: float) -> dict:
        return {"message": {"content": '{"status":"same"}'}}

    client = OllamaStructuredClient("phi4-mini:3.8b", transport=transport)
    first = await client.structured(
        system_prompt="Return status.",
        user_payload={},
        schema_name="status",
        schema=SCHEMA,
    )
    second = await client.structured(
        system_prompt="Return status.",
        user_payload={},
        schema_name="status",
        schema=SCHEMA,
    )
    assert first.response_id == second.response_id


@pytest.mark.asyncio
async def test_local_client_retries_old_ollama_json_compatibility_once() -> None:
    payloads: list[dict] = []

    async def transport(url: str, payload: dict, timeout: float) -> dict:
        payloads.append(payload)
        if len(payloads) == 1:
            raise OllamaStructuredHTTPError(400, '{"error":"unsupported think"}')
        return {"message": {"content": '{"status":"ok"}'}}

    client = OllamaStructuredClient(
        "deepseek-r1:8b",
        think=True,
        transport=transport,
    )
    await client.structured(
        system_prompt="Return status.",
        user_payload={},
        schema_name="status",
        schema=SCHEMA,
    )

    assert payloads[0]["think"] is True
    assert isinstance(payloads[0]["format"], dict)
    assert "think" not in payloads[1]
    assert payloads[1]["format"] == "json"
    assert payloads[1]["keep_alive"] == 0


def test_local_client_rejects_cloud_or_credential_bearing_endpoints() -> None:
    for url in (
        "https://ollama.example.com",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434/untrusted-path",
    ):
        with pytest.raises(ValueError, match="local HTTP endpoint"):
            OllamaStructuredClient("qwen3.5:4b", base_url=url)


@pytest.mark.asyncio
async def test_local_client_rejects_non_object_structured_output() -> None:
    async def transport(url: str, payload: dict, timeout: float) -> dict:
        return {"message": {"content": "[]"}}

    client = OllamaStructuredClient("gemma3:4b", transport=transport)
    with pytest.raises(OllamaStructuredError, match="JSON object"):
        await client.structured(
            system_prompt="Return status.",
            user_payload={},
            schema_name="status",
            schema=SCHEMA,
        )
