from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

from aura.execution.reconciliation import ReconciliationReport
from aura.risk.engine import RiskEngine


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class ComponentHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str
    status: HealthStatus
    detail: str
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("health timestamps must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class SupervisorSnapshot:
    components: tuple[ComponentHealth, ...]
    risk_kill_switch: bool
    risk_kill_switch_reason: str

    @property
    def healthy(self) -> bool:
        return not self.risk_kill_switch and all(
            component.status != HealthStatus.CRITICAL for component in self.components
        )


class OperationalSupervisor:
    """Central operational health authority that may freeze, but never auto-unfreeze, risk."""

    def __init__(self, risk_engine: RiskEngine) -> None:
        self.risk_engine = risk_engine
        self._components: dict[str, ComponentHealth] = {}

    def record_component(
        self,
        *,
        component: str,
        status: HealthStatus,
        detail: str,
        observed_at: datetime,
    ) -> ComponentHealth:
        if not component.strip():
            raise ValueError("component name is required")
        health = ComponentHealth(
            component=component.strip(),
            status=status,
            detail=detail,
            observed_at=observed_at,
        )
        self._components[health.component] = health
        if status == HealthStatus.CRITICAL:
            self.risk_engine.engage_kill_switch(
                f"operational health critical: {health.component}: {health.detail}"
            )
        return health

    def assess_feed_freshness(
        self,
        *,
        component: str,
        last_event_at: datetime,
        now: datetime,
        max_age: timedelta,
    ) -> ComponentHealth:
        if last_event_at.tzinfo is None or last_event_at.utcoffset() is None:
            raise ValueError("last_event_at must be timezone-aware")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if max_age < timedelta(0):
            raise ValueError("max_age cannot be negative")
        age = now - last_event_at
        if age < timedelta(0):
            return self.record_component(
                component=component,
                status=HealthStatus.CRITICAL,
                detail=f"feed timestamp is {abs(age)} in the future",
                observed_at=now,
            )
        if age > max_age:
            return self.record_component(
                component=component,
                status=HealthStatus.CRITICAL,
                detail=f"feed stale by {age}; allowed {max_age}",
                observed_at=now,
            )
        return self.record_component(
            component=component,
            status=HealthStatus.HEALTHY,
            detail=f"feed age {age} within {max_age}",
            observed_at=now,
        )

    def record_reconciliation(
        self,
        report: ReconciliationReport,
        *,
        observed_at: datetime,
    ) -> ComponentHealth:
        if report.should_freeze_new_orders:
            detail = "; ".join(
                f"{issue.issue_type.value}:{issue.key}" for issue in report.issues[:3]
            )
            if len(report.issues) > 3:
                detail = f"{detail}; +{len(report.issues) - 3} more"
            return self.record_component(
                component="broker_reconciliation",
                status=HealthStatus.CRITICAL,
                detail=detail or "critical reconciliation divergence",
                observed_at=observed_at,
            )
        return self.record_component(
            component="broker_reconciliation",
            status=HealthStatus.HEALTHY,
            detail="broker/local financial state matches",
            observed_at=observed_at,
        )

    def snapshot(self) -> SupervisorSnapshot:
        return SupervisorSnapshot(
            components=tuple(
                self._components[name] for name in sorted(self._components)
            ),
            risk_kill_switch=self.risk_engine.kill_switch,
            risk_kill_switch_reason=self.risk_engine.kill_switch_reason,
        )
