from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from aura.interface.alerts import (
    AlertDeliveryReceipt,
    AlertEvent,
    AlertSeverity,
    TelegramAlertConfig,
    TelegramAlertSink,
    TelegramCredentials,
    TelegramDeliveryError,
    load_telegram_credentials_from_env,
)
from aura.persistence.wal import JsonlWriteAheadLog


class FakeTransport:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((url, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        return response


def alert(**changes: object) -> AlertEvent:
    values: dict[str, object] = {
        "alert_id": "alert-1",
        "category": "risk",
        "severity": AlertSeverity.CRITICAL,
        "title": "Risk veto",
        "message": "Daily loss limit blocked the proposed order.",
        "correlation_id": "decision-1",
    }
    values.update(changes)
    return AlertEvent(**values)


def test_credentials_are_env_only_and_repr_is_redacted(monkeypatch) -> None:
    monkeypatch.delenv("AURA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("AURA_TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(RuntimeError, match="AURA_TELEGRAM_BOT_TOKEN"):
        load_telegram_credentials_from_env()

    monkeypatch.setenv("AURA_TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("AURA_TELEGRAM_CHAT_ID", "private-chat")
    credentials = load_telegram_credentials_from_env()
    assert "secret-token" not in repr(credentials)
    assert "private-chat" not in repr(credentials)


@pytest.mark.asyncio
async def test_success_is_durable_secret_free_and_deduplicated(tmp_path) -> None:
    journal = tmp_path / "telegram.jsonl"
    credentials = TelegramCredentials("secret-token", "private-chat")
    transport = FakeTransport({"ok": True, "result": {"message_id": 42}})
    sink = TelegramAlertSink(credentials, journal, transport=transport)

    receipt = await sink.send(alert())

    assert receipt.delivered is True
    assert receipt.provider_message_id == "42"
    assert receipt.destination_hash != "private-chat"
    assert transport.calls[0][1]["protect_content"] is True
    raw = journal.read_text(encoding="utf-8")
    assert "secret-token" not in raw
    assert "private-chat" not in raw

    restarted_transport = FakeTransport()
    restarted = TelegramAlertSink(credentials, journal, transport=restarted_transport)
    assert await restarted.send(alert()) == receipt
    assert restarted_transport.calls == []


@pytest.mark.asyncio
async def test_reused_alert_id_with_different_content_is_rejected(tmp_path) -> None:
    sink = TelegramAlertSink(
        TelegramCredentials("token", "chat"),
        tmp_path / "receipts.jsonl",
        transport=FakeTransport({"ok": True, "result": {"message_id": 1}}),
    )
    await sink.send(alert())
    with pytest.raises(RuntimeError, match="different content"):
        await sink.send(alert(message="changed"))


@pytest.mark.asyncio
async def test_rate_limit_honors_retry_after_then_succeeds(tmp_path) -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    transport = FakeTransport(
        TelegramDeliveryError(
            "retry",
            error_code="429",
            retry_after_seconds=2.0,
            retriable=True,
        ),
        {"ok": True, "result": {"message_id": 9}},
    )
    sink = TelegramAlertSink(
        TelegramCredentials("token", "chat"),
        tmp_path / "receipts.jsonl",
        transport=transport,
        sleep=sleep,
    )
    receipt = await sink.send(alert())
    assert receipt.delivered is True
    assert receipt.attempts == 2
    assert delays == [2.0]


@pytest.mark.asyncio
async def test_non_retriable_failure_is_recorded_and_can_be_retried(tmp_path) -> None:
    journal = tmp_path / "receipts.jsonl"
    credentials = TelegramCredentials("token", "chat")
    failed = TelegramAlertSink(
        credentials,
        journal,
        transport=FakeTransport(
            TelegramDeliveryError("forbidden", error_code="403", retriable=False)
        ),
    )
    receipt = await failed.send(alert())
    assert (receipt.delivered, receipt.attempts, receipt.error_code) == (False, 1, "403")

    retry = TelegramAlertSink(
        credentials,
        journal,
        transport=FakeTransport({"ok": True, "result": {"message_id": 10}}),
    )
    assert (await retry.send(alert())).delivered is True


@pytest.mark.asyncio
async def test_invalid_provider_response_fails_closed(tmp_path) -> None:
    sink = TelegramAlertSink(
        TelegramCredentials("token", "chat"),
        tmp_path / "receipts.jsonl",
        transport=FakeTransport({"ok": True, "result": {}}),
    )
    receipt = await sink.send(alert())
    assert receipt.delivered is False
    assert receipt.error_code == "invalid_response"


@pytest.mark.asyncio
async def test_message_is_normalized_and_truncated_to_configured_limit(tmp_path) -> None:
    transport = FakeTransport({"ok": True, "result": {"message_id": 11}})
    sink = TelegramAlertSink(
        TelegramCredentials("token", "chat"),
        tmp_path / "receipts.jsonl",
        transport=transport,
        config=TelegramAlertConfig(message_limit=256),
    )
    await sink.send(alert(message="word \n " * 1_500))
    rendered = transport.calls[0][1]["text"]
    assert isinstance(rendered, str)
    assert len(rendered) <= 256


def test_unknown_journal_event_blocks_recovery(tmp_path) -> None:
    journal = tmp_path / "receipts.jsonl"
    JsonlWriteAheadLog(journal).append(
        event_type="unknown",
        payload={},
        correlation_id="alert-1",
    )
    with pytest.raises(RuntimeError, match="unknown Telegram receipt event"):
        TelegramAlertSink(TelegramCredentials("token", "chat"), journal)


@pytest.mark.parametrize("model", [AlertEvent, AlertDeliveryReceipt])
def test_alert_timestamps_must_be_timezone_aware(model) -> None:
    if model is AlertEvent:
        with pytest.raises(ValidationError, match="timezone-aware"):
            alert(created_at=datetime(2026, 1, 1))  # noqa: DTZ001 - invalid input under test
    else:
        with pytest.raises(ValidationError, match="timezone-aware"):
            model(
                alert_id="a",
                alert_fingerprint="f",
                destination_hash="h",
                delivered=True,
                attempts=1,
                completed_at=datetime(2026, 1, 1),  # noqa: DTZ001 - invalid input under test
            )
