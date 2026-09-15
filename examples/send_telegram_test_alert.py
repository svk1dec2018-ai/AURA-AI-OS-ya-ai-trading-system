"""Send one explicit, non-trading Telegram delivery test."""

import asyncio
from pathlib import Path

from aura.interface.alerts import (
    AlertEvent,
    AlertSeverity,
    TelegramAlertSink,
    load_telegram_credentials_from_env,
)


async def main() -> int:
    sink = TelegramAlertSink(
        load_telegram_credentials_from_env(),
        Path("runtime/alerts/telegram_receipts.jsonl"),
    )
    receipt = await sink.send(
        AlertEvent(
            category="system",
            severity=AlertSeverity.INFO,
            title="AURA Telegram delivery test",
            message="Alert delivery works. No order was created or submitted.",
            correlation_id="manual-telegram-test",
        )
    )
    print(receipt.model_dump_json(indent=2))
    return 0 if receipt.delivered else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
