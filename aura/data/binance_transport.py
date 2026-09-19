from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote


class BinanceStreamEnvironment(str, Enum):
    PRODUCTION = "production"
    TESTNET = "testnet"
    MARKET_DATA_ONLY = "market_data_only"


@dataclass(slots=True, frozen=True)
class BinanceStreamConfig:
    environment: BinanceStreamEnvironment = BinanceStreamEnvironment.PRODUCTION

    @property
    def base_url(self) -> str:
        return {
            BinanceStreamEnvironment.PRODUCTION: "wss://stream.binance.com:9443",
            BinanceStreamEnvironment.TESTNET: "wss://stream.testnet.binance.vision",
            BinanceStreamEnvironment.MARKET_DATA_ONLY: "wss://data-stream.binance.vision",
        }[self.environment]

    def raw_stream_url(self, stream_name: str) -> str:
        normalized = _stream_name(stream_name)
        return f"{self.base_url}/ws/{quote(normalized, safe='@_') }"

    def combined_stream_url(self, stream_names: tuple[str, ...]) -> str:
        if not stream_names:
            raise ValueError("combined Binance stream requires at least one stream")
        normalized = [_stream_name(name) for name in stream_names]
        joined = "/".join(quote(name, safe="@_") for name in normalized)
        return f"{self.base_url}/stream?streams={joined}"

    @staticmethod
    def subscription_message(stream_names: tuple[str, ...], *, request_id: int) -> dict:
        if not stream_names:
            raise ValueError("Binance subscription requires at least one stream")
        if request_id < 0:
            raise ValueError("Binance request_id cannot be negative")
        return {
            "method": "SUBSCRIBE",
            "params": [_stream_name(name) for name in stream_names],
            "id": request_id,
        }

    @staticmethod
    def unsubscription_message(stream_names: tuple[str, ...], *, request_id: int) -> dict:
        if not stream_names:
            raise ValueError("Binance unsubscription requires at least one stream")
        if request_id < 0:
            raise ValueError("Binance request_id cannot be negative")
        return {
            "method": "UNSUBSCRIBE",
            "params": [_stream_name(name) for name in stream_names],
            "id": request_id,
        }


def _stream_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Binance stream name cannot be empty")
    if "/" in normalized or "?" in normalized or "#" in normalized:
        raise ValueError("Binance stream name contains unsafe URL delimiters")
    return normalized
