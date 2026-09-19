from __future__ import annotations

import os
from typing import Any

from .manifest import fleet_manifest, validate_fleet_manifest
from .providers import provider_status, supported_market_families


def distributed_fleet_status() -> dict[str, Any]:
    redis_url = os.environ.get("AURA_REDIS_URL", "redis://127.0.0.1:6379/0")
    return {
        "ok": not validate_fleet_manifest(),
        "architecture": "AURA_DISTRIBUTED_FLEET_V1",
        "event_transport": "redis_streams",
        "redis_url_configured": bool(redis_url),
        "redis_url": _redact_redis_url(redis_url),
        "services": list(fleet_manifest()),
        "providers": list(provider_status()),
        "market_families": list(supported_market_families()),
        "real_money_enabled": False,
        "fund_movement_enabled": False,
        "manifest_errors": list(validate_fleet_manifest()),
    }


def _redact_redis_url(value: str) -> str:
    if "@" not in value:
        return value
    prefix, suffix = value.rsplit("@", 1)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else "redis"
    return f"{scheme}://***@{suffix}"
