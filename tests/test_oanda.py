from datetime import UTC, datetime
from decimal import Decimal

from aura.data.oanda import OandaCredentials, OandaMarketDataClient


class _Client(OandaMarketDataClient):
    def __init__(self, payloads: list[dict]) -> None:
        super().__init__(OandaCredentials(account_id="demo", access_token="token"))
        self.payloads = payloads

    def _get(self, path: str, params: dict[str, str]) -> dict:
        return self.payloads.pop(0)


def test_oanda_pricing_normalizes_bid_ask_midpoint() -> None:
    now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    client = _Client(
        [
            {
                "prices": [
                    {
                        "instrument": "EUR_USD",
                        "status": "tradeable",
                        "time": "2026-08-18T05:00:00.123456789Z",
                        "bids": [{"price": "1.1000"}],
                        "asks": [{"price": "1.1002"}],
                    }
                ]
            }
        ]
    )
    quotes = client.pricing(["EUR_USD"], observed_at=now)
    assert len(quotes) == 1
    assert quotes[0].last == Decimal("1.1001")
    assert quotes[0].provider == "OANDA_PRACTICE"


def test_oanda_candles_keep_only_complete_visible_bars() -> None:
    as_of = datetime(2026, 8, 18, 5, 2, 30, tzinfo=UTC)
    client = _Client(
        [
            {
                "candles": [
                    {
                        "complete": True,
                        "time": "2026-08-18T05:00:00.000000000Z",
                        "volume": 10,
                        "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15"},
                    },
                    {
                        "complete": False,
                        "time": "2026-08-18T05:02:00.000000000Z",
                        "volume": 4,
                        "mid": {"o": "1.15", "h": "1.16", "l": "1.14", "c": "1.15"},
                    },
                ]
            }
        ]
    )
    candles = client.candles("EUR_USD", granularity="M1", as_of=as_of)
    assert len(candles) == 1
    assert candles[0].close == Decimal("1.15")
    assert candles[0].venue == "OANDA_PRACTICE"
