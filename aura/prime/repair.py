from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RepairAction(str, Enum):
    NONE = "NONE"
    RESTART_SERVICE = "RESTART_SERVICE"
    RESTART_REDIS = "RESTART_REDIS"
    RECONNECT_DATA = "RECONNECT_DATA"
    REBUILD_DASHBOARD = "REBUILD_DASHBOARD"
    REINSTALL_DEPENDENCIES = "REINSTALL_DEPENDENCIES"
    OPEN_MAINTENANCE_PROPOSAL = "OPEN_MAINTENANCE_PROPOSAL"


@dataclass(slots=True, frozen=True)
class AutoRepairPolicy:
    max_service_restarts: int = 3
    allow_dependency_reinstall: bool = True
    allow_dashboard_rebuild: bool = True
    allow_code_patch_proposal: bool = True

    def __post_init__(self) -> None:
        if self.max_service_restarts < 0:
            raise ValueError("max_service_restarts cannot be negative")


@dataclass(slots=True, frozen=True)
class AutoRepairResult:
    repaired: bool
    action: RepairAction
    detail: str
    requires_owner_approval: bool = False


class SafeAutoRepair:
    """Classify safe repairs without granting financial or self-modifying authority."""

    def __init__(self, policy: AutoRepairPolicy | None = None) -> None:
        self.policy = policy or AutoRepairPolicy()

    def plan(
        self,
        *,
        component: str,
        error_type: str,
        restart_count: int = 0,
    ) -> AutoRepairResult:
        component_key = component.strip().lower()
        error_key = error_type.strip().lower()

        if component_key in {"risk", "executor", "broker", "portfolio"}:
            return AutoRepairResult(
                repaired=False,
                action=RepairAction.OPEN_MAINTENANCE_PROPOSAL,
                detail="financial component failures require governed review; no automatic restart mutation",
                requires_owner_approval=True,
            )

        if "redis" in error_key:
            return AutoRepairResult(
                repaired=False,
                action=RepairAction.RESTART_REDIS,
                detail="restart local Redis transport and re-run readiness checks",
            )

        if "connection" in error_key or "websocket" in error_key:
            return AutoRepairResult(
                repaired=False,
                action=RepairAction.RECONNECT_DATA,
                detail="reconnect data transport with bounded backoff",
            )

        if component_key in {"dashboard", "frontend"} and self.policy.allow_dashboard_rebuild:
            return AutoRepairResult(
                repaired=False,
                action=RepairAction.REBUILD_DASHBOARD,
                detail="rebuild production dashboard assets and retry health check",
            )

        if restart_count < self.policy.max_service_restarts:
            return AutoRepairResult(
                repaired=False,
                action=RepairAction.RESTART_SERVICE,
                detail="restart non-financial service under bounded supervisor policy",
            )

        if self.policy.allow_code_patch_proposal:
            return AutoRepairResult(
                repaired=False,
                action=RepairAction.OPEN_MAINTENANCE_PROPOSAL,
                detail="automatic restarts exhausted; open governed code-repair proposal",
                requires_owner_approval=True,
            )

        return AutoRepairResult(
            repaired=False,
            action=RepairAction.NONE,
            detail="no permitted automatic repair remains",
        )
