from __future__ import annotations

from collections.abc import Callable

from aura.agents.models import AgentContext
from aura.runtime.free_public_ai_council import (
    FreePublicAICouncilConfig,
    FreePublicAICouncilRuntime,
)
from aura.runtime.scanner import MarketScanResult

ScanObserver = Callable[[MarketScanResult], None]


class ObservableFreePublicAICouncilRuntime(FreePublicAICouncilRuntime):
    """Free public council runtime with a read-only post-scan observation hook.

    The observer receives immutable scanner output after analysis. Observer errors
    are isolated and surfaced through the existing runtime status file; they do
    not gain execution authority and cannot create broker orders.
    """

    def __init__(
        self,
        config: FreePublicAICouncilConfig | None = None,
        *,
        scan_observer: ScanObserver | None = None,
        **kwargs,
    ) -> None:
        self.scan_observer = scan_observer
        super().__init__(config, **kwargs)

    async def _analyze(self, context: AgentContext) -> None:
        async with self._decision_semaphore:
            enriched = await self._enrich_context(context)
            result = await self.scanner.scan([enriched])
        self.recorder.register_scan(result)
        self.opportunity_auditor.register_scan(result)
        candidate = result.candidates[0]
        self.counters.ai_decisions_completed += 1
        if candidate.actionable:
            self.counters.actionable_decisions += 1
        if self.scan_observer is not None:
            try:
                self.scan_observer(result)
            except Exception as exc:  # noqa: BLE001 - dashboard observation is isolated
                self._write_status(
                    candidate,
                    last_error=f"operator observer {type(exc).__name__}: {exc}",
                )
                return
        self._write_status(candidate)
