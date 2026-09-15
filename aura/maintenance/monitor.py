from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from aura.maintenance.authority import (
    AuthorityAction,
    AuthorityRole,
    DevelopmentAuthorityPolicy,
)
from aura.maintenance.models import MaintenanceSeverity, SystemObservation
from aura.ops.health import HealthReport
from aura.ops.health import HealthStatus as OpsHealthStatus
from aura.runtime.supervisor import (
    HealthStatus as RuntimeHealthStatus,
)
from aura.runtime.supervisor import (
    SupervisorSnapshot,
)


class MaintenanceMonitor:
    """Convert governed health state into deterministic, deduplicated incidents."""

    def __init__(self, policy: DevelopmentAuthorityPolicy | None = None) -> None:
        self.policy = policy or DevelopmentAuthorityPolicy()
        self._seen: set[str] = set()

    def observe_health_report(
        self,
        report: HealthReport,
        *,
        include_repeated: bool = False,
    ) -> tuple[SystemObservation, ...]:
        self.policy.require(AuthorityRole.MAINTENANCE_AI, AuthorityAction.MONITOR_SYSTEM)
        observations = []
        for component in report.components:
            if component.status == OpsHealthStatus.HEALTHY:
                continue
            severity = (
                MaintenanceSeverity.CRITICAL
                if component.status == OpsHealthStatus.UNHEALTHY
                else MaintenanceSeverity.DEGRADED
            )
            observations.append(
                self._observation(
                    component=component.component,
                    severity=severity,
                    summary=component.detail or f"{component.component} health degraded",
                    observed_at=component.observed_at,
                    evidence={
                        "health_status": component.status.value,
                        "kill_switch_engaged": report.kill_switch_engaged,
                        "ready_for_new_risk": report.ready_for_new_risk,
                    },
                )
            )
        return self._dedupe(tuple(observations), include_repeated=include_repeated)

    def observe_supervisor(
        self,
        snapshot: SupervisorSnapshot,
        *,
        observed_at: datetime | None = None,
        include_repeated: bool = False,
    ) -> tuple[SystemObservation, ...]:
        self.policy.require(AuthorityRole.MAINTENANCE_AI, AuthorityAction.MONITOR_SYSTEM)
        now = observed_at or datetime.now(UTC)
        observations = []
        for component in snapshot.components:
            if component.status == RuntimeHealthStatus.HEALTHY:
                continue
            severity = (
                MaintenanceSeverity.CRITICAL
                if component.status == RuntimeHealthStatus.CRITICAL
                else MaintenanceSeverity.DEGRADED
            )
            observations.append(
                self._observation(
                    component=component.component,
                    severity=severity,
                    summary=component.detail,
                    observed_at=component.observed_at,
                    evidence={
                        "health_status": component.status.value,
                        "risk_kill_switch": snapshot.risk_kill_switch,
                    },
                )
            )
        if snapshot.risk_kill_switch and not observations:
            observations.append(
                self._observation(
                    component="risk_kill_switch",
                    severity=MaintenanceSeverity.CRITICAL,
                    summary=snapshot.risk_kill_switch_reason or "risk kill switch engaged",
                    observed_at=now,
                    evidence={"risk_kill_switch": True},
                )
            )
        return self._dedupe(tuple(observations), include_repeated=include_repeated)

    def _observation(
        self,
        *,
        component: str,
        severity: MaintenanceSeverity,
        summary: str,
        observed_at: datetime,
        evidence: dict[str, str | int | float | bool | None],
    ) -> SystemObservation:
        identity = hashlib.sha256(
            f"{component}:{severity.value}:{summary}:{observed_at.isoformat()}".encode()
        ).hexdigest()[:32]
        return SystemObservation(
            observation_id=f"incident:{identity}",
            component=component,
            severity=severity,
            summary=summary,
            symptoms=(summary,),
            evidence=evidence,
            observed_at=observed_at,
        )

    def _dedupe(
        self,
        observations: tuple[SystemObservation, ...],
        *,
        include_repeated: bool,
    ) -> tuple[SystemObservation, ...]:
        accepted = []
        for observation in observations:
            if not include_repeated and observation.fingerprint in self._seen:
                continue
            self._seen.add(observation.fingerprint)
            accepted.append(observation)
        return tuple(accepted)
