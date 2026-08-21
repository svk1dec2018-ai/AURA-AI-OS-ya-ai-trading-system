from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from aura.maintenance.authority import (
    AuthorityAction,
    AuthorityRole,
    DevelopmentAuthorityPolicy,
)
from aura.maintenance.models import (
    CorrectedFinancialView,
    FinancialCorrectionApproval,
    FinancialCorrectionRequest,
)
from aura.persistence.wal import JsonlWriteAheadLog, WalEvent

_SCHEMA_VERSION = 1
_HEADER_EVENT = "financial_correction_ledger_initialized"
_REQUEST_EVENT = "financial_correction_requested"
_APPROVAL_EVENT = "financial_correction_owner_approved"


class FinancialCorrectionError(RuntimeError):
    pass


class AuditedFinancialCorrectionLedger:
    """Append-only overlay for owner-approved P&L/trade reporting corrections.

    It intentionally has no `cash`, `position`, `fill`, deposit, withdrawal or broker
    methods. Approved events produce a corrected reporting view while the original
    `PortfolioLedger`, broker fills and reconciliation truth remain unchanged.
    """

    def __init__(
        self,
        journal_path: Path,
        *,
        policy: DevelopmentAuthorityPolicy | None = None,
    ) -> None:
        self.journal_path = journal_path
        self.policy = policy or DevelopmentAuthorityPolicy()
        self._wal = JsonlWriteAheadLog(journal_path)
        self._requests: dict[str, FinancialCorrectionRequest] = {}
        self._approvals: dict[str, FinancialCorrectionApproval] = {}
        self.recovered_events = 0
        self._initialize_or_replay()

    def request(
        self,
        correction: FinancialCorrectionRequest,
        *,
        role: AuthorityRole,
    ) -> bool:
        self.policy.require(role, AuthorityAction.REQUEST_FINANCIAL_CORRECTION)
        existing = self._requests.get(correction.correction_id)
        if existing is not None:
            if existing != correction:
                raise FinancialCorrectionError("correction identity collision")
            return False
        event = self._wal.append(
            event_type=_REQUEST_EVENT,
            payload={
                "correction_schema_version": _SCHEMA_VERSION,
                "correction": correction.model_dump(
                    mode="json",
                    exclude={"content_sha256"},
                ),
            },
            correlation_id=correction.correction_id,
            event_id=f"{correction.correction_id}:requested:{correction.content_sha256}",
        )
        self._apply_request(event)
        return True

    def approve(
        self,
        correction_id: str,
        *,
        role: AuthorityRole,
        owner_id: str,
        expected_content_sha256: str,
    ) -> FinancialCorrectionApproval:
        self.policy.require(role, AuthorityAction.APPROVE_FINANCIAL_CORRECTION)
        correction = self.get(correction_id)
        if correction.content_sha256 != expected_content_sha256:
            raise FinancialCorrectionError("correction changed after owner review")
        existing = self._approvals.get(correction_id)
        if existing is not None:
            if existing.owner_id != owner_id:
                raise FinancialCorrectionError("correction is already approved by another owner")
            return existing
        approval = FinancialCorrectionApproval(
            correction_id=correction_id,
            correction_content_sha256=correction.content_sha256,
            owner_id=owner_id,
        )
        event = self._wal.append(
            event_type=_APPROVAL_EVENT,
            payload={
                "correction_schema_version": _SCHEMA_VERSION,
                "approval": approval.model_dump(mode="json"),
            },
            correlation_id=correction_id,
            event_id=f"{correction_id}:approved:{approval.approval_id}",
        )
        self._apply_approval(event)
        return approval

    def get(self, correction_id: str) -> FinancialCorrectionRequest:
        try:
            return self._requests[correction_id]
        except KeyError as exc:
            raise KeyError(f"unknown financial correction: {correction_id}") from exc

    def approved(self, correction_id: str) -> bool:
        return correction_id in self._approvals

    def corrected_view(
        self,
        *,
        base_realized_pnl: Decimal,
        base_fees_paid: Decimal,
    ) -> CorrectedFinancialView:
        pnl_delta = Decimal(0)
        fee_delta = Decimal(0)
        correction_ids: list[str] = []
        annotations: dict[str, list[dict[str, str]]] = {}
        for correction_id in sorted(self._approvals):
            correction = self._requests[correction_id]
            pnl_delta += correction.net_realized_pnl_delta
            fee_delta += correction.fee_delta
            correction_ids.append(correction_id)
            if correction.target_trade_id and correction.corrected_fields:
                annotations.setdefault(correction.target_trade_id, []).append(
                    dict(correction.corrected_fields)
                )
        return CorrectedFinancialView(
            base_realized_pnl=base_realized_pnl,
            corrected_realized_pnl=base_realized_pnl + pnl_delta,
            base_fees_paid=base_fees_paid,
            corrected_fees_paid=base_fees_paid + fee_delta,
            approved_correction_ids=tuple(correction_ids),
            trade_annotations={
                trade_id: tuple(items)
                for trade_id, items in sorted(annotations.items())
            },
        )

    def _initialize_or_replay(self) -> None:
        events = self._wal.read_all()
        if not events:
            self._wal.append(
                event_type=_HEADER_EVENT,
                payload={"correction_schema_version": _SCHEMA_VERSION},
                correlation_id="financial-correction-ledger",
                event_id="financial-correction-ledger:initialized:v1",
            )
            return
        header = events[0]
        self._validate_schema(header)
        if (
            header.event_type != _HEADER_EVENT
            or header.event_id != "financial-correction-ledger:initialized:v1"
            or header.correlation_id != "financial-correction-ledger"
        ):
            raise FinancialCorrectionError("financial correction ledger is missing its header")
        for event in events[1:]:
            self._validate_schema(event)
            if event.event_type == _REQUEST_EVENT:
                self._apply_request(event)
            elif event.event_type == _APPROVAL_EVENT:
                self._apply_approval(event)
            else:
                raise FinancialCorrectionError(
                    f"unknown financial correction event: {event.event_type}"
                )
            self.recovered_events += 1

    @staticmethod
    def _validate_schema(event: WalEvent) -> None:
        if event.payload.get("correction_schema_version") != _SCHEMA_VERSION:
            raise FinancialCorrectionError("unsupported financial correction schema")

    def _apply_request(self, event: WalEvent) -> None:
        try:
            correction = FinancialCorrectionRequest.model_validate(event.payload["correction"])
        except Exception as exc:
            raise FinancialCorrectionError(f"invalid correction event: {event.event_id}") from exc
        expected_id = f"{correction.correction_id}:requested:{correction.content_sha256}"
        if (
            event.event_id != expected_id
            or event.correlation_id != correction.correction_id
            or correction.correction_id in self._requests
        ):
            raise FinancialCorrectionError("correction event identity mismatch or duplicate")
        self._requests[correction.correction_id] = correction

    def _apply_approval(self, event: WalEvent) -> None:
        try:
            approval = FinancialCorrectionApproval.model_validate(event.payload["approval"])
            correction = self.get(approval.correction_id)
        except Exception as exc:
            raise FinancialCorrectionError(
                f"invalid correction approval event: {event.event_id}"
            ) from exc
        if approval.correction_content_sha256 != correction.content_sha256:
            raise FinancialCorrectionError("correction approval content binding mismatch")
        expected_id = f"{correction.correction_id}:approved:{approval.approval_id}"
        if (
            event.event_id != expected_id
            or event.correlation_id != correction.correction_id
            or correction.correction_id in self._approvals
        ):
            raise FinancialCorrectionError("correction approval identity mismatch or duplicate")
        self._approvals[correction.correction_id] = approval
