from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aura.interface.operator_read_model import OperatorReadModel, ReadDomain
from aura.runtime.opportunity_radar import OpportunityRadarSnapshot


def test_read_model_publishes_fresh_provenance_snapshot() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store = OperatorReadModel()
    record = store.publish(
        ReadDomain.RISK,
        {"kill_switch": False, "drawdown_pct": "1.25"},
        source="risk-engine:v1",
        observed_at=now,
        max_age=timedelta(seconds=30),
        received_at=now,
    )

    view = store.get(ReadDomain.RISK, as_of=now + timedelta(seconds=10))
    assert view.available is True
    assert view.stale is False
    assert view.source == "risk-engine:v1"
    assert view.payload == {"drawdown_pct": "1.25", "kill_switch": False}
    assert view.checksum_sha256 == record.checksum_sha256
    assert len(view.checksum_sha256 or "") == 64


def test_stale_read_model_never_returns_stale_payload() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store = OperatorReadModel()
    store.publish(
        ReadDomain.OPPORTUNITIES,
        {"items": [{"symbol": "BTC/USD", "score": 91.0}]},
        source="radar",
        observed_at=now,
        max_age=timedelta(seconds=5),
        received_at=now,
    )

    view = store.get(ReadDomain.OPPORTUNITIES, as_of=now + timedelta(seconds=6))
    assert view.available is False
    assert view.stale is True
    assert view.payload is None
    assert view.reason == "snapshot is stale"


def test_missing_domain_is_explicitly_unavailable() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    view = OperatorReadModel().get(ReadDomain.PORTFOLIO, as_of=now)
    assert view.available is False
    assert view.stale is False
    assert view.payload is None
    assert view.reason == "source not attached"


def test_read_model_rejects_future_or_backward_observations() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store = OperatorReadModel()
    with pytest.raises(ValueError, match="future"):
        store.publish(
            ReadDomain.DATA,
            {"feed": "test"},
            source="data",
            observed_at=now + timedelta(seconds=1),
            received_at=now,
            max_age=timedelta(seconds=10),
        )

    store.publish(
        ReadDomain.DATA,
        {"feed": "test"},
        source="data",
        observed_at=now,
        received_at=now,
        max_age=timedelta(seconds=10),
    )
    with pytest.raises(ValueError, match="backwards"):
        store.publish(
            ReadDomain.DATA,
            {"feed": "older"},
            source="data",
            observed_at=now - timedelta(seconds=1),
            received_at=now,
            max_age=timedelta(seconds=10),
        )


def test_read_model_rejects_non_json_payloads_and_nan() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = OperatorReadModel()
    with pytest.raises(ValueError, match="finite JSON"):
        store.publish(
            ReadDomain.SYSTEM,
            {"bad": object()},
            source="system",
            observed_at=now,
            received_at=now,
            max_age=timedelta(seconds=10),
        )
    with pytest.raises(ValueError, match="finite JSON"):
        store.publish(
            ReadDomain.SYSTEM,
            {"bad": float("nan")},
            source="system",
            observed_at=now,
            received_at=now,
            max_age=timedelta(seconds=10),
        )


def test_opportunity_radar_publisher_preserves_as_of() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store = OperatorReadModel()
    snapshot = OpportunityRadarSnapshot(items=(), as_of=now)
    store.publish_opportunity_radar(
        snapshot,
        received_at=now,
        max_age=timedelta(minutes=1),
    )
    view = store.get(ReadDomain.OPPORTUNITIES, as_of=now)
    assert view.available is True
    assert view.payload == {
        "actionable_count": 0,
        "as_of": now.isoformat(),
        "count": 0,
        "items": [],
    }


def test_overview_contains_every_whitelisted_domain() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    overview = OperatorReadModel().overview(as_of=now)
    assert set(overview) == {domain.value for domain in ReadDomain}
    assert all(item["available"] is False for item in overview.values())
