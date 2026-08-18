from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.agents.ai_council import AICouncilConfig, build_ollama_ai_council
from aura.agents.models import AgentContext, AgentRole
from aura.agents.ollama_provider import OllamaReasoningProvider
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
    assert team.orchestrator.timeout_seconds == 60.0


async def _unused_transport(url: str, payload: dict, timeout: float) -> dict:
    raise AssertionError("transport should not be called in council construction test")
