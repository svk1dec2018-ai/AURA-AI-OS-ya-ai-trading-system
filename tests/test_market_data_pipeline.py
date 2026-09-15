from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aura.data.pipeline import CandleDataPipeline, RawCandlePayload
from aura.data.quality import CandleQualityGate, DataQualityPolicy


def _pipeline() -> CandleDataPipeline:
    return CandleDataPipeline(
        CandleQualityGate(
            DataQualityPolicy(
                expected_interval=timedelta(minutes=1),
                max_staleness=timedelta(minutes=2),
            )
        )
    )


def _raw(minute: int, **updates: object) -> RawCandlePayload:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    values: dict[str, object] = {
        "symbol": " aura-fixture ",
        "venue": " internal_fixture ",
        "timeframe": "1M",
        "open_time": start,
        "close_time": start + timedelta(minutes=1),
        "open_price": "100",
        "high_price": "101",
        "low_price": "99",
        "close_price": "100.5",
        "volume": "10",
    }
    values.update(updates)
    return RawCandlePayload.model_validate(values)


def test_pipeline_normalizes_and_releases_only_validated_batch() -> None:
    result = _pipeline().ingest(
        [_raw(0), _raw(1)],
        decision_time=datetime(2026, 1, 1, 0, 2, 30, tzinfo=UTC),
    )

    assert result.accepted
    assert result.validated is not None
    assert result.validated.candles[0].symbol == "AURA-FIXTURE"
    assert result.validated.candles[0].timeframe == "1m"
    assert result.validated.quality.latest_data_lag_ms == 30000
    assert result.anomalies == ()


def test_malformed_record_rejects_entire_batch_without_exposing_candles() -> None:
    result = _pipeline().ingest(
        [_raw(0), _raw(1, high_price="98")],
        decision_time=datetime(2026, 1, 1, 0, 2, 30, tzinfo=UTC),
    )

    assert not result.accepted
    assert result.validated is None
    assert [item.anomaly_type for item in result.anomalies] == ["normalization_error"]


def test_stale_series_rejects_entire_batch_and_records_anomaly() -> None:
    result = _pipeline().ingest(
        [_raw(0)],
        decision_time=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
    )

    assert not result.accepted
    assert result.validated is None
    assert [item.anomaly_type for item in result.anomalies] == ["stale"]
