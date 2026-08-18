from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantIntent(str, Enum):
    MARKET_SCAN = "market_scan"
    STATUS = "status"
    RISK_STATUS = "risk_status"
    POSITIONS = "positions"
    EXPLAIN = "explain"
    RESEARCH_REQUEST = "research_request"
    PAPER_CONTROL = "paper_control"
    LIVE_CONTROL = "live_control"


class CommandPrivilege(str, Enum):
    READ_ONLY = "read_only"
    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"


_INTENT_PRIVILEGE = {
    AssistantIntent.MARKET_SCAN: CommandPrivilege.READ_ONLY,
    AssistantIntent.STATUS: CommandPrivilege.READ_ONLY,
    AssistantIntent.RISK_STATUS: CommandPrivilege.READ_ONLY,
    AssistantIntent.POSITIONS: CommandPrivilege.READ_ONLY,
    AssistantIntent.EXPLAIN: CommandPrivilege.READ_ONLY,
    AssistantIntent.RESEARCH_REQUEST: CommandPrivilege.RESEARCH,
    AssistantIntent.PAPER_CONTROL: CommandPrivilege.PAPER,
    AssistantIntent.LIVE_CONTROL: CommandPrivilege.LIVE,
}


class AssistantCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    intent: AssistantIntent
    privilege: CommandPrivilege
    parameters: dict[str, str] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("command timestamp must be timezone-aware")
        return value


class AssistantCommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: str
    intent: AssistantIntent
    accepted: bool
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    risk_gate_required: bool = False
    human_live_approval_required: bool = False
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def completed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("command result timestamp must be timezone-aware")
        return value


class CommandHandler(Protocol):
    async def handle(self, command: AssistantCommand) -> dict[str, Any]: ...


class CommandRouter:
    """Deterministic intent/privilege boundary for a Jarvis-like AURA surface.

    This router is deliberately not an LLM parser and has no broker dependency.
    Voice or LLM frontends may produce text, but the final command must pass this
    auditable privilege layer. `LIVE_CONTROL` is rejected unless the caller has
    explicitly enabled live commands, and even then the result only requests a
    governed action; it does not submit a broker order.
    """

    def __init__(
        self,
        handlers: dict[AssistantIntent, CommandHandler] | None = None,
        *,
        allow_research: bool = True,
        allow_paper_control: bool = True,
        allow_live_control: bool = False,
    ) -> None:
        self.handlers = dict(handlers or {})
        self.allow_research = allow_research
        self.allow_paper_control = allow_paper_control
        self.allow_live_control = allow_live_control

    def parse(self, text: str, *, created_at: datetime | None = None) -> AssistantCommand:
        raw = " ".join(text.strip().split())
        if not raw:
            raise ValueError("command text cannot be empty")
        intent, parameters = _classify(raw)
        return AssistantCommand(
            command_id=f"cmd:{uuid.uuid4()}",
            raw_text=raw,
            intent=intent,
            privilege=_INTENT_PRIVILEGE[intent],
            parameters=parameters,
            created_at=created_at or datetime.now(UTC),
        )

    async def execute(self, command: AssistantCommand) -> AssistantCommandResult:
        denial = self._denial(command)
        if denial is not None:
            return AssistantCommandResult(
                command_id=command.command_id,
                intent=command.intent,
                accepted=False,
                summary=denial,
                risk_gate_required=command.privilege in {CommandPrivilege.PAPER, CommandPrivilege.LIVE},
                human_live_approval_required=command.privilege == CommandPrivilege.LIVE,
                completed_at=datetime.now(UTC),
            )
        handler = self.handlers.get(command.intent)
        if handler is None:
            return AssistantCommandResult(
                command_id=command.command_id,
                intent=command.intent,
                accepted=False,
                summary=f"no handler registered for {command.intent.value}",
                risk_gate_required=command.privilege in {CommandPrivilege.PAPER, CommandPrivilege.LIVE},
                human_live_approval_required=command.privilege == CommandPrivilege.LIVE,
                completed_at=datetime.now(UTC),
            )
        payload = await handler.handle(command)
        return AssistantCommandResult(
            command_id=command.command_id,
            intent=command.intent,
            accepted=True,
            summary=f"{command.intent.value} command handled",
            payload=payload,
            risk_gate_required=command.privilege in {CommandPrivilege.PAPER, CommandPrivilege.LIVE},
            human_live_approval_required=command.privilege == CommandPrivilege.LIVE,
            completed_at=datetime.now(UTC),
        )

    def _denial(self, command: AssistantCommand) -> str | None:
        if command.privilege == CommandPrivilege.RESEARCH and not self.allow_research:
            return "research commands are disabled"
        if command.privilege == CommandPrivilege.PAPER and not self.allow_paper_control:
            return "paper-control commands are disabled"
        if command.privilege == CommandPrivilege.LIVE and not self.allow_live_control:
            return "live-control commands are disabled; explicit live governance is required"
        return None


def _classify(text: str) -> tuple[AssistantIntent, dict[str, str]]:
    normalized = text.lower()
    parameters: dict[str, str] = {}
    symbol_match = re.search(r"\b(?:symbol|for)\s+([a-z0-9_.:/-]+)", normalized)
    if symbol_match:
        parameters["symbol"] = symbol_match.group(1).upper()

    if any(phrase in normalized for phrase in ("live trade", "live order", "real money", "go live")):
        return AssistantIntent.LIVE_CONTROL, parameters
    if any(phrase in normalized for phrase in ("paper start", "paper stop", "paper trade", "demo control")):
        return AssistantIntent.PAPER_CONTROL, parameters
    if any(phrase in normalized for phrase in ("research", "test hypothesis", "generate strategy", "optimize")):
        parameters.setdefault("request", text)
        return AssistantIntent.RESEARCH_REQUEST, parameters
    if any(phrase in normalized for phrase in ("risk status", "risk", "drawdown", "exposure")):
        return AssistantIntent.RISK_STATUS, parameters
    if any(phrase in normalized for phrase in ("positions", "open trades", "portfolio")):
        return AssistantIntent.POSITIONS, parameters
    if any(phrase in normalized for phrase in ("explain", "why trade", "why signal")):
        return AssistantIntent.EXPLAIN, parameters
    if any(phrase in normalized for phrase in ("scan", "opportunity", "market brief")):
        return AssistantIntent.MARKET_SCAN, parameters
    if any(phrase in normalized for phrase in ("status", "health", "system")):
        return AssistantIntent.STATUS, parameters
    return AssistantIntent.STATUS, {"query": text}
