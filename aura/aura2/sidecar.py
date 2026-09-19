from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .external_artifact import ExternalResearchArtifact, ExternalResearchIntake
from .opensource_registry import PROJECTS
from .research_gateway import GatewayDecision

_DEFAULT_ENV_KEYS = (
    "HOME",
    "LOCALAPPDATA",
    "OLLAMA_HOST",
    "PATH",
    "PYTHONPATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
)
_FORBIDDEN_ENV_FRAGMENTS = (
    "BROKER",
    "DHAN",
    "MT5",
    "OANDA",
    "BINANCE",
    "KRAKEN",
    "ANGEL",
    "ZERODHA",
    "SHOONYA",
    "API_SECRET",
    "PRIVATE_KEY",
)


@dataclass(frozen=True, slots=True)
class SidecarSpec:
    project_key: str
    command: tuple[str, ...]
    cwd: Path | None = None
    timeout_seconds: float = 300.0
    allowed_env_keys: tuple[str, ...] = _DEFAULT_ENV_KEYS
    max_output_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if self.project_key not in PROJECTS:
            raise ValueError(f"unknown AURA 2 project: {self.project_key}")
        if not self.command or not all(part.strip() for part in self.command):
            raise ValueError("sidecar command must contain non-empty arguments")
        if not 1.0 <= self.timeout_seconds <= 3600.0:
            raise ValueError("sidecar timeout must be between 1 and 3600 seconds")
        if not 1024 <= self.max_output_bytes <= 20_000_000:
            raise ValueError("max_output_bytes must be between 1KB and 20MB")
        for name in self.allowed_env_keys:
            upper = name.upper()
            if any(fragment in upper for fragment in _FORBIDDEN_ENV_FRAGMENTS):
                raise ValueError(f"broker/secret environment variable is forbidden: {name}")


@dataclass(frozen=True, slots=True)
class SidecarRequest:
    request_id: str
    objective: str
    symbol: str
    timeframe: str
    context: dict[str, Any]

    def to_json(self, project_key: str) -> str:
        payload = {
            "schema_version": 1,
            "project": project_key,
            "request_id": self.request_id,
            "objective": self.objective,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "context": self.context,
            "research_only": True,
            "live_approved": False,
            "execution_authority": False,
            "risk_authority": False,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True, slots=True)
class SidecarResult:
    artifact: ExternalResearchArtifact
    decision: GatewayDecision
    stderr: str


class ResearchSidecarRunner:
    """Run an isolated local research framework with no broker-secret inheritance.

    The sidecar protocol uses JSON on stdin/stdout. A sidecar may research, train,
    backtest or deliberate, but its output can only enter AURA at RESEARCH stage.
    """

    def __init__(self, intake: ExternalResearchIntake | None = None) -> None:
        self.intake = intake or ExternalResearchIntake()

    def run(self, spec: SidecarSpec, request: SidecarRequest) -> SidecarResult:
        environment = {
            key: os.environ[key]
            for key in spec.allowed_env_keys
            if key in os.environ
        }
        completed = subprocess.run(
            list(spec.command),
            input=request.to_json(spec.project_key),
            text=True,
            capture_output=True,
            cwd=str(spec.cwd) if spec.cwd is not None else None,
            env=environment,
            timeout=spec.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-2000:]
            raise RuntimeError(
                f"{PROJECTS[spec.project_key].name} sidecar failed "
                f"with exit code {completed.returncode}: {detail}"
            )
        stdout_bytes = completed.stdout.encode("utf-8")
        if len(stdout_bytes) > spec.max_output_bytes:
            raise RuntimeError("sidecar output exceeded configured size limit")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("sidecar stdout must be one valid JSON object") from exc
        if not isinstance(payload, dict):
            raise TypeError("sidecar stdout must decode to a JSON object")
        payload_source = str(payload.get("source", ""))
        if payload_source != spec.project_key:
            raise ValueError(
                f"sidecar source mismatch: expected {spec.project_key}, got {payload_source or 'missing'}"
            )
        artifact, decision = self.intake.ingest(payload)
        return SidecarResult(
            artifact=artifact,
            decision=decision,
            stderr=completed.stderr[-4000:],
        )
