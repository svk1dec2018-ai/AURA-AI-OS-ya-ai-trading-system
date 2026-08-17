from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Protocol

from aura.domain.models import NormalizedCandle
from aura.execution.reconciliation import ReconciliationReport
from aura.runtime.multi_market_paper import MultiMarketPaperStep


class PaperCoordinator(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def on_batch(
        self,
        candles: list[NormalizedCandle] | tuple[NormalizedCandle, ...],
    ) -> MultiMarketPaperStep: ...

    def reconcile(self) -> ReconciliationReport: ...


@dataclass(slots=True, frozen=True)
class AutonomousPaperPolicy:
    reconcile_every_batches: int = 10
    stop_on_reconciliation_failure: bool = True
    max_batches: int | None = None

    def __post_init__(self) -> None:
        if self.reconcile_every_batches <= 0:
            raise ValueError("reconcile_every_batches must be positive")
        if self.max_batches is not None and self.max_batches <= 0:
            raise ValueError("max_batches must be positive when supplied")


@dataclass(slots=True, frozen=True)
class AutonomousPaperResult:
    processed_batches: int
    submitted_orders: int
    observed_fills: int
    reconciliation_checks: int
    stopped_for_reconciliation: bool
    final_reconciliation: ReconciliationReport | None


class AutonomousPaperSupervisor:
    """Consume a live/demo batch stream and operate AURA paper trading autonomously.

    The supervisor owns orchestration only. It does not weaken data-quality,
    agent-policy or financial-risk gates in the underlying coordinator. A failed
    reconciliation can stop further paper decisions immediately.
    """

    def __init__(
        self,
        coordinator: PaperCoordinator,
        *,
        policy: AutonomousPaperPolicy | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.policy = policy or AutonomousPaperPolicy()

    async def run(
        self,
        batches: AsyncIterable[list[NormalizedCandle] | tuple[NormalizedCandle, ...]],
    ) -> AutonomousPaperResult:
        processed = 0
        orders = 0
        fills = 0
        reconciliation_checks = 0
        stopped_for_reconciliation = False
        final_reconciliation: ReconciliationReport | None = None

        await self.coordinator.start()
        try:
            async for batch in batches:
                step = await self.coordinator.on_batch(batch)
                processed += 1
                orders += len(step.submitted_orders)
                fills += len(step.fills)

                if processed % self.policy.reconcile_every_batches == 0:
                    final_reconciliation = self.coordinator.reconcile()
                    reconciliation_checks += 1
                    if (
                        self.policy.stop_on_reconciliation_failure
                        and not final_reconciliation.safe_for_new_risk
                    ):
                        stopped_for_reconciliation = True
                        break

                if self.policy.max_batches is not None and processed >= self.policy.max_batches:
                    break

            if processed and processed % self.policy.reconcile_every_batches != 0:
                final_reconciliation = self.coordinator.reconcile()
                reconciliation_checks += 1
                if (
                    self.policy.stop_on_reconciliation_failure
                    and not final_reconciliation.safe_for_new_risk
                ):
                    stopped_for_reconciliation = True
        finally:
            await self.coordinator.stop()

        return AutonomousPaperResult(
            processed_batches=processed,
            submitted_orders=orders,
            observed_fills=fills,
            reconciliation_checks=reconciliation_checks,
            stopped_for_reconciliation=stopped_for_reconciliation,
            final_reconciliation=final_reconciliation,
        )
