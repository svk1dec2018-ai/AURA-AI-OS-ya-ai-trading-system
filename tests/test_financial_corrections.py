from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aura.domain.models import Fill, Side
from aura.maintenance.authority import (
    AuthorityAction,
    AuthorityDeniedError,
    AuthorityRole,
    DevelopmentAuthorityPolicy,
)
from aura.maintenance.financial_corrections import AuditedFinancialCorrectionLedger
from aura.maintenance.models import (
    FinancialCorrectionKind,
    FinancialCorrectionRequest,
    FinancialMode,
)
from aura.portfolio.ledger import PortfolioLedger


def _fill(fill_id: str, side: Side, price: str, fee: str = "0") -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id=f"order:{fill_id}",
        symbol="X",
        side=side,
        quantity=Decimal(1),
        price=Decimal(price),
        fee=Decimal(fee),
        timestamp=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
    )


def test_owner_approved_correction_changes_view_not_source_ledger(tmp_path) -> None:
    portfolio = PortfolioLedger(Decimal(1000))
    portfolio.apply_fill(_fill("fill-1", Side.BUY, "100", "1"))
    portfolio.apply_fill(_fill("fill-2", Side.SELL, "120", "1"))
    base_snapshot = portfolio.snapshot({"X": Decimal(120)})
    original_cash = portfolio.cash
    original_realized = portfolio.realized_pnl
    original_fills = set(portfolio._applied_fills)

    ledger = AuditedFinancialCorrectionLedger(tmp_path / "corrections.jsonl")
    correction = FinancialCorrectionRequest(
        correction_id="correction:pnl-1",
        mode=FinancialMode.PAPER,
        kind=FinancialCorrectionKind.PNL_ADJUSTMENT,
        net_realized_pnl_delta=Decimal("-3.50"),
        reason="correct paper reporting rounding discrepancy",
        requested_by="maintenance-ai",
    )
    assert ledger.request(correction, role=AuthorityRole.MAINTENANCE_AI)
    with pytest.raises(AuthorityDeniedError):
        ledger.approve(
            correction.correction_id,
            role=AuthorityRole.MAINTENANCE_AI,
            owner_id="owner",
            expected_content_sha256=correction.content_sha256,
        )
    ledger.approve(
        correction.correction_id,
        role=AuthorityRole.OWNER,
        owner_id="owner",
        expected_content_sha256=correction.content_sha256,
    )
    view = ledger.corrected_view(
        base_realized_pnl=base_snapshot.realized_pnl,
        base_fees_paid=portfolio.fees_paid,
    )

    assert view.corrected_realized_pnl == Decimal("14.50")
    assert view.source_ledger_mutated is False
    assert view.fund_movement_performed is False
    assert portfolio.cash == original_cash
    assert portfolio.realized_pnl == original_realized
    assert portfolio._applied_fills == original_fills


def test_trade_annotation_and_fee_adjustment_survive_restart(tmp_path) -> None:
    path = tmp_path / "corrections.jsonl"
    ledger = AuditedFinancialCorrectionLedger(path)
    annotation = FinancialCorrectionRequest(
        correction_id="correction:annotation",
        mode=FinancialMode.PAPER,
        kind=FinancialCorrectionKind.TRADE_ANNOTATION,
        target_trade_id="fill-2",
        corrected_fields={"setup": "breakout", "note": "owner-reviewed label"},
        reason="correct the paper trade classification",
        requested_by="developer",
    )
    fee = FinancialCorrectionRequest(
        correction_id="correction:fee",
        mode=FinancialMode.PAPER,
        kind=FinancialCorrectionKind.FEE_ADJUSTMENT,
        net_realized_pnl_delta=Decimal(-2),
        fee_delta=Decimal(2),
        reason="add omitted paper transaction fee",
        requested_by="developer",
    )
    for correction in (annotation, fee):
        ledger.request(correction, role=AuthorityRole.DEVELOPER)
        ledger.approve(
            correction.correction_id,
            role=AuthorityRole.OWNER,
            owner_id="owner",
            expected_content_sha256=correction.content_sha256,
        )

    recovered = AuditedFinancialCorrectionLedger(path)
    view = recovered.corrected_view(
        base_realized_pnl=Decimal(100),
        base_fees_paid=Decimal(5),
    )
    assert recovered.recovered_events == 4
    assert view.corrected_realized_pnl == Decimal(98)
    assert view.corrected_fees_paid == Decimal(7)
    assert view.trade_annotations["fill-2"][0]["setup"] == "breakout"


def test_controlled_live_correction_requires_broker_evidence_and_reconciliation() -> None:
    with pytest.raises(ValidationError, match="broker evidence"):
        FinancialCorrectionRequest(
            mode=FinancialMode.CONTROLLED_LIVE,
            kind=FinancialCorrectionKind.BROKER_TRADE_CORRECTION,
            target_trade_id="opaque-fill",
            corrected_fields={"status": "broker-corrected"},
            reason="broker supplied a corrected trade record",
            requested_by="owner",
        )
    valid = FinancialCorrectionRequest(
        mode=FinancialMode.CONTROLLED_LIVE,
        kind=FinancialCorrectionKind.BROKER_TRADE_CORRECTION,
        target_trade_id="opaque-fill",
        corrected_fields={"status": "broker-corrected"},
        reason="broker supplied a corrected trade record",
        requested_by="owner",
        evidence_sha256="a" * 64,
        reconciliation_id="reconciliation:clean:123",
    )
    assert valid.content_sha256


def test_correction_schema_has_no_cash_or_fund_mutation_fields() -> None:
    with pytest.raises(ValidationError):
        FinancialCorrectionRequest.model_validate(
            {
                "mode": "PAPER",
                "kind": "PNL_ADJUSTMENT",
                "net_realized_pnl_delta": "10",
                "reason": "attempt to add hidden cash",
                "requested_by": "owner",
                "cash_delta": "100000",
            }
        )
    policy = DevelopmentAuthorityPolicy()
    for action in (
        AuthorityAction.ADD_FUNDS,
        AuthorityAction.WITHDRAW_FUNDS,
        AuthorityAction.TRANSFER_FUNDS,
    ):
        assert policy.decide(AuthorityRole.OWNER, action).allowed is False

    with pytest.raises(ValidationError, match="unsupported corrected reporting field"):
        FinancialCorrectionRequest(
            mode=FinancialMode.PAPER,
            kind=FinancialCorrectionKind.TRADE_ANNOTATION,
            target_trade_id="paper-trade-1",
            corrected_fields={"cash_balance": "999999"},
            reason="attempt to disguise a cash mutation as an annotation",
            requested_by="owner",
        )

    with pytest.raises(ValidationError, match="finite"):
        FinancialCorrectionRequest(
            mode=FinancialMode.PAPER,
            kind=FinancialCorrectionKind.PNL_ADJUSTMENT,
            net_realized_pnl_delta=Decimal("NaN"),
            reason="attempt to create a non-finite reporting adjustment",
            requested_by="owner",
        )


def test_financial_correction_tampering_fails_closed_on_restart(tmp_path) -> None:
    path = tmp_path / "corrections.jsonl"
    ledger = AuditedFinancialCorrectionLedger(path)
    correction = FinancialCorrectionRequest(
        correction_id="correction:tamper",
        mode=FinancialMode.PAPER,
        kind=FinancialCorrectionKind.PNL_ADJUSTMENT,
        net_realized_pnl_delta=Decimal(1),
        reason="correct a paper reporting discrepancy",
        requested_by="owner",
    )
    ledger.request(correction, role=AuthorityRole.OWNER)
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    record["event"]["payload"]["correction"]["reason"] = "tampered reason"
    lines[-1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(Exception, match="checksum mismatch"):
        AuditedFinancialCorrectionLedger(path)
