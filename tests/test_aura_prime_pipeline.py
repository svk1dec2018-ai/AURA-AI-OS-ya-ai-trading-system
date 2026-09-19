import asyncio
from datetime import UTC, datetime
from pathlib import Path

from aura.fleet.bus import InMemoryEventBus
from aura.fleet.events import FleetEvent, FleetEventKind
from aura.fleet.manifest import AURA_FLEET, ServiceRole
from aura.prime.features import extract_candle_features
from aura.prime.ml_linear import LinearProbabilityArtifact, SklearnLogisticTrainer
from aura.prime.service_handlers import (
    FeatureRoleHandler,
    LinearModelRoleHandler,
    build_prime_role_handler,
)


def _candles(count: int = 60) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    price = 100.0
    for index in range(count):
        price += 0.15 + (0.03 if index % 3 == 0 else -0.01)
        rows.append(
            {
                "open": price - 0.08,
                "high": price + 0.22,
                "low": price - 0.18,
                "close": price,
                "volume": 1000 + index * 5,
                "closed": True,
            }
        )
    return rows


def test_prime_feature_extraction_is_finite_and_closed_candle_only() -> None:
    vector = extract_candle_features(
        _candles(),
        symbol="XAUUSD",
        timeframe="5m",
    )
    assert vector.sample_count == 60
    assert set(vector.features) == {
        "return_1",
        "return_5",
        "ema8_gap",
        "ema21_gap",
        "ema50_gap",
        "ema8_21_spread",
        "ema21_50_spread",
        "rsi14",
        "atr14_pct",
        "range20_position",
        "volume_ratio20",
    }
    assert 0 <= vector.features["rsi14"] <= 1
    assert 0 <= vector.features["range20_position"] <= 1


def test_feature_to_linear_ml_vote_pipeline(tmp_path: Path) -> None:
    async def scenario() -> None:
        bus = InMemoryEventBus()
        feature_handler = FeatureRoleHandler(bus)
        vector = extract_candle_features(
            _candles(),
            symbol="XAUUSD",
            timeframe="5m",
        )
        names = tuple(sorted(vector.features))
        artifact = LinearProbabilityArtifact(
            model_key="prime-logistic",
            version="v1",
            feature_names=names,
            coefficients=tuple(0.0 for _ in names),
            intercept=2.0,
            reliability=0.8,
            calibration=0.8,
            training_data_fingerprint="a" * 64,
        )
        path = tmp_path / "model.json"
        artifact.save(path)
        model_handler = LinearModelRoleHandler(bus, path)
        assert model_handler.ready is True

        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        market = FleetEvent(
            kind=FleetEventKind.MARKET_CANDLE,
            source="test-data",
            symbol="XAUUSD",
            venue="MT5",
            correlation_id="corr-1",
            occurred_at=now,
            payload={"timeframe": "5m", "candles": _candles()},
        )
        await feature_handler("market.candle", market)
        feature_rows = await bus.read("features.vector", after_id="0-0")
        assert len(feature_rows) == 1
        feature_event = feature_rows[0][1]
        assert feature_event.kind is FleetEventKind.FEATURE_VECTOR

        await model_handler("features.vector", feature_event)
        vote_rows = await bus.read("ml.vote", after_id="0-0")
        assert len(vote_rows) == 1
        vote = vote_rows[0][1]
        assert vote.kind is FleetEventKind.ML_VOTE
        assert vote.payload["intent"] == "LONG"
        assert vote.payload["execution_authority"] is False
        await bus.close()

    asyncio.run(scenario())


def test_unconfigured_ml_and_financial_roles_report_not_business_ready() -> None:
    async def scenario() -> None:
        bus = InMemoryEventBus()
        ml_service = next(item for item in AURA_FLEET if item.role is ServiceRole.ML)
        risk_service = next(item for item in AURA_FLEET if item.role is ServiceRole.RISK)
        ml_handler = build_prime_role_handler(ml_service, bus)
        risk_handler = build_prime_role_handler(risk_service, bus)
        assert ml_handler.ready is False
        assert "no AURA_PRIME_LINEAR_MODEL" in ml_handler.detail
        assert risk_handler.ready is False
        assert "pending explicit business wiring" in risk_handler.detail
        await bus.close()

    asyncio.run(scenario())


def test_sklearn_logistic_trainer_exports_portable_artifact() -> None:
    import pytest

    pytest.importorskip("sklearn")
    rows = [
        {"momentum": float(index - 20) / 20.0, "volatility": 0.1 + index / 1000.0}
        for index in range(40)
    ]
    labels = [0 if index < 20 else 1 for index in range(40)]
    artifact = SklearnLogisticTrainer().fit(
        rows,
        labels,
        model_key="prime-logistic",
        version="synthetic-v1",
        training_data_fingerprint="b" * 64,
        reliability=0.7,
        calibration=0.7,
    )
    assert artifact.feature_names == ("momentum", "volatility")
    assert len(artifact.coefficients) == 2
    assert artifact.probability({"momentum": 0.9, "volatility": 0.13}) > 0.5
    assert artifact.probability({"momentum": -0.9, "volatility": 0.11}) < 0.5
