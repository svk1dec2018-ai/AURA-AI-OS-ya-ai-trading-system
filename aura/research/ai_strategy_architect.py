from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aura.research.autonomy import ResearchHypothesis
from aura.research.lifecycle import StrategyStage, StrategyVersion
from aura.research.strategy_factory import (
    AutonomousStrategyFactory,
    ExitPrimitive,
    StrategyBlueprint,
    StrategyPrimitive,
)

JsonTransport = Callable[[str, dict[str, Any], float], Awaitable[dict[str, Any]]]


class AIStrategyArchitectError(RuntimeError):
    pass


class StrategyArchitectureProposal(BaseModel):
    """Strict AI output: components only, never code/risk sizing/broker actions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    design_name: str = Field(min_length=1, max_length=120)
    thesis: str = Field(min_length=1, max_length=1200)
    entries: tuple[StrategyPrimitive, ...] = Field(min_length=1, max_length=3)
    confirmations: tuple[StrategyPrimitive, ...] = Field(default=(), max_length=5)
    exits: tuple[ExitPrimitive, ...] = Field(min_length=1, max_length=3)
    rationale: str = Field(min_length=1, max_length=1600)
    falsification_conditions: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def unique_components(self) -> StrategyArchitectureProposal:
        if len(set(self.entries)) != len(self.entries):
            raise ValueError("AI strategy entries must be unique")
        if len(set(self.confirmations)) != len(self.confirmations):
            raise ValueError("AI strategy confirmations must be unique")
        if len(set(self.exits)) != len(self.exits):
            raise ValueError("AI strategy exits must be unique")
        return self


class OllamaStrategyCandidateGenerator:
    """CandidateGenerator adapter for AURA's governed autonomous research loop.

    Local AI chooses only allow-listed strategy components. The deterministic
    strategy factory owns numeric parameters and rejects invalid primitive roles.
    Returned candidates always begin at RESEARCH and therefore cannot deploy live.
    """

    def __init__(
        self,
        model_ids: tuple[str, ...] | list[str],
        *,
        factory: AutonomousStrategyFactory | None = None,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 45.0,
        think: bool | str = True,
        transport: JsonTransport | None = None,
    ) -> None:
        models = tuple(dict.fromkeys(item.strip() for item in model_ids if item.strip()))
        if not models:
            raise ValueError("at least one strategy architect model is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.model_ids = models
        self.factory = factory or AutonomousStrategyFactory()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.think = think
        self.transport = transport or _default_json_transport
        self._proposals: dict[str, StrategyArchitectureProposal] = {}
        self._proposal_models: dict[str, str] = {}

    async def generate(
        self,
        hypothesis: ResearchHypothesis,
        *,
        feedback: tuple[str, ...],
        candidate_index: int,
    ) -> StrategyVersion:
        if candidate_index < 0:
            raise ValueError("candidate_index cannot be negative")
        model_id = self.model_ids[candidate_index % len(self.model_ids)]
        proposal = await self._propose(model_id, hypothesis, feedback, candidate_index)
        blueprint = self.factory.propose_from_components(
            hypothesis,
            entries=proposal.entries,
            confirmations=proposal.confirmations,
            exits=proposal.exits,
            feedback=feedback,
            candidate_index=candidate_index,
            design_tag=f"ai:{model_id}:{proposal.design_name}",
        )
        strategy = self.factory.register_blueprint(
            blueprint,
            candidate_index=candidate_index,
        )
        if strategy.stage != StrategyStage.RESEARCH:
            raise AIStrategyArchitectError("AI strategy candidate escaped RESEARCH stage")
        self._proposals[strategy.content_hash] = proposal
        self._proposal_models[strategy.content_hash] = model_id
        return strategy

    def blueprint_for(self, strategy: StrategyVersion) -> StrategyBlueprint:
        return self.factory.blueprint_for(strategy)

    def proposal_for(self, strategy: StrategyVersion) -> StrategyArchitectureProposal:
        try:
            return self._proposals[strategy.content_hash]
        except KeyError as exc:
            raise KeyError(f"unknown AI strategy proposal: {strategy.content_hash}") from exc

    def model_for(self, strategy: StrategyVersion) -> str:
        try:
            return self._proposal_models[strategy.content_hash]
        except KeyError as exc:
            raise KeyError(f"unknown AI strategy model: {strategy.content_hash}") from exc

    async def _propose(
        self,
        model_id: str,
        hypothesis: ResearchHypothesis,
        feedback: tuple[str, ...],
        candidate_index: int,
    ) -> StrategyArchitectureProposal:
        schema = StrategyArchitectureProposal.model_json_schema()
        request = {
            "hypothesis": hypothesis.model_dump(mode="json"),
            "candidate_index": candidate_index,
            "measured_feedback_from_previous_candidates": list(feedback),
            "allowed_entry_primitives": [
                item.value for item in AutonomousStrategyFactory._ENTRY_POOL
            ],
            "allowed_confirmation_primitives": [
                item.value for item in AutonomousStrategyFactory._CONFIRMATION_POOL
            ],
            "allowed_exit_primitives": [
                item.value for item in AutonomousStrategyFactory._EXIT_POOL
            ],
            "rules": [
                "Design one falsifiable trading hypothesis using only allowed primitives.",
                "Do not emit Python, formulas outside the schema, broker actions, leverage, quantity, position sizing, risk percentages, loss limits or kill-switch controls.",
                "Use previous measured failure feedback when present; do not claim guaranteed accuracy.",
                "Reason privately and return only the requested JSON object.",
            ],
            "output_schema": schema,
        }
        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are AURA's research-only Strategy Architect. Propose alpha structure; "
                        "you have zero execution, sizing, risk-engine or live-approval authority."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(request, separators=(",", ":"), default=str),
                },
            ],
            "stream": False,
            "think": self.think,
            "format": schema,
            "options": {"temperature": 0.35},
        }
        response = await self.transport(
            f"{self.base_url}/api/chat",
            payload,
            self.timeout_seconds,
        )
        message = response.get("message")
        if not isinstance(message, dict):
            raise AIStrategyArchitectError("Ollama architect response missing message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AIStrategyArchitectError("Ollama architect response missing content")
        try:
            return StrategyArchitectureProposal.model_validate_json(content)
        except Exception as exc:
            raise AIStrategyArchitectError("invalid structured AI strategy proposal") from exc


def build_ollama_strategy_candidate_generator_from_env(
    *,
    factory: AutonomousStrategyFactory | None = None,
) -> OllamaStrategyCandidateGenerator | None:
    raw = os.getenv("AURA_STRATEGY_ARCHITECT_MODELS") or os.getenv("AURA_OLLAMA_MODELS", "")
    models = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not models:
        return None
    return OllamaStrategyCandidateGenerator(
        models,
        factory=factory,
        base_url=os.getenv("AURA_OLLAMA_URL", "http://127.0.0.1:11434"),
        timeout_seconds=float(os.getenv("AURA_OLLAMA_TIMEOUT_SECONDS", "45")),
        think=_parse_think(os.getenv("AURA_OLLAMA_THINK", "true")),
    )


def _parse_think(value: str) -> bool | str:
    normalized = value.strip().lower()
    if normalized in {"false", "0", "off", "no"}:
        return False
    if normalized in {"true", "1", "on", "yes"}:
        return True
    if normalized in {"low", "medium", "high"}:
        return normalized
    raise ValueError("AURA_OLLAMA_THINK must be true/false/low/medium/high")


async def _default_json_transport(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    return await asyncio.to_thread(_sync_json_post, url, payload, timeout_seconds)


def _sync_json_post(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise AIStrategyArchitectError(f"Ollama architect request failed: {exc}") from exc
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIStrategyArchitectError("Ollama architect returned non-JSON HTTP response") from exc
    if not isinstance(result, dict):
        raise AIStrategyArchitectError("Ollama architect response must be a JSON object")
    return result
