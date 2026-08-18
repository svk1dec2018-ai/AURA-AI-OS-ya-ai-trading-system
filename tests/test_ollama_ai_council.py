from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.ai_council import AICouncilConfig, build_ollama_ai_council
from aura.agents.models import AgentContext, AgentRole
from aura.agents.ollama_provider import (
    OllamaHTTPError,
    OllamaReasoningProvider,
    build_ollama_providers_from_env,
)
from aura.agents.team import build_default_agent_team
from aura.domain.models import NormalizedCandle, SignalIntent
from aura.knowledge.firewall import KnowledgeFirewall


def _context() -> AgentContext:
    start = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
    candles = tuple(
        NormalizedCandle(
            symbol="BTC-USD",
            venue="COINBASE_PUBLIC",
            timeframe="1m",
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal("100.5") + Decimal(index),
            volume=Decimal(10 + index),
            closed=True,
        )
        for index in range(30)
    )
    return AgentContext(
        correlation_id="ai-test:btc:1m",
        symbol="BTC-USD",
        decision_timeframe="1m",
        candles=candles,
        created_at=candles[-1].close_time,
        metadata={"runtime": "unit_test"},
    )


@pytest.mark.asyncio
async def test_ollama_provider_uses_structured_output_and_discards_raw_thinking() -> None:
    captured: dict = {}

    async def fake_transport(url: str, payload: dict, timeout: float) -> dict:
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {
            "message": {
                "role": "assistant",
                "thinking": "private chain of thought that AURA must never persist",
                "content": json.dumps(
                    {
                        "intent": "LONG",
                        "confidence": 0.74,
                        "thesis": "trend and participation are aligned",
                        "risk_flags": ["watch_volatility"],
                        "key_factors": ["higher closes", "positive participation"],
                        "invalidation": "closed candle breaks prior swing low",
                    }
                ),
            },
            "done": True,
        }

    provider = OllamaReasoningProvider(
        "local-reasoner",
        think="high",
        transport=fake_transport,
    )
    analysis = await provider.analyze(role=AgentRole.TECHNICAL, context=_context())

    assert analysis.intent == SignalIntent.LONG
    assert analysis.confidence == pytest.approx(0.74)
    assert analysis.features["internal_thinking_discarded"] is True
    assert "private chain of thought" not in json.dumps(analysis.model_dump(mode="json"))
    assert captured["url"].endswith("/api/chat")
    assert captured["payload"]["think"] == "high"
    assert isinstance(captured["payload"]["format"], dict)
    assert captured["payload"]["stream"] is False


@pytest.mark.asyncio
async def test_ollama_provider_omits_think_by_default() -> None:
    captured: dict = {}

    async def fake_transport(url: str, payload: dict, timeout: float) -> dict:
        captured["payload"] = payload
        return _valid_ollama_response()

    provider = OllamaReasoningProvider("non-thinking-model", transport=fake_transport)
    analysis = await provider.analyze(role=AgentRole.TECHNICAL, context=_context())

    assert "think" not in captured["payload"]
    assert analysis.features["ollama_compatibility_mode"] is False


@pytest.mark.asyncio
async def test_ollama_provider_retries_http_400_in_compatible_json_mode() -> None:
    payloads: list[dict] = []

    async def fake_transport(url: str, payload: dict, timeout: float) -> dict:
        payloads.append(payload)
        if len(payloads) == 1:
            raise OllamaHTTPError(
                400,
                json.dumps({"error": "model does not support thinking"}),
            )
        return _valid_ollama_response()

    provider = OllamaReasoningProvider(
        "mixed-capability-model",
        think=True,
        transport=fake_transport,
    )
    analysis = await provider.analyze(role=AgentRole.TECHNICAL, context=_context())

    assert len(payloads) == 2
    assert payloads[0]["think"] is True
    assert isinstance(payloads[0]["format"], dict)
    assert "think" not in payloads[1]
    assert payloads[1]["format"] == "json"
    assert analysis.features["ollama_compatibility_mode"] is True


@pytest.mark.asyncio
async def test_ollama_shared_request_limiter_prevents_model_queue_flooding() -> None:
    active = 0
    peak = 0

    async def fake_transport(url: str, payload: dict, timeout: float) -> dict:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _valid_ollama_response()

    limiter = asyncio.Semaphore(1)
    providers = (
        OllamaReasoningProvider(
            "model-a",
            transport=fake_transport,
            request_limiter=limiter,
        ),
        OllamaReasoningProvider(
            "model-b",
            transport=fake_transport,
            request_limiter=limiter,
        ),
    )

    await asyncio.gather(
        providers[0].analyze(role=AgentRole.TECHNICAL, context=_context()),
        providers[1].analyze(role=AgentRole.REGIME, context=_context()),
    )

    assert peak == 1


def test_multi_model_council_creates_independent_role_agents() -> None:
    providers = (
        OllamaReasoningProvider("model-a", transport=_unused_transport),
        OllamaReasoningProvider("model-b", transport=_unused_transport),
    )
    agents = build_ollama_ai_council(
        providers,
        config=AICouncilConfig(
            roles=(AgentRole.TECHNICAL, AgentRole.SMC_ICT, AgentRole.MACRO_SENTIMENT),
            opinions_per_role=2,
        ),
    )
    assert len(agents) == 6
    assert len({item.agent_id for item in agents}) == 6
    assert {item.role for item in agents} == {
        AgentRole.TECHNICAL,
        AgentRole.SMC_ICT,
        AgentRole.MACRO_SENTIMENT,
    }
    assert {item.provider.model_id for item in agents} == {"model-a", "model-b"}


def test_default_team_auto_adds_env_ai_without_broker_credentials(monkeypatch) -> None:
    monkeypatch.setenv("AURA_OLLAMA_MODELS", "model-a,model-b")
    monkeypatch.setenv("AURA_AI_ROLES", "technical,smc_ict,macro_sentiment,regime")
    monkeypatch.setenv("AURA_AI_OPINIONS_PER_ROLE", "1")
    team = build_default_agent_team(KnowledgeFirewall())
    assert len(team.agents) == 14
    ai_agents = [item for item in team.agents if item.agent_id.startswith("ai-council:")]
    assert len(ai_agents) == 4
    assert team.orchestrator.timeout_seconds == 240.0


def test_env_ollama_providers_share_safe_local_defaults(monkeypatch) -> None:
    monkeypatch.setenv("AURA_OLLAMA_MODELS", "model-a,model-b")
    providers = build_ollama_providers_from_env()

    assert len(providers) == 2
    assert all(item.think is False for item in providers)
    assert all(item.timeout_seconds == 120.0 for item in providers)
    assert providers[0].request_limiter is providers[1].request_limiter


def _valid_ollama_response() -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": json.dumps(
                {
                    "intent": "FLAT",
                    "confidence": 0.55,
                    "thesis": "evidence is mixed",
                    "risk_flags": [],
                    "key_factors": ["mixed evidence"],
                    "invalidation": "",
                }
            ),
        },
        "done": True,
    }


async def _unused_transport(url: str, payload: dict, timeout: float) -> dict:
    raise AssertionError("transport should not be called in council construction test")
