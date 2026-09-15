from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from aura.interface.alerts import (
    AlertEvent,
    AlertSeverity,
    TelegramAlertConfig,
    TelegramAlertSink,
    TelegramCredentials,
)
from aura.interface.voice_alerts import LocalVoiceAnnouncer
from aura.interface.web_command_center import CommandCenterConfig
from aura.interface.web_command_center_v2 import CommandCenterV2Service
from aura.ops.backtest_gate import PHASE_SIX_EVIDENCE
from aura.ops.broker_conformance_gate import PHASE_FOUR_EVIDENCE
from aura.ops.ceo_decision_gate import PHASE_TEN_EVIDENCE
from aura.ops.core_contracts import PHASE_ONE_EVIDENCE
from aura.ops.knowledge_rag_gate import PHASE_EIGHT_EVIDENCE
from aura.ops.market_data_gate import PHASE_FIVE_EVIDENCE
from aura.ops.multi_agent_gate import PHASE_NINE_EVIDENCE
from aura.ops.paper_trading_gate import PHASE_TWELVE_EVIDENCE
from aura.ops.phase_gates import (
    build_sequential_phase_records,
    phase_is_pass,
    validate_phase_gate_ledger,
    write_phase_gate_ledger,
)
from aura.ops.repository_audit import PHASE_ZERO_EVIDENCE
from aura.ops.risk_engine_gate import PHASE_THREE_EVIDENCE
from aura.ops.state_engine_gate import PHASE_TWO_EVIDENCE
from aura.ops.strategy_research_gate import PHASE_SEVEN_EVIDENCE

OUTPUT_DIR = Path("artifacts/governance")
INTERFACE_REPORT = OUTPUT_DIR / "alert_ui_voice_validation.json"
PHASE_LEDGER = OUTPUT_DIR / "phase_gate_status.json"
PHASE_THIRTEEN_EVIDENCE = {"Alert delivery logs": INTERFACE_REPORT.as_posix()}
_FIXED_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_OWNER_TOKEN = "phase13-owner-token-with-at-least-32-characters"


class _Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, payload))
        return {"ok": True, "result": {"message_id": 1301}}


async def _alert_probe(receipt_path: Path) -> dict[str, bool]:
    transport = _Transport()
    sink = TelegramAlertSink(
        TelegramCredentials(bot_token="phase13-fake-token", chat_id="phase13-chat"),
        receipt_path,
        transport=transport,
        config=TelegramAlertConfig(max_attempts=1, base_retry_seconds=0),
    )
    alert = AlertEvent(
        alert_id="phase13-critical-alert",
        category="risk",
        severity=AlertSeverity.CRITICAL,
        title="Risk control test",
        message="Deterministic critical alert delivery probe",
        correlation_id="phase13-gate",
        created_at=_FIXED_TIME,
    )
    first = await sink.send(alert)
    second = await sink.send(alert)
    payload = transport.calls[0][1]
    return {
        "critical_alert_delivered": first.delivered,
        "delivery_receipt_durable": receipt_path.is_file(),
        "duplicate_alert_deduplicated": first == second and len(transport.calls) == 1,
        "critical_alert_not_silenced": payload.get("disable_notification") is False,
        "content_protection_enabled": payload.get("protect_content") is True,
    }


async def _voice_probe() -> dict[str, bool]:
    calls: list[tuple[list[str] | tuple[str, ...], dict[str, Any]]] = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))

    announcer = LocalVoiceAnnouncer(
        enabled=True,
        platform_name="win32",
        which=lambda name: "C:/Windows/powershell.exe" if name == "powershell.exe" else None,
        runner=runner,
    )
    spoken = await announcer.speak("AURA phase thirteen critical alert")
    command, kwargs = calls[0]
    return {
        "voice_available": announcer.available,
        "voice_probe_spoken": spoken,
        "voice_uses_argument_vector": isinstance(command, (list, tuple)),
        "voice_avoids_shell_interpolation": "shell" not in kwargs,
        "voice_text_passed_by_environment": (
            kwargs.get("env", {}).get("AURA_VOICE_TEXT")
            == "AURA phase thirteen critical alert"
        ),
    }


def build_operator_interface_artifact() -> dict[str, Any]:
    with TemporaryDirectory(prefix="aura-phase13-") as directory:
        base = Path(directory)
        service = CommandCenterV2Service(
            CommandCenterConfig(
                queue_path=base / "research.jsonl",
                api_token=_OWNER_TOKEN,
                owner_id="phase13-owner",
            )
        )
        live_status, live = service.handle_command("go live")
        paper_status, paper = service.handle_command("paper start")
        denied_status, denied = service.handle_command("research XAUUSD")
        research_status, research = service.handle_command(
            "research XAUUSD", owner_authenticated=True
        )
        status = service.status()
        alert_checks = asyncio.run(_alert_probe(base / "alert_receipts.jsonl"))
        voice_checks = asyncio.run(_voice_probe())

    checks = {
        **alert_checks,
        **voice_checks,
        "live_control_blocked": live_status == HTTPStatus.FORBIDDEN and not live["accepted"],
        "human_live_approval_required": bool(live.get("human_live_approval_required")),
        "paper_control_not_exposed_by_operator_ui": (
            paper_status == HTTPStatus.FORBIDDEN and not paper["accepted"]
        ),
        "research_requires_owner_auth": (
            denied_status == HTTPStatus.UNAUTHORIZED and not denied["accepted"]
        ),
        "authenticated_research_is_review_gated": (
            research_status == HTTPStatus.ACCEPTED
            and research["payload"]["auto_promotion_allowed"] is False
        ),
        "command_center_reports_live_money_disabled": status["live_money_enabled"] is False,
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"Phase 13 operator interface checks failed: {failed}")
    return {
        "schema_version": 1,
        "phase": 13,
        "decision": "PASS",
        "classification": "governed_operator_interface_ready",
        "checks": checks,
        "external_telegram_delivery_claimed": False,
        "external_voice_quality_claimed": False,
        "live_money_enabled": False,
    }


def _evidence_map() -> dict[int, dict[str, str]]:
    return {
        0: PHASE_ZERO_EVIDENCE,
        1: PHASE_ONE_EVIDENCE,
        2: PHASE_TWO_EVIDENCE,
        3: PHASE_THREE_EVIDENCE,
        4: PHASE_FOUR_EVIDENCE,
        5: PHASE_FIVE_EVIDENCE,
        6: PHASE_SIX_EVIDENCE,
        7: PHASE_SEVEN_EVIDENCE,
        8: PHASE_EIGHT_EVIDENCE,
        9: PHASE_NINE_EVIDENCE,
        10: PHASE_TEN_EVIDENCE,
        12: PHASE_TWELVE_EVIDENCE,
        13: PHASE_THIRTEEN_EVIDENCE,
    }


def write_operator_interface_artifact(root: Path) -> None:
    root = root.resolve()
    _write_json(root / INTERFACE_REPORT, build_operator_interface_artifact())
    records = build_sequential_phase_records(root, _evidence_map())
    write_phase_gate_ledger(root / PHASE_LEDGER, records, root=root)


def check_operator_interface_artifact(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    expected = _pretty_json(build_operator_interface_artifact())
    path = root / INTERFACE_REPORT
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"missing Phase 13 evidence: {INTERFACE_REPORT.as_posix()}")
    elif path.read_text(encoding="utf-8") != expected:
        errors.append(f"stale Phase 13 evidence: {INTERFACE_REPORT.as_posix()}")
    errors.extend(validate_phase_gate_ledger(root / PHASE_LEDGER, root))
    if not errors and not phase_is_pass(root / PHASE_LEDGER, root, 13):
        errors.append("Phase 13 is not PASS in the governance ledger")
    if phase_is_pass(root / PHASE_LEDGER, root, 15):
        errors.append("Phase 13 software evidence must not unlock Phase 15")
    return tuple(errors)


def _pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(value), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase-13 evidence")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.write:
        write_operator_interface_artifact(root)
        print("Phase 13: PASS (operator UI/alerts/voice software scope)")
        return 0
    errors = check_operator_interface_artifact(root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 13 operator interface artifact is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
