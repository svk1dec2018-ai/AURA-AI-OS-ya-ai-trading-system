from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Protocol

from aura.fleet.bus import EventBus
from aura.fleet.events import FleetEvent, FleetEventKind
from aura.fleet.manifest import FleetService, ServiceRole

from .features import extract_candle_features
from .ml_linear import LinearProbabilityArtifact


class PrimeRoleHandler(Protocol):
    ready: bool
    detail: str

    async def __call__(self, stream: str, event: FleetEvent) -> None: ...


class PassiveRoleHandler:
    def __init__(self, detail: str) -> None:
        self.ready = False
        self.detail = detail

    async def __call__(self, stream: str, event: FleetEvent) -> None:
        return


class FeatureRoleHandler:
    ready = True
    detail = "closed-candle feature extraction active"

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    async def __call__(self, stream: str, event: FleetEvent) -> None:
        if event.kind is not FleetEventKind.MARKET_CANDLE:
            return
        candles = event.payload.get("candles")
        if not isinstance(candles, list):
            raise ValueError("market.candle event requires candles list")
        symbol = str(event.symbol or event.payload.get("symbol") or "").strip()
        timeframe = str(event.payload.get("timeframe") or "").strip()
        if not symbol or not timeframe:
            raise ValueError("market.candle event requires symbol and timeframe")
        vector = extract_candle_features(
            candles,
            symbol=symbol,
            timeframe=timeframe,
        )
        output = FleetEvent(
            kind=FleetEventKind.FEATURE_VECTOR,
            source="aura-features",
            symbol=symbol,
            venue=event.venue,
            correlation_id=event.correlation_id or event.event_id,
            occurred_at=event.occurred_at,
            payload=vector.model_dump(mode="json"),
        )
        await self.bus.publish("features.vector", output)


class LinearModelRoleHandler:
    def __init__(self, bus: EventBus, model_path: Path | None) -> None:
        self.bus = bus
        self.model_path = model_path
        self.model: LinearProbabilityArtifact | None = None
        if model_path is not None and model_path.is_file():
            self.model = LinearProbabilityArtifact.load(model_path)
            self.ready = True
            self.detail = f"linear model loaded: {self.model.model_key}:{self.model.version}"
        else:
            self.ready = False
            self.detail = "no AURA_PRIME_LINEAR_MODEL configured"

    async def __call__(self, stream: str, event: FleetEvent) -> None:
        if event.kind is not FleetEventKind.FEATURE_VECTOR or self.model is None:
            return
        features = event.payload.get("features")
        if not isinstance(features, dict):
            raise ValueError("features.vector event requires features object")
        vote = self.model.vote({str(key): float(value) for key, value in features.items()})
        output = FleetEvent(
            kind=FleetEventKind.ML_VOTE,
            source="aura-ml",
            symbol=event.symbol,
            venue=event.venue,
            correlation_id=event.correlation_id or event.event_id,
            occurred_at=event.occurred_at,
            payload={
                "model_key": vote.model_key,
                "intent": vote.intent.value,
                "confidence": vote.confidence,
                "reliability": vote.reliability,
                "calibration": vote.calibration,
                "research_only": vote.research_only,
                "execution_authority": False,
            },
        )
        await self.bus.publish("ml.vote", output)


class MonitorRoleHandler:
    ready = True
    detail = "event telemetry aggregation active"

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    async def __call__(self, stream: str, event: FleetEvent) -> None:
        self.counts[stream] += 1
        self.counts[event.kind.value] += 1


def build_prime_role_handler(
    service: FleetService,
    bus: EventBus,
) -> PrimeRoleHandler:
    if service.role is ServiceRole.FEATURES:
        return FeatureRoleHandler(bus)
    if service.role is ServiceRole.ML:
        raw_path = os.environ.get("AURA_PRIME_LINEAR_MODEL", "").strip()
        return LinearModelRoleHandler(bus, Path(raw_path) if raw_path else None)
    if service.role is ServiceRole.MONITOR:
        return MonitorRoleHandler()

    return PassiveRoleHandler(
        "Prime role handler pending explicit business wiring; "
        "service heartbeat does not imply business readiness"
    )
