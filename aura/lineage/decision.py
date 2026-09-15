from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.agents.deliberation import DeliberationMemo
from aura.agents.models import AgentContext, AgentRound, CEODecisionMemo
from aura.agents.risk_policy import AgentPolicyDecision
from aura.data.quality import DataQualityReport


class DecisionLineageRecord(BaseModel):
    """Immutable cryptographic fingerprint of one AURA intelligence decision.

    The record does not contain broker credentials or private model reasoning. It
    fingerprints the point-in-time inputs and each advisory decision stage so the
    same decision can later be reproduced and tampering/mismatch can be detected.
    """

    model_config = ConfigDict(frozen=True)

    lineage_version: str = "decision-lineage-v1"
    correlation_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    decision_time: datetime
    candle_count: int = Field(ge=1)
    candle_series_hash: str = Field(min_length=64, max_length=64)
    metadata_hash: str = Field(min_length=64, max_length=64)
    evidence_hash: str = Field(min_length=64, max_length=64)
    failures_hash: str = Field(min_length=64, max_length=64)
    quality_hash: str = Field(min_length=64, max_length=64)
    deliberation_hash: str = Field(min_length=64, max_length=64)
    ceo_hash: str = Field(min_length=64, max_length=64)
    agent_policy_hash: str = Field(min_length=64, max_length=64)
    source_ids: tuple[str, ...] = ()
    latest_source_observed_at: datetime | None = None
    lineage_hash: str = Field(min_length=64, max_length=64)

    @field_validator("decision_time", "latest_source_observed_at")
    @classmethod
    def timestamps_must_be_timezone_aware(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("decision lineage timestamps must be timezone-aware")
        return value

    @classmethod
    def build(
        cls,
        *,
        context: AgentContext,
        round_result: AgentRound,
        memo: CEODecisionMemo,
        data_quality: DataQualityReport | None,
        agent_policy: AgentPolicyDecision | None,
        deliberation: DeliberationMemo | None,
    ) -> DecisionLineageRecord:
        if round_result.correlation_id != context.correlation_id:
            raise ValueError("lineage round correlation_id does not match context")
        if memo.correlation_id != context.correlation_id:
            raise ValueError("lineage CEO correlation_id does not match context")

        sources = tuple(
            source
            for evidence in round_result.evidence
            for source in evidence.sources
        )
        if any(source.observed_at > context.created_at for source in sources):
            raise ValueError("decision lineage contains evidence observed after decision time")
        source_ids = tuple(sorted({source.source_id for source in sources}))
        latest_source_observed_at = (
            max(source.observed_at for source in sources) if sources else None
        )

        component_hashes = {
            "candle_series_hash": _hash(
                [candle.model_dump(mode="json") for candle in context.candles]
            ),
            "metadata_hash": _hash(context.metadata),
            "evidence_hash": _hash(
                [item.model_dump(mode="json") for item in round_result.evidence]
            ),
            "failures_hash": _hash(
                [item.model_dump(mode="json") for item in round_result.failures]
            ),
            "quality_hash": _hash(data_quality),
            "deliberation_hash": _hash(deliberation),
            "ceo_hash": _hash(memo.model_dump(mode="json")),
            "agent_policy_hash": _hash(
                agent_policy.model_dump(mode="json") if agent_policy is not None else None
            ),
        }
        lineage_payload = {
            "lineage_version": "decision-lineage-v1",
            "correlation_id": context.correlation_id,
            "symbol": context.symbol,
            "timeframe": context.decision_timeframe,
            "decision_time": context.created_at,
            "candle_count": len(context.candles),
            **component_hashes,
            "source_ids": source_ids,
            "latest_source_observed_at": latest_source_observed_at,
        }
        return cls(
            **lineage_payload,
            lineage_hash=_hash(lineage_payload),
        )

    def verify(
        self,
        *,
        context: AgentContext,
        round_result: AgentRound,
        memo: CEODecisionMemo,
        data_quality: DataQualityReport | None,
        agent_policy: AgentPolicyDecision | None,
        deliberation: DeliberationMemo | None,
    ) -> bool:
        rebuilt = type(self).build(
            context=context,
            round_result=round_result,
            memo=memo,
            data_quality=data_quality,
            agent_policy=agent_policy,
            deliberation=deliberation,
        )
        return self == rebuilt


def _hash(value: Any) -> str:
    canonical = json.dumps(
        _canonicalize(value),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _canonicalize(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=False,
            ),
        )
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cannot hash naive datetime in decision lineage")
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _canonicalize(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("cannot hash non-finite float in decision lineage")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)
