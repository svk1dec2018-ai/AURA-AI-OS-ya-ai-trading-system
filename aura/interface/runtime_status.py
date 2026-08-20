from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class RuntimeStatusDocument(BaseModel):
    """Minimum trusted contract shared by AURA runtime status writers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    mode: str = Field(min_length=1, max_length=120)
    updated_at: datetime
    real_money_enabled: bool
    broker_orders_enabled: bool | None = None
    risk_kill_switch: bool | None = None
    risk_kill_switch_reason: str | None = Field(default=None, max_length=500)
    symbols: list[str] = Field(default_factory=list, max_length=500)
    counters: dict[str, Any] = Field(default_factory=dict)
    latest: dict[str, Any] = Field(default_factory=dict)
    radar: dict[str, Any] = Field(default_factory=dict)

    @field_validator("updated_at")
    @classmethod
    def updated_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("runtime updated_at must be timezone-aware")
        return value


class RuntimeStatusView(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    state: str
    detail: str
    mode: str | None = None
    updated_at: datetime | None = None
    age_seconds: float | None = Field(default=None, ge=0)
    market: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)
    portfolio: dict[str, Any] = Field(default_factory=dict)
    explanation: dict[str, Any] = Field(default_factory=dict)


class FileRuntimeStatusSource:
    """Reads one atomically-written runtime status file without leaking arbitrary keys."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_age_seconds: float = 120.0,
        max_bytes: int = 1024 * 1024,
    ) -> None:
        self.path = Path(path)
        if max_age_seconds <= 0:
            raise ValueError("runtime status max age must be positive")
        if not 1024 <= max_bytes <= 16 * 1024 * 1024:
            raise ValueError("runtime status max bytes must be between 1 KiB and 16 MiB")
        self.max_age_seconds = max_age_seconds
        self.max_bytes = max_bytes

    def read(self, *, now: datetime | None = None) -> RuntimeStatusView:
        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("runtime status observation time must be timezone-aware")
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return _unavailable("missing", "configured runtime status file does not exist")
        except OSError:
            return _unavailable("unreadable", "configured runtime status file is unreadable")
        if size > self.max_bytes:
            return _unavailable("oversized", "runtime status file exceeds the configured limit")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            document = RuntimeStatusDocument.model_validate(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
            return _unavailable("invalid", "runtime status failed schema validation")
        if document.real_money_enabled:
            return _unavailable(
                "unsafe_mode",
                "command center refuses runtime status that reports live money enabled",
            )
        age = max(0.0, (observed_at - document.updated_at).total_seconds())
        if age > self.max_age_seconds:
            return RuntimeStatusView(
                available=False,
                state="stale",
                detail="runtime status is older than the configured freshness limit",
                mode=document.mode,
                updated_at=document.updated_at,
                age_seconds=age,
            )
        return RuntimeStatusView(
            available=True,
            state="fresh",
            detail="validated runtime status is fresh",
            mode=document.mode,
            updated_at=document.updated_at,
            age_seconds=age,
            market=_market_payload(document),
            risk=_risk_payload(document),
            portfolio=_portfolio_payload(document),
            explanation=_explanation_payload(document),
        )


def _unavailable(state: str, detail: str) -> RuntimeStatusView:
    return RuntimeStatusView(available=False, state=state, detail=detail)


def _market_payload(document: RuntimeStatusDocument) -> dict[str, Any]:
    latest = document.latest
    payload: dict[str, Any] = {
        "symbols": [str(item)[:80] for item in document.symbols],
    }
    for key in ("symbol", "timeframe", "intent", "confidence", "actionable", "quorum_met"):
        if key in latest and _is_safe_scalar(latest[key]):
            payload[key] = _normalize_scalar(latest[key])
    opportunities = latest.get("opportunities")
    if isinstance(opportunities, list):
        payload["opportunities"] = [
            _scalar_subset(item, ("symbol", "timeframe", "intent", "confidence"))
            for item in opportunities[:50]
            if isinstance(item, dict)
        ]
    selected = document.radar.get("selected")
    if isinstance(selected, list):
        payload["selected_symbols"] = [str(item)[:80] for item in selected[:500]]
    return payload


def _risk_payload(document: RuntimeStatusDocument) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if document.risk_kill_switch is not None:
        payload["kill_switch"] = document.risk_kill_switch
        payload["kill_switch_reason"] = document.risk_kill_switch_reason
    flags = document.latest.get("risk_flags")
    if isinstance(flags, list):
        payload["risk_flags"] = [str(item)[:200] for item in flags[:100]]
    for key in ("gross_exposure", "drawdown_pct"):
        value = document.latest.get(key)
        if _is_safe_scalar(value) and value is not None and not isinstance(value, bool):
            payload[key] = _normalize_scalar(value)
    return payload


def _portfolio_payload(document: RuntimeStatusDocument) -> dict[str, Any]:
    return _scalar_subset(
        document.latest,
        ("portfolio_equity", "gross_exposure", "drawdown_pct", "orders", "fills"),
    )


def _explanation_payload(document: RuntimeStatusDocument) -> dict[str, Any]:
    payload = _scalar_subset(
        document.latest,
        ("correlation_id", "symbol", "timeframe", "intent", "confidence", "rationale"),
    )
    evidence = document.latest.get("agent_evidence")
    if isinstance(evidence, list):
        payload["agent_evidence"] = [
            _scalar_subset(item, ("agent_id", "role", "intent", "confidence", "thesis"))
            for item in evidence[:50]
            if isinstance(item, dict)
        ]
    return payload


def _scalar_subset(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        key: _normalize_scalar(source[key])
        for key in keys
        if key in source and _is_safe_scalar(source[key])
    }


def _is_safe_scalar(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, (str, int, bool, type(None)))


def _normalize_scalar(value: Any) -> Any:
    return value[:2000] if isinstance(value, str) else value
