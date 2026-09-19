from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ServiceRole(str, Enum):
    API = "api"
    DATA = "data"
    FEATURES = "features"
    ML = "ml"
    AGENTS = "agents"
    NEWS = "news"
    RISK = "risk"
    EXECUTOR = "executor"
    MONITOR = "monitor"


class FleetService(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str = Field(min_length=1, max_length=80)
    role: ServiceRole
    port: int = Field(ge=1024, le=65535)
    subscribes: tuple[str, ...] = ()
    publishes: tuple[str, ...] = ()
    restartable: bool = True
    financial_authority: bool = False


AURA_FLEET: tuple[FleetService, ...] = (
    FleetService(
        service_id="aura-api",
        role=ServiceRole.API,
        port=9100,
        subscribes=("system.health", "execution.fill", "agents.verdict", "ml.vote"),
        publishes=("owner.command",),
    ),
    FleetService(
        service_id="aura-data",
        role=ServiceRole.DATA,
        port=9101,
        publishes=("market.tick", "market.candle"),
    ),
    FleetService(
        service_id="aura-features",
        role=ServiceRole.FEATURES,
        port=9102,
        subscribes=("market.candle",),
        publishes=("features.vector",),
    ),
    FleetService(
        service_id="aura-ml",
        role=ServiceRole.ML,
        port=9103,
        subscribes=("features.vector",),
        publishes=("ml.vote",),
    ),
    FleetService(
        service_id="aura-agents",
        role=ServiceRole.AGENTS,
        port=9104,
        subscribes=("features.vector", "ml.vote", "news.signal"),
        publishes=("agents.verdict",),
    ),
    FleetService(
        service_id="aura-news",
        role=ServiceRole.NEWS,
        port=9105,
        publishes=("news.signal",),
    ),
    FleetService(
        service_id="aura-risk",
        role=ServiceRole.RISK,
        port=9106,
        subscribes=("agents.verdict", "execution.fill"),
        publishes=("risk.decision",),
        financial_authority=True,
    ),
    FleetService(
        service_id="aura-executor",
        role=ServiceRole.EXECUTOR,
        port=9107,
        subscribes=("risk.decision",),
        publishes=("execution.order", "execution.fill"),
        financial_authority=True,
    ),
    FleetService(
        service_id="aura-monitor",
        role=ServiceRole.MONITOR,
        port=9108,
        subscribes=(
            "market.tick",
            "features.vector",
            "ml.vote",
            "agents.verdict",
            "risk.decision",
            "execution.fill",
        ),
        publishes=("system.health",),
    ),
)


def fleet_manifest() -> tuple[dict[str, object], ...]:
    return tuple(item.model_dump(mode="json") for item in AURA_FLEET)


def validate_fleet_manifest() -> tuple[str, ...]:
    errors: list[str] = []
    ids = [item.service_id for item in AURA_FLEET]
    ports = [item.port for item in AURA_FLEET]
    if len(ids) != len(set(ids)):
        errors.append("fleet service ids must be unique")
    if len(ports) != len(set(ports)):
        errors.append("fleet service ports must be unique")
    missing = set(ServiceRole) - {item.role for item in AURA_FLEET}
    if missing:
        errors.append("fleet is missing roles: " + ",".join(sorted(item.value for item in missing)))
    for item in AURA_FLEET:
        should_have_authority = item.role in {ServiceRole.RISK, ServiceRole.EXECUTOR}
        if item.financial_authority != should_have_authority:
            errors.append(f"invalid financial authority declaration: {item.service_id}")
    return tuple(errors)
