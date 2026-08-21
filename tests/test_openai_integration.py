from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import pytest

from aura.agents.models import AgentContext, AgentRole
from aura.agents.openai_provider import OpenAIReasoningProvider, build_openai_providers_from_env
from aura.agents.team import build_default_agent_team
from aura.ai.openai_responses import OpenAIResponsesClient, _safe_http_error_details
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.knowledge.firewall import KnowledgeFirewall


def _context() -> AgentContext:
    start = datetime(2026, 8, 21, 3, 0, tzinfo=UTC)
    candles = tuple(
        NormalizedCandle(
            symbol="XAUUSD",
            venue="MT5_DEMO",
            timeframe="1m",
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            open=Decimal(2400 + index),
            high=Decimal(2402 + index),
            low=Decimal(2399 + index),
            close=Decimal("2401.5") + index,
            volume=Decimal(100 + index),
        )
        for index in range(20)
    )
    return AgentContext(
        correlation_id="openai-test:xauusd",
        symbol="XAUUSD",
        decision_timeframe="1m",
        candles=candles,
        created_at=candles[-1].close_time,
        metadata={
            "runtime": {
                "mode": "unit_test",
                "api_key": "nested-provider-secret",
                "note": "password=another-hidden-value",
            },
            "unsafe_secret": "must-not-be-forwarded",
        },
    )


@pytest.mark.asyncio
async def test_responses_client_uses_official_endpoint_strict_schema_and_redacted_repr() -> None:
    captured: dict = {}

    async def transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {
            "id": "resp_test_123",
            "model": "gpt-5.4-mini-2026-03-17",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"status": "ok"}),
                        }
                    ],
                }
            ],
        }

    client = OpenAIResponsesClient(
        "gpt-5.4-mini",
        api_key="fake-api-key-must-not-leak",
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

    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert captured["payload"]["store"] is False
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    assert "fake-api-key" not in repr(client)
    assert response.output == {"status": "ok"}
    assert response.response_id == "resp_test_123"


@pytest.mark.asyncio
async def test_openai_market_provider_is_advisory_and_filters_context_metadata() -> None:
    captured: dict = {}

    async def transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured["payload"] = payload
        return {
            "id": "resp_market_1",
            "model": "gpt-5.4-mini",
            "output_text": json.dumps(
                {
                    "intent": "LONG",
                    "confidence": 0.71,
                    "thesis": "closed candles show aligned trend evidence",
                    "risk_flags": ["demo_only"],
                    "key_factors": ["higher closes"],
                    "invalidation": "close below the prior swing low",
                }
            ),
        }

    client = OpenAIResponsesClient("gpt-5.4-mini", api_key="test-key", transport=transport)
    provider = OpenAIReasoningProvider(client=client)
    analysis = await provider.analyze(role=AgentRole.TECHNICAL, context=_context())

    assert analysis.intent == SignalIntent.LONG
    assert analysis.features["internal_thinking_discarded"] is True
    assert analysis.features["provider_response_id"] == "resp_market_1"
    encoded_request = json.dumps(captured["payload"])
    assert "unsafe_secret" not in encoded_request
    assert "must-not-be-forwarded" not in encoded_request
    assert "nested-provider-secret" not in encoded_request
    assert "another-hidden-value" not in encoded_request
    assert "[REDACTED]" in encoded_request
    assert "broker" not in analysis.features


def test_openai_models_join_default_council_only_when_explicitly_configured(monkeypatch) -> None:
    monkeypatch.delenv("AURA_OLLAMA_MODELS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AURA_OPENAI_MODELS", "gpt-5.4-mini")
    monkeypatch.setenv("AURA_AI_ROLES", "technical,regime")
    providers = build_openai_providers_from_env()
    team = build_default_agent_team(KnowledgeFirewall())

    assert len(providers) == 1
    assert providers[0].provider_id == "openai"
    assert len(team.agents) == 12
    openai_agents = [
        agent for agent in team.agents if agent.agent_id.startswith("ai-council:openai:")
    ]
    assert len(openai_agents) == 2


def test_configuring_openai_models_without_key_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("AURA_OPENAI_MODELS", "gpt-5.4-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_openai_providers_from_env()


def test_http_error_classification_discards_provider_message() -> None:
    from urllib.error import HTTPError

    error = HTTPError(
        "https://api.openai.com/v1/responses",
        429,
        "Too Many Requests",
        {},
        BytesIO(
            json.dumps(
                {
                    "error": {
                        "code": "insufficient_quota",
                        "type": "insufficient_quota",
                        "message": "sensitive provider detail must be discarded",
                    }
                }
            ).encode()
        ),
    )
    assert _safe_http_error_details(error) == (
        "insufficient_quota",
        "insufficient_quota",
    )
