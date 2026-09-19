import asyncio
from datetime import UTC, datetime

import pytest

from aura.fleet.bus import InMemoryEventBus
from aura.fleet.events import FleetEvent, FleetEventKind
from aura.fleet.manifest import ServiceRole, validate_fleet_manifest
from aura.fleet.providers import MARKET_PROVIDERS, MarketFamily, provider_status
from aura.fleet.status import distributed_fleet_status


def test_in_memory_event_bus_preserves_stream_order() -> None:
    async def scenario():
        bus = InMemoryEventBus()
        first = FleetEvent(
            kind=FleetEventKind.MARKET_TICK,
            source="test",
            symbol="XAUUSD",
            venue="MT5",
            occurred_at=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
            payload={"price": "2600.10"},
        )
        second = FleetEvent(
            kind=FleetEventKind.FEATURE_VECTOR,
            source="test",
            symbol="XAUUSD",
            venue="MT5",
            occurred_at=datetime(2026, 9, 19, 10, 0, 1, tzinfo=UTC),
            payload={"rsi": 55},
        )
        first_id = await bus.publish("market.tick", first)
        second_id = await bus.publish("market.tick", second)
        rows = await bus.read("market.tick", after_id="0-0", count=10)
        assert [item[0] for item in rows] == [first_id, second_id]
        assert rows[0][1].kind is FleetEventKind.MARKET_TICK
        assert rows[1][1].payload["rsi"] == 55
        await bus.close()

    asyncio.run(scenario())


def test_in_memory_bus_rejects_invalid_cursor() -> None:
    async def scenario():
        bus = InMemoryEventBus()
        with pytest.raises(ValueError, match="invalid stream id"):
            await bus.read("x", after_id="bad")
        await bus.close()

    asyncio.run(scenario())


def test_fleet_manifest_has_all_nine_roles_and_locked_authority() -> None:
    assert validate_fleet_manifest() == ()
    status = distributed_fleet_status()
    services = status["services"]
    assert len(services) == 9
    roles = {item["role"] for item in services}
    assert roles == {item.value for item in ServiceRole}
    authority = {
        item["role"]
        for item in services
        if item["financial_authority"]
    }
    assert authority == {"risk", "executor"}
    assert status["real_money_enabled"] is False
    assert status["fund_movement_enabled"] is False


def test_all_market_registry_covers_target_families() -> None:
    families = {
        family
        for item in provider_status()
        for family in item["families"]
    }
    assert families == {item.value for item in MarketFamily}
    assert set(MARKET_PROVIDERS) == {
        "mt5",
        "dhan",
        "angel_one",
        "binance",
        "kraken",
        "oanda",
    }


def test_provider_status_never_exposes_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("AURA_BINANCE_API_KEY", "secret-key-value")
    monkeypatch.setenv("AURA_BINANCE_API_SECRET", "secret-secret-value")
    payload = MARKET_PROVIDERS["binance"].status()
    rendered = repr(payload)
    assert payload["configured"] is True
    assert "secret-key-value" not in rendered
    assert "secret-secret-value" not in rendered
    assert payload["missing_credentials"] == []
    assert payload["execution_supported"] is False


def test_only_mt5_is_currently_marked_execution_supported() -> None:
    supported = {
        key
        for key, spec in MARKET_PROVIDERS.items()
        if spec.execution_supported
    }
    assert supported == {"mt5"}


def test_redis_url_credentials_are_redacted(monkeypatch) -> None:
    monkeypatch.setenv("AURA_REDIS_URL", "redis://user:password@127.0.0.1:6379/0")
    status = distributed_fleet_status()
    assert status["redis_url"] == "redis://***@127.0.0.1:6379/0"
    assert "password" not in repr(status)
