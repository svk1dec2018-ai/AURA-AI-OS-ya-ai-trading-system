from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Mapping

from aura.runtime.opportunity_radar import OpportunityRadarSnapshot


class ReadDomain(str, Enum):
    OPPORTUNITIES = "opportunities"
    PORTFOLIO = "portfolio"
    RISK = "risk"
    AGENTS = "agents"
    DATA = "data"
    BROKERS = "brokers"
    SYSTEM = "system"
    RESEARCH = "research"


@dataclass(frozen=True, slots=True)
class PublishedReadModel:
    domain: ReadDomain
    source: str
    observed_at: datetime
    received_at: datetime
    max_age: timedelta
    payload: dict[str, Any]
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class ReadModelView:
    domain: ReadDomain
    available: bool
    stale: bool
    source: str | None
    observed_at: datetime | None
    age_seconds: float | None
    checksum_sha256: str | None
    payload: dict[str, Any] | None
    reason: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "available": self.available,
            "stale": self.stale,
            "source": self.source,
            "observed_at": None if self.observed_at is None else self.observed_at.isoformat(),
            "age_seconds": self.age_seconds,
            "checksum_sha256": self.checksum_sha256,
            "payload": copy.deepcopy(self.payload),
            "reason": self.reason,
        }


class OperatorReadModel:
    """Thread-safe owner dashboard read model with freshness/provenance gates.

    This store has no execution methods. Publishers must supply already-governed,
    JSON-serializable snapshots. Consumers receive stale data as unavailable and
    never receive a stale payload, preventing a UI or voice command from treating
    an old market/risk snapshot as current decision evidence.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[ReadDomain, PublishedReadModel] = {}

    def publish(
        self,
        domain: ReadDomain,
        payload: Mapping[str, Any],
        *,
        source: str,
        observed_at: datetime,
        max_age: timedelta,
        received_at: datetime | None = None,
    ) -> PublishedReadModel:
        source = source.strip()
        if not source:
            raise ValueError("read-model source is required")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        received = received_at or datetime.now(UTC)
        if received.tzinfo is None or received.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        if observed_at > received:
            raise ValueError("read-model observation cannot be from the future")

        normalized = _json_copy(payload)
        checksum = hashlib.sha256(_canonical_json(normalized)).hexdigest()
        record = PublishedReadModel(
            domain=domain,
            source=source,
            observed_at=observed_at,
            received_at=received,
            max_age=max_age,
            payload=normalized,
            checksum_sha256=checksum,
        )
        with self._lock:
            previous = self._records.get(domain)
            if previous is not None and observed_at < previous.observed_at:
                raise ValueError("read-model observations cannot move backwards in time")
            self._records[domain] = record
        return record

    def publish_opportunity_radar(
        self,
        snapshot: OpportunityRadarSnapshot,
        *,
        source: str = "aura-opportunity-radar",
        max_age: timedelta = timedelta(minutes=2),
        received_at: datetime | None = None,
    ) -> PublishedReadModel:
        if snapshot.as_of is None:
            raise ValueError("cannot publish an empty opportunity radar without an as_of time")
        return self.publish(
            ReadDomain.OPPORTUNITIES,
            snapshot.to_json_dict(),
            source=source,
            observed_at=snapshot.as_of,
            max_age=max_age,
            received_at=received_at,
        )

    def get(
        self,
        domain: ReadDomain,
        *,
        as_of: datetime | None = None,
    ) -> ReadModelView:
        evaluation_time = as_of or datetime.now(UTC)
        if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        with self._lock:
            record = self._records.get(domain)
            if record is None:
                return ReadModelView(
                    domain=domain,
                    available=False,
                    stale=False,
                    source=None,
                    observed_at=None,
                    age_seconds=None,
                    checksum_sha256=None,
                    payload=None,
                    reason="source not attached",
                )
            age = evaluation_time - record.observed_at
            if age < timedelta(0):
                return ReadModelView(
                    domain=domain,
                    available=False,
                    stale=False,
                    source=record.source,
                    observed_at=record.observed_at,
                    age_seconds=age.total_seconds(),
                    checksum_sha256=record.checksum_sha256,
                    payload=None,
                    reason="observation is from the future relative to evaluation time",
                )
            stale = age > record.max_age
            return ReadModelView(
                domain=domain,
                available=not stale,
                stale=stale,
                source=record.source,
                observed_at=record.observed_at,
                age_seconds=age.total_seconds(),
                checksum_sha256=record.checksum_sha256,
                payload=None if stale else copy.deepcopy(record.payload),
                reason="snapshot is stale" if stale else None,
            )

    def overview(self, *, as_of: datetime | None = None) -> dict[str, Any]:
        return {
            domain.value: self.get(domain, as_of=as_of).to_json_dict()
            for domain in ReadDomain
        }


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_copy(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("read-model payload must be finite JSON data") from exc
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("read-model payload must be a JSON object")
    return decoded
