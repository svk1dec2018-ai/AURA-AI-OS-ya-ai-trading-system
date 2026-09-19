from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from urllib.parse import urlencode


class DhanFeedMode(IntEnum):
    TICKER = 15
    QUOTE = 17
    FULL = 21
    FULL_MARKET_DEPTH = 23


@dataclass(slots=True, frozen=True)
class DhanCredentials:
    client_id: str
    access_token: str

    def __post_init__(self) -> None:
        if not self.client_id.strip() or not self.access_token.strip():
            raise ValueError("Dhan client_id and access_token are required")


@dataclass(slots=True, frozen=True)
class DhanInstrumentSubscription:
    exchange_segment: str
    security_id: str

    def __post_init__(self) -> None:
        if not self.exchange_segment.strip() or not self.security_id.strip():
            raise ValueError("Dhan exchange_segment and security_id are required")


class DhanMarketFeedConfig:
    """Build Dhan v2 URLs/subscription payloads without persisting credentials.

    Credentials are supplied by the runtime secret provider and are never stored
    in repository configuration files or agent prompts.
    """

    base_url = "wss://api-feed.dhan.co"
    max_instruments_per_connection = 5000
    max_instruments_per_message = 100
    max_connections_per_user = 5

    @classmethod
    def websocket_url(cls, credentials: DhanCredentials) -> str:
        query = urlencode(
            {
                "version": "2",
                "token": credentials.access_token,
                "clientId": credentials.client_id,
                "authType": "2",
            }
        )
        return f"{cls.base_url}?{query}"

    @classmethod
    def subscription_messages(
        cls,
        instruments: tuple[DhanInstrumentSubscription, ...],
        *,
        mode: DhanFeedMode = DhanFeedMode.FULL,
    ) -> tuple[dict, ...]:
        if not instruments:
            raise ValueError("Dhan subscription requires at least one instrument")
        if len(instruments) > cls.max_instruments_per_connection:
            raise ValueError(
                f"Dhan connection supports at most {cls.max_instruments_per_connection} instruments"
            )
        messages: list[dict] = []
        for start in range(0, len(instruments), cls.max_instruments_per_message):
            batch = instruments[start : start + cls.max_instruments_per_message]
            messages.append(
                {
                    "RequestCode": int(mode),
                    "InstrumentCount": len(batch),
                    "InstrumentList": [
                        {
                            "ExchangeSegment": instrument.exchange_segment,
                            "SecurityId": instrument.security_id,
                        }
                        for instrument in batch
                    ],
                }
            )
        return tuple(messages)

    @staticmethod
    def disconnect_message() -> dict[str, int]:
        return {"RequestCode": 12}
