from dataclasses import dataclass

import pytest

from aura.execution.reconciliation import (
    ReconciliationIssue,
    ReconciliationIssueType,
    ReconciliationReport,
    ReconciliationSeverity,
)
from aura.runtime.autonomous_paper import AutonomousPaperPolicy, AutonomousPaperSupervisor


@dataclass
class FakeStep:
    submitted_orders: tuple
    fills: tuple


class FakeCoordinator:
    def __init__(self, *, fail_reconciliation_after: int | None = None) -> None:
        self.started = False
        self.stopped = False
        self.batches = 0
        self.reconciliations = 0
        self.fail_reconciliation_after = fail_reconciliation_after

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def on_batch(self, batch):
        self.batches += 1
        return FakeStep(submitted_orders=(object(),), fills=(object(),) if self.batches > 1 else ())

    def reconcile(self):
        self.reconciliations += 1
        should_fail = (
            self.fail_reconciliation_after is not None
            and self.reconciliations >= self.fail_reconciliation_after
        )
        if not should_fail:
            return ReconciliationReport(
                issues=(),
                local_open_orders=0,
                broker_open_orders=0,
                compared_positions=0,
            )
        return ReconciliationReport(
            issues=(
                ReconciliationIssue(
                    issue_type=ReconciliationIssueType.POSITION_QUANTITY_MISMATCH,
                    severity=ReconciliationSeverity.CRITICAL,
                    key="X",
                    detail="paper broker/local position mismatch",
                ),
            ),
            local_open_orders=0,
            broker_open_orders=0,
            compared_positions=1,
        )


async def _batches(count: int):
    for _ in range(count):
        yield []


@pytest.mark.asyncio
async def test_supervisor_runs_batches_and_reconciles_automatically() -> None:
    coordinator = FakeCoordinator()
    result = await AutonomousPaperSupervisor(
        coordinator,
        policy=AutonomousPaperPolicy(reconcile_every_batches=2),
    ).run(_batches(3))

    assert coordinator.started and coordinator.stopped
    assert result.processed_batches == 3
    assert result.submitted_orders == 3
    assert result.observed_fills == 2
    assert result.reconciliation_checks == 2
    assert not result.stopped_for_reconciliation
    assert result.final_reconciliation is not None
    assert result.final_reconciliation.safe_for_new_risk


@pytest.mark.asyncio
async def test_supervisor_stops_when_reconciliation_becomes_unsafe() -> None:
    coordinator = FakeCoordinator(fail_reconciliation_after=1)
    result = await AutonomousPaperSupervisor(
        coordinator,
        policy=AutonomousPaperPolicy(reconcile_every_batches=2),
    ).run(_batches(10))

    assert result.processed_batches == 2
    assert result.stopped_for_reconciliation
    assert result.final_reconciliation is not None
    assert not result.final_reconciliation.safe_for_new_risk
    assert coordinator.stopped
