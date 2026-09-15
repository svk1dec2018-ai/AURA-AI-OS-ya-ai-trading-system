from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aura.persistence.wal import JsonlWriteAheadLog


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    category: str = Field(min_length=1, max_length=80)
    severity: AlertSeverity
    title: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=12_000)
    correlation_id: str = Field(min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("alert timestamp must be timezone-aware")
        return value

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        payload.pop("created_at", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AlertDeliveryReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str
    alert_fingerprint: str
    channel: str = "telegram"
    destination_hash: str
    delivered: bool
    attempts: int = Field(ge=1)
    provider_message_id: str | None = None
    error_code: str | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("completed_at")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt timestamp must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class TelegramCredentials:
    bot_token: str = field(repr=False)
    chat_id: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.bot_token.strip() or not self.chat_id.strip():
            raise ValueError("Telegram bot token and chat id are required")


def load_telegram_credentials_from_env() -> TelegramCredentials:
    token = os.environ.get("AURA_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("AURA_TELEGRAM_CHAT_ID", "").strip()
    missing = []
    if not token:
        missing.append("AURA_TELEGRAM_BOT_TOKEN")
    if not chat_id:
        missing.append("AURA_TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(f"missing Telegram environment values: {', '.join(missing)}")
    return TelegramCredentials(bot_token=token, chat_id=chat_id)


class TelegramDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "telegram_error",
        retry_after_seconds: float | None = None,
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
        self.retriable = retriable


class TelegramTransport(Protocol):
    async def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class UrllibTelegramTransport:
    """Minimal HTTPS transport that never includes the tokenized URL in errors."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Telegram timeout must be positive")
        self.timeout_seconds = timeout_seconds

    async def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync, url, payload)

    def _sync(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            parsed = _safe_json_object(body)
            raise _telegram_error(parsed, fallback_code=str(exc.code)) from exc
        except (TimeoutError, URLError) as exc:
            raise TelegramDeliveryError(
                "Telegram transport failed",
                error_code="transport_error",
                retriable=True,
            ) from exc
        parsed = _safe_json_object(body)
        if not parsed:
            raise TelegramDeliveryError(
                "Telegram returned an invalid JSON response",
                error_code="invalid_response",
            )
        return parsed


@dataclass(slots=True, frozen=True)
class TelegramAlertConfig:
    max_attempts: int = 3
    base_retry_seconds: float = 0.5
    message_limit: int = 4000

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("Telegram max_attempts must be at least one")
        if self.base_retry_seconds < 0:
            raise ValueError("Telegram retry delay cannot be negative")
        if not 256 <= self.message_limit <= 4096:
            raise ValueError("Telegram message_limit must be between 256 and 4096")


class TelegramAlertSink:
    """Durable, deduplicated Telegram delivery with explicit receipts."""

    def __init__(
        self,
        credentials: TelegramCredentials,
        receipt_path: str | Path,
        *,
        transport: TelegramTransport | None = None,
        config: TelegramAlertConfig | None = None,
        sleep=asyncio.sleep,
    ) -> None:
        self.credentials = credentials
        self.transport = transport or UrllibTelegramTransport()
        self.config = config or TelegramAlertConfig()
        self.sleep = sleep
        self.journal = JsonlWriteAheadLog(receipt_path)
        self._delivered: dict[str, AlertDeliveryReceipt] = {}
        self._recover()

    async def send(self, alert: AlertEvent) -> AlertDeliveryReceipt:
        existing = self._delivered.get(alert.alert_id)
        if existing is not None:
            if existing.alert_fingerprint != alert.fingerprint:
                raise RuntimeError(f"alert id reused with different content: {alert.alert_id}")
            return existing

        text = _render_alert(alert, limit=self.config.message_limit)
        url = f"https://api.telegram.org/bot{self.credentials.bot_token}/sendMessage"
        payload = {
            "chat_id": self.credentials.chat_id,
            "text": text,
            "disable_notification": alert.severity == AlertSeverity.INFO,
            "protect_content": True,
        }
        last_error: TelegramDeliveryError | None = None
        attempts = 0
        for attempt in range(1, self.config.max_attempts + 1):
            attempts = attempt
            try:
                response = await self.transport.post_json(url, payload)
                message_id = _provider_message_id(response)
            except TelegramDeliveryError as exc:
                last_error = exc
                if not exc.retriable or attempt >= self.config.max_attempts:
                    break
                delay = (
                    exc.retry_after_seconds
                    if exc.retry_after_seconds is not None
                    else self.config.base_retry_seconds * (2 ** (attempt - 1))
                )
                await self.sleep(delay)
                continue

            receipt = self._receipt(
                alert,
                delivered=True,
                attempts=attempt,
                provider_message_id=message_id,
            )
            self._append_receipt(receipt)
            self._delivered[alert.alert_id] = receipt
            return receipt

        if last_error is None:
            last_error = TelegramDeliveryError(
                "Telegram delivery failed without an error response",
                error_code="unknown_failure",
            )
        receipt = self._receipt(
            alert,
            delivered=False,
            attempts=attempts or 1,
            error_code=last_error.error_code,
        )
        self._append_receipt(receipt)
        return receipt

    def _receipt(
        self,
        alert: AlertEvent,
        *,
        delivered: bool,
        attempts: int,
        provider_message_id: str | None = None,
        error_code: str | None = None,
    ) -> AlertDeliveryReceipt:
        return AlertDeliveryReceipt(
            alert_id=alert.alert_id,
            alert_fingerprint=alert.fingerprint,
            destination_hash=_destination_hash(self.credentials.chat_id),
            delivered=delivered,
            attempts=attempts,
            provider_message_id=provider_message_id,
            error_code=error_code,
        )

    def _append_receipt(self, receipt: AlertDeliveryReceipt) -> None:
        self.journal.append(
            event_type=(
                "telegram_delivery_succeeded"
                if receipt.delivered
                else "telegram_delivery_failed"
            ),
            payload={"receipt": receipt.model_dump(mode="json")},
            correlation_id=receipt.alert_id,
        )

    def _recover(self) -> None:
        for event in self.journal.read_all():
            if event.event_type not in {
                "telegram_delivery_succeeded",
                "telegram_delivery_failed",
            }:
                raise RuntimeError(f"unknown Telegram receipt event: {event.event_type}")
            try:
                receipt = AlertDeliveryReceipt.model_validate(event.payload["receipt"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("invalid Telegram receipt event") from exc
            if receipt.channel != "telegram":
                raise RuntimeError("Telegram receipt journal contains another channel")
            if receipt.delivered:
                existing = self._delivered.get(receipt.alert_id)
                if existing is not None and existing != receipt:
                    raise RuntimeError(f"conflicting Telegram delivery receipt: {receipt.alert_id}")
                self._delivered[receipt.alert_id] = receipt


def _safe_json_object(body: str) -> dict[str, Any]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _telegram_error(response: dict[str, Any], *, fallback_code: str) -> TelegramDeliveryError:
    parameters = response.get("parameters")
    retry_after = (
        parameters.get("retry_after")
        if isinstance(parameters, dict)
        else None
    )
    try:
        retry_seconds = float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        retry_seconds = None
    code = str(response.get("error_code") or fallback_code)
    description = str(response.get("description") or "Telegram request failed")
    retriable = code.isdigit() and (code == "429" or 500 <= int(code) < 600)
    return TelegramDeliveryError(
        description[:300],
        error_code=code,
        retry_after_seconds=retry_seconds,
        retriable=retriable,
    )


def _provider_message_id(response: dict[str, Any]) -> str:
    if response.get("ok") is not True:
        raise _telegram_error(response, fallback_code="api_error")
    result = response.get("result")
    if not isinstance(result, dict):
        raise TelegramDeliveryError(
            "Telegram response is missing the sent message",
            error_code="invalid_response",
        )
    message_id = str(result.get("message_id", "")).strip()
    if not message_id:
        raise TelegramDeliveryError(
            "Telegram response is missing message_id",
            error_code="invalid_response",
        )
    return message_id


def _destination_hash(chat_id: str) -> str:
    return hashlib.sha256(chat_id.encode("utf-8")).hexdigest()


def _render_alert(alert: AlertEvent, *, limit: int) -> str:
    prefix = f"[AURA {alert.severity.value}] {alert.title}"
    suffix = (
        f"\nCategory: {alert.category}"
        f"\nCorrelation: {alert.correlation_id}"
        f"\nTime: {alert.created_at.astimezone(UTC).isoformat()}"
    )
    available = max(1, limit - len(prefix) - len(suffix) - 2)
    message = " ".join(alert.message.split())
    if len(message) > available:
        message = f"{message[: max(1, available - 3)]}..."
    return f"{prefix}\n\n{message}{suffix}"
