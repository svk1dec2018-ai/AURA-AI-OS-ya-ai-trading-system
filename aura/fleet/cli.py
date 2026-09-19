from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os

from .bus import RedisStreamsEventBus
from .status import distributed_fleet_status


async def _redis_check(url: str) -> dict[str, object]:
    try:
        redis_exceptions = importlib.import_module("redis.exceptions")
    except ModuleNotFoundError as exc:
        return {
            "configured": False,
            "reachable": False,
            "error": f"ModuleNotFoundError: {exc}",
        }

    bus = RedisStreamsEventBus(url)
    error_types = (
        OSError,
        TimeoutError,
        ConnectionError,
        redis_exceptions.RedisError,
    )
    try:
        return {"configured": True, "reachable": await bus.ping(), "error": None}
    except error_types as exc:
        return {
            "configured": True,
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        await bus.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect AURA distributed fleet readiness")
    parser.add_argument("--check-redis", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    payload = distributed_fleet_status()
    if args.check_redis:
        payload["redis"] = asyncio.run(
            _redis_check(os.environ.get("AURA_REDIS_URL", "redis://127.0.0.1:6379/0"))
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
