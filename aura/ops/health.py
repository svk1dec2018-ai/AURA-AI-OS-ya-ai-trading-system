from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(slots=True, frozen=True)
class ComponentHealth:
    component: str
    status: HealthStatus
    detail: str = ""
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.component.strip():
            raise ValueError("component name is required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(slots=True, frozen=True)
class HealthReport:
    components: tuple[ComponentHealth, ...]
    kill_switch_engaged: bool = False
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def status(self) -> HealthStatus:
        if self.kill_switch_engaged:
            return HealthStatus.UNHEALTHY
        statuses = {item.status for item in self.components}
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    @property
    def ready_for_new_risk(self) -> bool:
        return self.status == HealthStatus.HEALTHY and not self.kill_switch_engaged

    def to_json_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "ready_for_new_risk": self.ready_for_new_risk,
            "kill_switch_engaged": self.kill_switch_engaged,
            "generated_at": self.generated_at.isoformat(),
            "components": [
                {
                    "component": item.component,
                    "status": item.status.value,
                    "detail": item.detail,
                    "observed_at": item.observed_at.isoformat(),
                }
                for item in self.components
            ],
        }

    def write_atomic(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_json_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
