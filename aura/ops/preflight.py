from __future__ import annotations

import os
import platform
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from aura.research.lifecycle import StrategyStage


class DeploymentMode(str, Enum):
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"


@dataclass(slots=True, frozen=True)
class PreflightCheck:
    check_id: str
    passed: bool
    detail: str
    blocking: bool = True


@dataclass(slots=True, frozen=True)
class PreflightReport:
    mode: DeploymentMode
    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(item.passed or not item.blocking for item in self.checks)

    @property
    def blocking_failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(item for item in self.checks if item.blocking and not item.passed)


_CONNECTOR_ENV: dict[str, tuple[str, ...]] = {
    "public": (),
    "mt5_demo": (
        "AURA_MT5_DEMO_LOGIN",
        "AURA_MT5_DEMO_PASSWORD",
        "AURA_MT5_DEMO_SERVER",
    ),
    "dhan": ("AURA_DHAN_CLIENT_ID", "AURA_DHAN_ACCESS_TOKEN"),
    "shoonya": (
        "AURA_SHOONYA_USER_ID",
        "AURA_SHOONYA_ACCOUNT_ID",
        "AURA_SHOONYA_SESSION_TOKEN",
    ),
    "flattrade": (
        "AURA_FLATTRADE_USER_ID",
        "AURA_FLATTRADE_ACCOUNT_ID",
        "AURA_FLATTRADE_ACCESS_TOKEN",
    ),
    "oanda": ("AURA_OANDA_ACCOUNT_ID", "AURA_OANDA_ACCESS_TOKEN"),
}

_LIVE_ACK = "I_UNDERSTAND_AND_APPROVE_LIVE_RISK"


class ProductionPreflight:
    """Fail-closed startup validation for research, paper, demo and live modes.

    This gate validates configuration and durable-state prerequisites before any
    broker or model runtime is created. It does not certify profitability. Live
    mode additionally requires an APPROVED strategy and explicit human approval.
    """

    def __init__(
        self,
        *,
        mode: DeploymentMode,
        runtime_dir: Path,
        connectors: Sequence[str] = (),
        strategy_stage: StrategyStage | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.mode = mode
        self.runtime_dir = runtime_dir
        self.connectors = tuple(
            dict.fromkeys(item.strip().lower() for item in connectors)
        )
        self.strategy_stage = strategy_stage
        self.env = dict(os.environ if env is None else env)

    def run(self) -> PreflightReport:
        checks: list[PreflightCheck] = []
        checks.append(self._python_check())
        checks.append(self._runtime_dir_check())
        checks.extend(self._connector_checks())
        checks.extend(self._mode_checks())
        return PreflightReport(mode=self.mode, checks=tuple(checks))

    def _python_check(self) -> PreflightCheck:
        passed = sys.version_info >= (3, 11)
        return PreflightCheck(
            "python-version",
            passed,
            f"Python {platform.python_version()} (requires >=3.11)",
        )

    def _runtime_dir_check(self) -> PreflightCheck:
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.runtime_dir,
                prefix=".aura-preflight-",
                delete=False,
            ) as handle:
                handle.write("aura-preflight")
                path = Path(handle.name)
            path.unlink(missing_ok=True)
            passed = True
            detail = f"durable runtime path writable: {self.runtime_dir}"
        except OSError as exc:
            passed = False
            detail = f"runtime path is not writable: {exc}"
        return PreflightCheck("runtime-dir-writable", passed, detail)

    def _connector_checks(self) -> list[PreflightCheck]:
        checks: list[PreflightCheck] = []
        for connector in self.connectors:
            if connector not in _CONNECTOR_ENV:
                checks.append(
                    PreflightCheck(
                        f"connector-{connector}",
                        False,
                        f"unknown production connector profile: {connector}",
                    )
                )
                continue
            missing = [
                name
                for name in _CONNECTOR_ENV[connector]
                if not self.env.get(name, "").strip()
            ]
            detail = (
                "credentials/config present"
                if not missing
                else f"missing env: {', '.join(missing)}"
            )
            checks.append(
                PreflightCheck(
                    f"connector-{connector}",
                    not missing,
                    detail,
                )
            )
        return checks

    def _mode_checks(self) -> list[PreflightCheck]:
        if self.mode != DeploymentMode.LIVE:
            disabled = (
                self.env.get("AURA_LIVE_TRADING_ENABLED", "").strip() != _LIVE_ACK
            )
            return [
                PreflightCheck(
                    "live-money-disabled",
                    disabled,
                    (
                        "live-money acknowledgement is not enabled"
                        if disabled
                        else "live-risk acknowledgement must be unset outside LIVE mode"
                    ),
                )
            ]

        stage_ok = self.strategy_stage == StrategyStage.APPROVED
        human_approval = self.env.get("AURA_HUMAN_LIVE_APPROVAL_ID", "").strip()
        acknowledgement = self.env.get("AURA_LIVE_TRADING_ENABLED", "").strip()
        return [
            PreflightCheck(
                "approved-strategy",
                stage_ok,
                (
                    "strategy stage is APPROVED"
                    if stage_ok
                    else "live mode requires StrategyStage.APPROVED"
                ),
            ),
            PreflightCheck(
                "human-live-approval",
                bool(human_approval),
                (
                    "human approval id present"
                    if human_approval
                    else "AURA_HUMAN_LIVE_APPROVAL_ID missing"
                ),
            ),
            PreflightCheck(
                "explicit-live-risk-ack",
                acknowledgement == _LIVE_ACK,
                (
                    "explicit live-risk acknowledgement present"
                    if acknowledgement == _LIVE_ACK
                    else "AURA_LIVE_TRADING_ENABLED acknowledgement missing or invalid"
                ),
            ),
        ]
