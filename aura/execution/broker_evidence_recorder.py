from __future__ import annotations

import hashlib
import json
from datetime import datetime
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aura.domain.models import OrderStatus
from aura.execution.broker import BrokerExecutionMode
from aura.execution.broker_evidence import (
    BrokerEvidenceBundle,
    BrokerEvidenceSource,
    BrokerExecutionObservation,
    BrokerReconciliationObservation,
    SealedBrokerEvidence,
)
from aura.execution.reconciliation import ReconciliationReport, ReconciliationSeverity
from aura.execution.state import OrderState


class CredentialFreeExecutionFingerprints(BaseModel):
    """Opaque adapter-produced hashes; raw broker identifiers are not accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order: str = Field(pattern=r"^[0-9a-f]{64}$")
    broker_order: str = Field(pattern=r"^[0-9a-f]{64}$")
    broker_response: str = Field(pattern=r"^[0-9a-f]{64}$")


class BrokerEvidenceRecorderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    adapter_name: str = Field(min_length=1)
    mode: BrokerExecutionMode
    source: BrokerEvidenceSource
    environment_verified: bool
    account_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    attestation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_authority: Literal[False] = False


class BrokerEvidenceRecorder:
    """Convert existing normalized runtime state into a sealed, secret-free export.

    The recorder performs no broker I/O and cannot authorize execution. Broker and
    account identifiers must already be represented as opaque SHA-256 fingerprints.
    """

    def __init__(self, config: BrokerEvidenceRecorderConfig) -> None:
        self.config = config
        self._executions: list[BrokerExecutionObservation] = []
        self._reconciliations: list[BrokerReconciliationObservation] = []
        self._lock = RLock()

    def record_order_state(
        self,
        state: OrderState,
        *,
        fingerprints: CredentialFreeExecutionFingerprints,
        submitted_at: datetime,
        acknowledged_at: datetime,
        final_observed_at: datetime,
    ) -> BrokerExecutionObservation:
        if self.config.mode in {
            BrokerExecutionMode.PAPER,
            BrokerExecutionMode.READ_ONLY,
        }:
            raise ValueError("paper/read-only recorder cannot claim broker execution")
        if state.status != OrderStatus.FILLED:
            raise ValueError("broker execution evidence requires a complete filled order")

        observation = BrokerExecutionObservation(
            probe_id=f"probe:{fingerprints.client_order}",
            client_order_fingerprint=fingerprints.client_order,
            broker_order_fingerprint=fingerprints.broker_order,
            broker_response_fingerprint=fingerprints.broker_response,
            requested_quantity=state.request.quantity,
            filled_quantity=state.filled_quantity,
            fill_count=len(state.fill_ids),
            final_status=state.status,
            submitted_at=submitted_at,
            acknowledged_at=acknowledged_at,
            final_observed_at=final_observed_at,
        )
        with self._lock:
            if any(item.probe_id == observation.probe_id for item in self._executions):
                raise ValueError("duplicate broker execution probe")
            self._executions.append(observation)
        return observation

    def record_reconciliation(
        self,
        report: ReconciliationReport,
        *,
        observed_at: datetime,
    ) -> BrokerReconciliationObservation:
        report_fingerprint = _reconciliation_report_fingerprint(report)
        run_id = "reconciliation:" + _sha256(
            {
                "observed_at": observed_at.isoformat(),
                "report_fingerprint": report_fingerprint,
            }
        )
        observation = BrokerReconciliationObservation(
            run_id=run_id,
            observed_at=observed_at,
            local_open_orders=report.local_open_orders,
            broker_open_orders=report.broker_open_orders,
            compared_positions=report.compared_positions,
            issue_count=len(report.issues),
            critical_issue_count=sum(
                issue.severity == ReconciliationSeverity.CRITICAL
                for issue in report.issues
            ),
            safe_for_new_risk=report.safe_for_new_risk,
            report_fingerprint=report_fingerprint,
        )
        with self._lock:
            if any(item.run_id == observation.run_id for item in self._reconciliations):
                raise ValueError("duplicate broker reconciliation observation")
            self._reconciliations.append(observation)
        return observation

    def seal(self, *, captured_at: datetime) -> SealedBrokerEvidence:
        with self._lock:
            executions = tuple(self._executions)
            reconciliations = tuple(self._reconciliations)
        capture_id = "capture:" + _sha256(
            {
                "adapter_name": self.config.adapter_name,
                "account_fingerprint": self.config.account_fingerprint,
                "attestation_fingerprint": self.config.attestation_fingerprint,
                "captured_at": captured_at.isoformat(),
                "execution_probe_ids": sorted(item.probe_id for item in executions),
                "reconciliation_run_ids": sorted(
                    item.run_id for item in reconciliations
                ),
            }
        )
        bundle = BrokerEvidenceBundle(
            capture_id=capture_id,
            adapter_name=self.config.adapter_name,
            mode=self.config.mode,
            source=self.config.source,
            environment_verified=self.config.environment_verified,
            account_fingerprint=self.config.account_fingerprint,
            attestation_fingerprint=self.config.attestation_fingerprint,
            captured_at=captured_at,
            executions=executions,
            reconciliation_runs=reconciliations,
        )
        return SealedBrokerEvidence.seal(bundle)


def _reconciliation_report_fingerprint(report: ReconciliationReport) -> str:
    issues = sorted(
        (
            {
                "issue_type": issue.issue_type.value,
                "severity": issue.severity.value,
                "key_sha256": _sha256(issue.key),
                "detail_sha256": _sha256(issue.detail),
            }
            for issue in report.issues
        ),
        key=lambda item: (
            item["issue_type"],
            item["severity"],
            item["key_sha256"],
            item["detail_sha256"],
        ),
    )
    return _sha256(
        {
            "issues": issues,
            "local_open_orders": report.local_open_orders,
            "broker_open_orders": report.broker_open_orders,
            "compared_positions": report.compared_positions,
            "safe_for_new_risk": report.safe_for_new_risk,
        }
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
