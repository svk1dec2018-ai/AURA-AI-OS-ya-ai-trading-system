from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from aura.fleet.manifest import AURA_FLEET, validate_fleet_manifest
from aura.fleet.providers import MARKET_PROVIDERS
from aura.ops.phase_gates import phase_is_pass, validate_phase_gate_ledger


@dataclass(slots=True, frozen=True)
class DoctorCheck:
    check_id: str
    passed: bool
    blocking: bool
    detail: str


@dataclass(slots=True, frozen=True)
class DoctorReport:
    profile: str
    checks: tuple[DoctorCheck, ...]
    software_production_ready: bool
    live_money_eligible: bool
    live_money_reason: str

    @property
    def ready(self) -> bool:
        return all(item.passed or not item.blocking for item in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "ready": self.ready,
            "software_production_ready": self.software_production_ready,
            "live_money_eligible": self.live_money_eligible,
            "live_money_reason": self.live_money_reason,
            "checks": [asdict(item) for item in self.checks],
        }


def _module_present(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except (OSError, URLError, ValueError):
        return False


def _env_present(*names: str) -> tuple[bool, tuple[str, ...]]:
    missing = tuple(name for name in names if not os.environ.get(name, "").strip())
    return not missing, missing


def _phase_checks(root: Path) -> tuple[DoctorCheck, bool]:
    ledger = root / "artifacts" / "governance" / "phase_gate_status.json"
    errors = validate_phase_gate_ledger(ledger, root)
    if errors:
        return (
            DoctorCheck(
                "governance-ledger",
                False,
                True,
                "invalid phase-gate ledger: " + "; ".join(errors),
            ),
        ), False

    required_software_phases = tuple(range(0, 11)) + (12, 13, 14)
    failed = tuple(
        phase for phase in required_software_phases if not phase_is_pass(ledger, root, phase)
    )
    checks = [
        DoctorCheck(
            "governance-ledger",
            True,
            True,
            "phase-gate ledger hashes and evidence validate",
        ),
        DoctorCheck(
            "software-phases",
            not failed,
            True,
            (
                "software phases 0-10 and 12-14 are PASS"
                if not failed
                else "software phase failures: " + ", ".join(map(str, failed))
            ),
        ),
    ]
    live_pass = phase_is_pass(ledger, root, 11) and phase_is_pass(ledger, root, 15)
    checks.append(
        DoctorCheck(
            "live-phases-11-15",
            live_pass,
            False,
            (
                "broker live-readiness and controlled-live phases are PASS"
                if live_pass
                else "expected gate: phases 11 and/or 15 are not PASS; live money stays blocked"
            ),
        )
    )
    return tuple(checks), live_pass


def build_report(root: Path, *, profile: str) -> DoctorReport:
    root = root.resolve()
    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            "python",
            sys.version_info >= (3, 11),
            True,
            f"Python {platform.python_version()} (requires >=3.11)",
        )
    )
    checks.append(
        DoctorCheck(
            "node",
            shutil.which("node") is not None,
            profile != "repository",
            "Node.js executable found" if shutil.which("node") else "Node.js not found",
        )
    )
    checks.append(
        DoctorCheck(
            "fleet-manifest",
            not validate_fleet_manifest(),
            True,
            (
                "nine-service fleet manifest valid"
                if not validate_fleet_manifest()
                else "fleet manifest invalid: " + "; ".join(validate_fleet_manifest())
            ),
        )
    )

    phase_checks, live_phase_pass = _phase_checks(root)
    checks.extend(phase_checks)

    live_ack = os.environ.get("AURA_LIVE_TRADING_ENABLED", "").strip()
    expected_ack = "I_UNDERSTAND_AND_APPROVE_LIVE_RISK"
    checks.append(
        DoctorCheck(
            "live-money-default-lock",
            live_ack != expected_ack,
            profile != "live",
            (
                "live-money acknowledgement remains disabled"
                if live_ack != expected_ack
                else "live-risk acknowledgement is enabled"
            ),
        )
    )

    if profile in {"install", "running", "mt5-demo", "all-market"}:
        checks.append(
            DoctorCheck(
                "redis-package",
                _module_present("redis"),
                True,
                "Redis client installed" if _module_present("redis") else "install .[distributed]",
            )
        )
        checks.append(
            DoctorCheck(
                "docker",
                shutil.which("docker") is not None,
                True,
                "Docker executable found" if shutil.which("docker") else "Docker not found",
            )
        )

    if profile in {"running", "mt5-demo", "all-market"}:
        redis_ok = _port_open("127.0.0.1", 6379)
        checks.append(
            DoctorCheck(
                "redis-running",
                redis_ok,
                True,
                "Redis reachable on 127.0.0.1:6379" if redis_ok else "Redis is not reachable",
            )
        )
        service_ports = tuple(service.port for service in AURA_FLEET)
        missing_ports = tuple(port for port in service_ports if not _port_open("127.0.0.1", port))
        checks.append(
            DoctorCheck(
                "fleet-services-running",
                not missing_ports,
                True,
                (
                    "all nine fleet health ports are reachable"
                    if not missing_ports
                    else "missing fleet ports: " + ", ".join(map(str, missing_ports))
                ),
            )
        )
        checks.append(
            DoctorCheck(
                "backend-running",
                _http_ok("http://127.0.0.1:8766/api/health"),
                True,
                "AURA backend healthy" if _http_ok("http://127.0.0.1:8766/api/health") else "AURA backend unavailable",
            )
        )
        checks.append(
            DoctorCheck(
                "dashboard-running",
                _http_ok("http://127.0.0.1:3100"),
                True,
                "AURA dashboard reachable" if _http_ok("http://127.0.0.1:3100") else "AURA dashboard unavailable",
            )
        )

    if profile in {"mt5-demo", "all-market"}:
        mt5_module = _module_present("MetaTrader5")
        checks.append(
            DoctorCheck(
                "mt5-python-bridge",
                mt5_module,
                True,
                "MetaTrader5 Python bridge installed" if mt5_module else "MetaTrader5 package missing",
            )
        )
        mt5_ok, mt5_missing = _env_present(
            "AURA_MT5_DEMO_LOGIN",
            "AURA_MT5_DEMO_PASSWORD",
            "AURA_MT5_DEMO_SERVER",
        )
        checks.append(
            DoctorCheck(
                "mt5-demo-config",
                mt5_ok,
                True,
                (
                    "MT5 DEMO configuration present"
                    if mt5_ok
                    else "missing: " + ", ".join(mt5_missing)
                ),
            )
        )

        if mt5_module and mt5_ok and platform.system() == "Windows":
            try:
                from aura.webapp.mt5_preflight import mt5_demo_preflight

                preflight = mt5_demo_preflight(max_symbols=50)
                broker_ready = (
                    preflight.get("ok") is True
                    and preflight.get("demo_verified") is True
                    and int(preflight.get("tradable_symbol_count", 0)) > 0
                    and preflight.get("market_clock_ok") is True
                )
                broker_detail = (
                    "MT5 DEMO broker preflight verified with tradable symbols and safe market clock"
                    if broker_ready
                    else "MT5 DEMO broker preflight failed: "
                    + str(preflight.get("error") or "account/market clock not ready")
                )
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
                broker_ready = False
                broker_detail = "MT5 DEMO broker preflight error: " + str(exc)
            checks.append(
                DoctorCheck(
                    "mt5-demo-broker-preflight",
                    broker_ready,
                    True,
                    broker_detail,
                )
            )

    if profile == "all-market":
        configured = tuple(
            key
            for key, spec in MARKET_PROVIDERS.items()
            if spec.configured() or spec.read_only_without_credentials
        )
        checks.append(
            DoctorCheck(
                "all-market-provider-registry",
                "mt5" in MARKET_PROVIDERS and len(MARKET_PROVIDERS) >= 6,
                True,
                "provider registry covers: " + ", ".join(sorted(MARKET_PROVIDERS)),
            )
        )
        checks.append(
            DoctorCheck(
                "configured-market-providers",
                bool(configured),
                True,
                "configured/read-only providers: " + ", ".join(sorted(configured)),
            )
        )

    software_ready = all(item.passed or not item.blocking for item in checks)
    human_approval = bool(os.environ.get("AURA_HUMAN_LIVE_APPROVAL_ID", "").strip())
    live_eligible = (
        software_ready
        and live_phase_pass
        and live_ack == expected_ack
        and human_approval
        and profile == "live"
    )
    live_reason = (
        "live eligibility checks satisfied"
        if live_eligible
        else "live money is not certified: broker-origin Phase 11/15 evidence and explicit human live approval remain required"
    )

    return DoctorReport(
        profile=profile,
        checks=tuple(checks),
        software_production_ready=software_ready,
        live_money_eligible=live_eligible,
        live_money_reason=live_reason,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Final AURA production-readiness doctor")
    parser.add_argument(
        "--profile",
        choices=("repository", "install", "running", "mt5-demo", "all-market", "live"),
        default="running",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = build_report(args.root, profile=args.profile)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print("AURA FINAL PRODUCTION DOCTOR")
        print("=" * 34)
        for check in report.checks:
            marker = "PASS" if check.passed else ("WARN" if not check.blocking else "FAIL")
            print(f"[{marker}] {check.check_id}: {check.detail}")
        print()
        print(
            "Software production ready: "
            + ("YES" if report.software_production_ready else "NO")
        )
        print("Live-money eligible: " + ("YES" if report.live_money_eligible else "NO"))
        print(report.live_money_reason)
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
