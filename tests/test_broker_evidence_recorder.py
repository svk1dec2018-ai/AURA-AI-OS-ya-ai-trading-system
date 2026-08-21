from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aura.domain.models import Fill, OrderRequest, Side
from aura.execution.broker import BrokerExecutionMode
from aura.execution.broker_evidence import BrokerEvidenceSource
from aura.execution.broker_evidence_recorder import (
    BrokerEvidenceRecorder,
    BrokerEvidenceRecorderConfig,
    CredentialFreeExecutionFingerprints,
)
from aura.execution.reconciliation import (
    ReconciliationIssue,
    ReconciliationIssueType,
    ReconciliationReport,
    ReconciliationSeverity,
)
from aura.execution.state import OrderState

_START = datetime(2026, 8, 21, 5, 0, tzinfo=UTC)
_RAW_ORDER_ID = "raw-local-order-id-must-not-leak"
_RAW_CLIENT_ID = "raw-client-order-id-must-not-leak"
_RAW_FILL_ID = "raw-fill-id-must-not-leak"
_RAW_SYMBOL = "RAW-SYMBOL-MUST-NOT-LEAK"


def _config(
    mode: BrokerExecutionMode = BrokerExecutionMode.CONTROLLED_LIVE,
) -> BrokerEvidenceRecorderConfig:
    return BrokerEvidenceRecorderConfig(
        adapter_name="ANGEL_ONE_SMARTAPI",
        mode=mode,
        source=BrokerEvidenceSource.AUTHORIZED_EXTERNAL_BROKER,
        environment_verified=True,
        account_fingerprint="d" * 64,
        attestation_fingerprint="e" * 64,
    )


def _fingerprints() -> CredentialFreeExecutionFingerprints:
    return CredentialFreeExecutionFingerprints(
        client_order="a" * 64,
        broker_order="b" * 64,
        broker_response="c" * 64,
    )


def _filled_state() -> OrderState:
    request = OrderRequest(
        order_id=_RAW_ORDER_ID,
        client_order_id=_RAW_CLIENT_ID,
        symbol=_RAW_SYMBOL,
        venue="RAW-VENUE-MUST-NOT-LEAK",
        side=Side.BUY,
        quantity=Decimal(1),
        created_at=_START,
    )
    state = OrderState(request)
    state.submit()
    state.acknowledge()
    state.apply_fill(
        Fill(
            fill_id=_RAW_FILL_ID,
            order_id=request.order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=Decimal(1),
            price=Decimal(100),
            timestamp=_START + timedelta(seconds=2),
        )
    )
    return state


def _clean_report() -> ReconciliationReport:
    return ReconciliationReport(
        issues=(),
        local_open_orders=0,
        broker_open_orders=0,
        compared_positions=1,
    )


def test_recorder_converts_runtime_state_without_leaking_raw_identifiers() -> None:
    recorder = BrokerEvidenceRecorder(_config())
    recorder.record_order_state(
        _filled_state(),
        fingerprints=_fingerprints(),
        submitted_at=_START,
        acknowledged_at=_START + timedelta(seconds=1),
        final_observed_at=_START + timedelta(seconds=3),
    )
    for index in range(3):
        recorder.record_reconciliation(
            _clean_report(),
            observed_at=_START + timedelta(seconds=10 + index),
        )
    sealed = recorder.seal(captured_at=_START + timedelta(minutes=1))
    payload = sealed.model_dump_json()

    assert sealed.bundle.executions[0].fill_count == 1
    assert len(sealed.bundle.reconciliation_runs) == 3
    for raw_value in (_RAW_ORDER_ID, _RAW_CLIENT_ID, _RAW_FILL_ID, _RAW_SYMBOL):
        assert raw_value not in payload
    assert sealed.bundle.execution_authority is False


def test_recorder_hashes_reconciliation_issue_details() -> None:
    recorder = BrokerEvidenceRecorder(_config())
    raw_key = "sensitive-broker-key"
    raw_detail = "sensitive position mismatch details"
    report = ReconciliationReport(
        issues=(
            ReconciliationIssue(
                issue_type=ReconciliationIssueType.POSITION_QUANTITY_MISMATCH,
                severity=ReconciliationSeverity.CRITICAL,
                key=raw_key,
                detail=raw_detail,
            ),
        ),
        local_open_orders=0,
        broker_open_orders=0,
        compared_positions=1,
    )
    observation = recorder.record_reconciliation(
        report,
        observed_at=_START + timedelta(seconds=10),
    )

    assert observation.safe_for_new_risk is False
    assert observation.critical_issue_count == 1
    assert raw_key not in observation.model_dump_json()
    assert raw_detail not in observation.model_dump_json()


def test_recorder_rejects_nonterminal_and_read_only_execution() -> None:
    state = _filled_state()
    pending = OrderState(state.request)
    pending.submit()

    with pytest.raises(ValueError, match="complete filled order"):
        BrokerEvidenceRecorder(_config()).record_order_state(
            pending,
            fingerprints=_fingerprints(),
            submitted_at=_START,
            acknowledged_at=_START + timedelta(seconds=1),
            final_observed_at=_START + timedelta(seconds=2),
        )

    with pytest.raises(ValueError, match="read-only recorder"):
        BrokerEvidenceRecorder(_config(BrokerExecutionMode.READ_ONLY)).record_order_state(
            state,
            fingerprints=_fingerprints(),
            submitted_at=_START,
            acknowledged_at=_START + timedelta(seconds=1),
            final_observed_at=_START + timedelta(seconds=2),
        )


def test_recorder_rejects_duplicate_observations() -> None:
    recorder = BrokerEvidenceRecorder(_config())
    kwargs = {
        "fingerprints": _fingerprints(),
        "submitted_at": _START,
        "acknowledged_at": _START + timedelta(seconds=1),
        "final_observed_at": _START + timedelta(seconds=3),
    }
    recorder.record_order_state(_filled_state(), **kwargs)
    with pytest.raises(ValueError, match="duplicate broker execution probe"):
        recorder.record_order_state(_filled_state(), **kwargs)

    observed_at = _START + timedelta(seconds=10)
    recorder.record_reconciliation(_clean_report(), observed_at=observed_at)
    with pytest.raises(ValueError, match="duplicate broker reconciliation"):
        recorder.record_reconciliation(_clean_report(), observed_at=observed_at)
