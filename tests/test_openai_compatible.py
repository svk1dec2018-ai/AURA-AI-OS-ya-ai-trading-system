from __future__ import annotations

import asyncio

import pytest

from aura.ai.openai_compatible import (
    CompatibleHTTPError,
    OpenAICompatibleStructuredClient,
    normalize_compatible_base_url,
)


def test_local_compatible_gateway_needs_no_key() -> None:
    base, local = normalize_compatible_base_url("http://127.0.0.1:20128/v1")
    assert base == "http://127.0.0.1:20128/v1"
    assert local is True
    client = OpenAICompatibleStructuredClient(
        "auto/best-coding",
        base_url=base,
    )
    assert "api_key=<redacted>" in repr(client)


def test_cloud_compatible_gateway_requires_key_and_allowlist() -> None:
    with pytest.raises(ValueError, match="requires an API key"):
        OpenAICompatibleStructuredClient(
            "openrouter/free",
            base_url="https://openrouter.ai/api/v1",
        )
    with pytest.raises(ValueError, match="not allowlisted"):
        OpenAICompatibleStructuredClient(
            "model",
            base_url="https://example.com/v1",
            api_key="secret",
        )


def test_compatible_structured_response() -> None:
    calls: list[dict[str, object]] = []

    async def transport(url, payload, headers, timeout):
        calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return {
            "id": "resp-1",
            "model": "router-model",
            "choices": [
                {
                    "message": {
                        "content": '{"diagnosis":"ok","score":1}',
                    }
                }
            ],
        }

    async def scenario() -> None:
        client = OpenAICompatibleStructuredClient(
            "auto/best-coding",
            base_url="http://localhost:20128/v1",
            transport=transport,
        )
        result = await client.structured(
            system_prompt="Return valid JSON.",
            user_payload={"issue": "test"},
            schema_name="test_schema",
            schema={
                "type": "object",
                "properties": {
                    "diagnosis": {"type": "string"},
                    "score": {"type": "integer"},
                },
                "required": ["diagnosis", "score"],
                "additionalProperties": False,
            },
        )
        assert result.response_id == "resp-1"
        assert result.model_id == "router-model"
        assert result.output == {"diagnosis": "ok", "score": 1}
        assert calls[0]["url"] == "http://localhost:20128/v1/chat/completions"
        assert "Authorization" not in calls[0]["headers"]

    asyncio.run(scenario())


def test_compatible_falls_back_when_json_schema_is_unsupported() -> None:
    calls = 0

    async def transport(_url, payload, _headers, _timeout):
        nonlocal calls
        calls += 1
        if payload["response_format"]["type"] == "json_schema":
            raise CompatibleHTTPError(400, "response_format")
        return {
            "model": "fallback-model",
            "choices": [{"message": {"content": '{"ok":true}'}}],
        }

    async def scenario() -> None:
        client = OpenAICompatibleStructuredClient(
            "auto/best-coding",
            base_url="http://127.0.0.1:20128/v1",
            transport=transport,
        )
        result = await client.structured(
            system_prompt="Return JSON.",
            user_payload={},
            schema_name="fallback_schema",
            schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        )
        assert result.output == {"ok": True}
        assert result.response_id.startswith("compatible:")
        assert calls == 2

    asyncio.run(scenario())
