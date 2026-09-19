from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .manifest import AURA_FLEET, FleetService


@dataclass(slots=True)
class ManagedProcess:
    service: FleetService
    process: subprocess.Popen[str]
    log_handle: IO[str]
    restart_count: int = 0
    last_started_at: float = 0.0


class FleetProcessSupervisor:
    """Own and restart the nine AURA fleet processes.

    Restarts repair infrastructure only. The supervisor does not clear a
    financial kill switch, approve live money or submit orders.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        runtime_dir: Path,
        python_executable: str | None = None,
        restart_delay_seconds: float = 2.0,
        max_restarts: int = 10,
    ) -> None:
        if restart_delay_seconds < 0:
            raise ValueError("restart_delay_seconds cannot be negative")
        if max_restarts < 0:
            raise ValueError("max_restarts cannot be negative")
        self.redis_url = redis_url
        self.runtime_dir = runtime_dir
        self.python_executable = python_executable or sys.executable
        self.restart_delay_seconds = restart_delay_seconds
        self.max_restarts = max_restarts
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, ManagedProcess] = {}
        self._stopping = False

    def start_all(self) -> None:
        for service in AURA_FLEET:
            if service.service_id not in self._processes:
                self._processes[service.service_id] = self._spawn(service, restart_count=0)

    def poll_once(self) -> tuple[dict[str, object], ...]:
        snapshots: list[dict[str, object]] = []
        for service in AURA_FLEET:
            managed = self._processes.get(service.service_id)
            if managed is None:
                snapshots.append(
                    {
                        "service_id": service.service_id,
                        "state": "not_started",
                        "restart_count": 0,
                    }
                )
                continue

            code = managed.process.poll()
            if code is not None and not self._stopping:
                if (
                    service.restartable
                    and managed.restart_count < self.max_restarts
                ):
                    restart_count = managed.restart_count + 1
                    managed.log_handle.close()
                    if self.restart_delay_seconds:
                        time.sleep(self.restart_delay_seconds)
                    managed = self._spawn(service, restart_count=restart_count)
                    self._processes[service.service_id] = managed
                    code = None

            snapshots.append(
                {
                    "service_id": service.service_id,
                    "role": service.role.value,
                    "pid": managed.process.pid,
                    "state": "running" if code is None else "exited",
                    "exit_code": code,
                    "restart_count": managed.restart_count,
                    "financial_authority": service.financial_authority,
                }
            )
        return tuple(snapshots)

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.start_all()
        try:
            while True:
                self.poll_once()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_all()

    def stop_all(self, *, timeout_seconds: float = 8.0) -> None:
        self._stopping = True
        for managed in self._processes.values():
            if managed.process.poll() is None:
                managed.process.terminate()
        deadline = time.monotonic() + timeout_seconds
        for managed in self._processes.values():
            remaining = max(0.0, deadline - time.monotonic())
            if managed.process.poll() is None:
                try:
                    managed.process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    managed.process.kill()
                    managed.process.wait(timeout=2)
            managed.log_handle.close()

    def status(self) -> tuple[dict[str, object], ...]:
        return self.poll_once()

    def _spawn(
        self,
        service: FleetService,
        *,
        restart_count: int,
    ) -> ManagedProcess:
        log_path = self.runtime_dir / f"{service.service_id}.log"
        log_handle = log_path.open("a", encoding="utf-8")
        env = dict(os.environ)
        env["AURA_REDIS_URL"] = self.redis_url
        env["AURA_FLEET_SERVICE_ID"] = service.service_id
        command = [
            self.python_executable,
            "-m",
            "aura.fleet.service_runner",
            "--service-id",
            service.service_id,
            "--redis-url",
            self.redis_url,
        ]
        process = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return ManagedProcess(
            service=service,
            process=process,
            log_handle=log_handle,
            restart_count=restart_count,
            last_started_at=time.monotonic(),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AURA nine-service fleet supervisor")
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("AURA_REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path("runtime") / "fleet",
    )
    parser.add_argument("--status-json", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    supervisor = FleetProcessSupervisor(
        redis_url=args.redis_url,
        runtime_dir=args.runtime_dir,
    )
    if args.status_json:
        supervisor.start_all()
        try:
            print(json.dumps(supervisor.status(), indent=2))
        finally:
            supervisor.stop_all()
        return 0
    supervisor.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
