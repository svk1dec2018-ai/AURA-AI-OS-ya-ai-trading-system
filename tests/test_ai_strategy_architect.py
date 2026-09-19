import json
from datetime import UTC, datetime

import pytest

from aura.research.ai_strategy_architect import (
    AIStrategyArchitectError,
    OllamaStrategyCandidateGenerator,
    build_ollama_strategy_candidate_generator_from_env,
)
from aura.research.autonomy import ResearchHypothesis
from aura.research.lifecycle import StrategyStage
from aura.research.strategy_factory import (
    AutonomousStrategyFactory,
    ExitPrimitive,
    StrategyPrimitive,
)


def _hypothesis() -> ResearchHypothesis:
    return ResearchHypothesis(
        hypothesis_id="btc-trend-breakout",
        thesis="BTC trend continuation after liquidity sweep with participation confirmation",
        market_scope=("CRYPTO",),
        timeframe_scope=("1m", "5m"),
        created_at=datetime(2026, 8, 18, 11, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_ai_architect_compiles_model_components_into_research_only_strategy() -> None:
    calls = []

    async def transport(url, payload, timeout):
        calls.append((url, payload, timeout))
        proposal = {
            "design_name": "liquidity-trend",
            "thesis": "Sweep then trend continuation",
            "entries": ["liquidity_sweep", "ema_trend"],
            "confirmations": ["relative_volume", "htf_bias", "regime"],
            "exits": ["atr_stop", "risk_reward_target"],
            "rationale": "Require structure plus participation and higher-timeframe alignment.",
            "falsification_conditions": ["choppy regime", "no relative volume"],
        }
        return {"message": {"content": json.dumps(proposal), "thinking": "discard me"}}

    generator = OllamaStrategyCandidateGenerator(
        ("model-a", "model-b"),
        transport=transport,
    )
    strategy = await generator.generate(
        _hypothesis(),
        feedback=("WALK_FORWARD failed: weak ranging regime",),
        candidate_index=0,
    )

    assert strategy.stage == StrategyStage.RESEARCH
    assert generator.model_for(strategy) == "model-a"
    blueprint = generator.blueprint_for(strategy)
    assert blueprint.research_only is True
    assert blueprint.live_approved is False
    assert blueprint.entries == (
        StrategyPrimitive.EMA_TREND,
        StrategyPrimitive.LIQUIDITY_SWEEP,
    )
    assert set(blueprint.confirmations) == {
        StrategyPrimitive.RELATIVE_VOLUME,
        StrategyPrimitive.HTF_BIAS,
        StrategyPrimitive.REGIME,
    }
    assert set(blueprint.exits) == {
        ExitPrimitive.ATR_STOP,
        ExitPrimitive.RISK_REWARD_TARGET,
    }
    forbidden = ("risk_pct", "quantity", "leverage", "kill_switch", "max_daily_loss")
    assert not any(any(fragment in key.lower() for fragment in forbidden) for key in blueprint.parameters)

    user_payload = json.loads(calls[0][1]["messages"][1]["content"])
    assert "weak ranging regime" in user_payload["measured_feedback_from_previous_candidates"][0]
    assert calls[0][1]["format"]
    assert calls[0][1]["keep_alive"] == 0


@pytest.mark.asyncio
async def test_ai_architect_rotates_models_across_candidates() -> None:
    used = []

    async def transport(url, payload, timeout):
        used.append(payload["model"])
        proposal = {
            "design_name": "trend",
            "thesis": "trend",
            "entries": ["ema_trend"],
            "confirmations": ["regime"],
            "exits": ["time_stop"],
            "rationale": "simple",
            "falsification_conditions": [],
        }
        return {"message": {"content": json.dumps(proposal)}}

    generator = OllamaStrategyCandidateGenerator(("a", "b"), transport=transport)
    await generator.generate(_hypothesis(), feedback=(), candidate_index=0)
    await generator.generate(_hypothesis(), feedback=(), candidate_index=1)
    assert used == ["a", "b"]


@pytest.mark.asyncio
async def test_ai_architect_rejects_extra_risk_fields_from_model() -> None:
    async def transport(url, payload, timeout):
        proposal = {
            "design_name": "unsafe",
            "thesis": "unsafe",
            "entries": ["ema_trend"],
            "confirmations": [],
            "exits": ["atr_stop"],
            "rationale": "unsafe",
            "falsification_conditions": [],
            "risk_pct": 10,
        }
        return {"message": {"content": json.dumps(proposal)}}

    generator = OllamaStrategyCandidateGenerator(("a",), transport=transport)
    with pytest.raises(AIStrategyArchitectError):
        await generator.generate(_hypothesis(), feedback=(), candidate_index=0)


def test_safe_compiler_rejects_primitive_used_in_wrong_role() -> None:
    factory = AutonomousStrategyFactory()
    with pytest.raises(ValueError, match="not allowed as entry"):
        factory.propose_from_components(
            _hypothesis(),
            entries=(StrategyPrimitive.MACRO_NEWS,),
            confirmations=(),
            exits=(ExitPrimitive.TIME_STOP,),
            candidate_index=0,
            design_tag="bad",
        )


def test_strategy_architect_inherits_balanced_free_preset(monkeypatch) -> None:
    monkeypatch.setenv("AURA_FREE_AI_PRESET", "balanced5")
    monkeypatch.delenv("AURA_OLLAMA_MODELS", raising=False)
    monkeypatch.delenv("AURA_STRATEGY_ARCHITECT_MODELS", raising=False)

    generator = build_ollama_strategy_candidate_generator_from_env()

    assert generator is not None
    assert generator.model_ids == (
        "qwen3.5:4b",
        "deepseek-r1:8b",
        "llama3.1:8b",
        "gemma3:4b",
        "phi4-mini:3.8b",
    )
    assert generator.keep_alive == 0
