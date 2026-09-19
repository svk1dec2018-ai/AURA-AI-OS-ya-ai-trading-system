import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from aura.fleet.bus import InMemoryEventBus
from aura.fleet.events import FleetEvent, FleetEventKind
from aura.fleet.manifest import AURA_FLEET
from aura.fleet.streaming import RedisFleetSSE
from aura.fleet.worker import FleetWorker


def test_worker_emits_health_without_business_fabrication() -> None:
    async def scenario():
        bus = InMemoryEventBus()
        service = next(item for item in AURA_FLEET if item.service_id == "aura-ml")
        worker = FleetWorker(service, bus, heartbeat_seconds=0.01)
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.03)
        worker.stop()
        await task
        rows = await bus.read("system.health", after_id="0-0", count=50)
        assert rows
        assert all(event.kind is FleetEventKind.SYSTEM_HEALTH for _, event in rows)
        assert any(event.payload["service_id"] == "aura-ml" for _, event in rows)
        assert not await bus.read("ml.vote", after_id="0-0", count=10)

    asyncio.run(scenario())


def test_in_memory_latest_cursor_matches_redis_semantics() -> None:
    async def scenario():
        bus = InMemoryEventBus()
        first = FleetEvent(
            kind=FleetEventKind.SYSTEM_HEALTH,
            source="test",
            occurred_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        )
        await bus.publish("system.health", first)
        assert await bus.read("system.health", after_id="$", count=10) == ()

    asyncio.run(scenario())


class FakeRedisClient:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def ping(self):
        return True

    def xread(self, _streams, block=None, count=None):
        self.calls += 1
        if self.calls == 1:
            payload = json.dumps(
                FleetEvent(
                    kind=FleetEventKind.SYSTEM_HEALTH,
                    source="aura-data",
                    payload={"state": "running"},
                ).model_dump(mode="json"),
                default=str,
            )
            return [(
                "aura:system.health",
                [("1-0", {"event": payload})],
            )]
        return []

    def close(self):
        self.closed = True


def test_sse_reader_serializes_redis_fleet_event() -> None:
    client = FakeRedisClient()
    reader = RedisFleetSSE("redis://unused", client=client)
    assert reader.ping() is True
    iterator = reader.iter_sse(("system.health",), duration_seconds=1.0, block_ms=1)
    first = next(iterator).decode("utf-8")
    assert "system.health|1-0" in first
    assert '"source":"aura-data"' in first
    assert '"state":"running"' in first
    reader.close()
    assert client.closed is True


def test_beginner_fleet_launchers_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    start_cmd = root / "START_AURA_FLEET.cmd"
    start_ps = root / "scripts" / "start_aura_fleet.ps1"
    stop_cmd = root / "STOP_AURA_FLEET.cmd"
    assert start_cmd.exists()
    assert start_ps.exists()
    assert stop_cmd.exists()
    text = start_ps.read_text(encoding="utf-8")
    assert "redis:7-alpine" in text
    assert "aura.fleet.process_supervisor" in text
    assert "AURA FLEET READY" in text
