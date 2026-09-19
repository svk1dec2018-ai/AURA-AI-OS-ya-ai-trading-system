from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .bus import RedisStreamsEventBus
from .manifest import AURA_FLEET, FleetService
from aura.prime.service_handlers import build_prime_role_handler

from .worker import FleetWorker


def _service_by_id(service_id: str) -> FleetService:
    for service in AURA_FLEET:
        if service.service_id == service_id:
            return service
    raise ValueError(f"unknown fleet service: {service_id}")


def _health_handler(service: FleetService, handler):
    class HealthHandler(BaseHTTPRequestHandler):
        server_version = "AuraFleetHealth/1.0"

        def do_GET(self) -> None:
            if self.path not in {"/", "/health"}:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(
                {
                    "ok": True,
                    "service_id": service.service_id,
                    "role": service.role.value,
                    "financial_authority": service.financial_authority,
                    "real_money_enabled": False,
                    "business_ready": bool(getattr(handler, "ready", False)),
                    "business_detail": str(
                        getattr(handler, "detail", "business handler unavailable")
                    ),
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return HealthHandler


async def _run(service: FleetService, redis_url: str, heartbeat: float) -> int:
    bus = RedisStreamsEventBus(redis_url)
    if not await bus.ping():
        raise RuntimeError("Redis ping failed")

    handler = build_prime_role_handler(service, bus)
    worker = FleetWorker(
        service,
        bus,
        heartbeat_seconds=heartbeat,
        handler=handler,
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", service.port),
        _health_handler(service, handler),
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"{service.service_id}-health",
        daemon=True,
    )
    thread.start()

    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        worker.stop()

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        try:
            loop.add_signal_handler(signal_value, request_stop)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await worker.run()
    finally:
        server.shutdown()
        server.server_close()
        await bus.close()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one AURA distributed fleet service")
    parser.add_argument("--service-id", required=True)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("AURA_REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    service = _service_by_id(args.service_id)
    return asyncio.run(_run(service, args.redis_url, args.heartbeat_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
