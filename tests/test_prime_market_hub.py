from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.data.cross_feed import QuoteObservation
from aura.prime.market_hub import PrimePublicQuoteHub, PublicQuoteRoute


def test_public_quote_hub_is_truthful_about_missing_and_fresh_quotes() -> None:
    hub = PrimePublicQuoteHub(
        (
            PublicQuoteRoute("TEST", "BTC-USD", "BTCUSD", "CRYPTO_SPOT"),
            PublicQuoteRoute("TEST", "ETH-USD", "ETHUSD", "CRYPTO_SPOT"),
        ),
        stale_after=timedelta(seconds=10),
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

    empty = hub.snapshot(now=now)
    assert empty["available_count"] == 0
    assert empty["fresh_count"] == 0
    assert all(item["available"] is False for item in empty["items"])

    hub.ingest(
        QuoteObservation(
            provider="TEST",
            symbol="BTC-USD",
            last=Decimal(65000),
            bid=Decimal(64999),
            ask=Decimal(65001),
            observed_at=now - timedelta(seconds=2),
            received_at=now - timedelta(seconds=1),
            trust_score=1.0,
        )
    )
    snapshot = hub.snapshot(now=now)
    btc = next(item for item in snapshot["items"] if item["symbol"] == "BTCUSD")
    eth = next(item for item in snapshot["items"] if item["symbol"] == "ETHUSD")
    assert btc["available"] is True
    assert btc["stale"] is False
    assert btc["last"] == 65000.0
    assert btc["execution_authority"] is False
    assert eth["available"] is False
    assert snapshot["available_count"] == 1
    assert snapshot["fresh_count"] == 1


def test_public_quote_hub_drops_out_of_order_updates() -> None:
    hub = PrimePublicQuoteHub(
        (PublicQuoteRoute("TEST", "BTC-USD", "BTCUSD", "CRYPTO_SPOT"),)
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
    newer = QuoteObservation(
        provider="TEST",
        symbol="BTC-USD",
        last=Decimal(65000),
        observed_at=now,
        received_at=now,
    )
    older = QuoteObservation(
        provider="TEST",
        symbol="BTC-USD",
        last=Decimal(64000),
        observed_at=now - timedelta(seconds=5),
        received_at=now,
    )
    hub.ingest(newer)
    hub.ingest(older)
    snapshot = hub.snapshot(now=now)
    assert snapshot["items"][0]["last"] == 65000.0


def test_public_quote_hub_marks_stale_without_faking_replacement() -> None:
    hub = PrimePublicQuoteHub(
        (PublicQuoteRoute("TEST", "BTC-USD", "BTCUSD", "CRYPTO_SPOT"),),
        stale_after=timedelta(seconds=5),
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
    hub.ingest(
        QuoteObservation(
            provider="TEST",
            symbol="BTC-USD",
            last=Decimal(65000),
            observed_at=now - timedelta(seconds=10),
            received_at=now - timedelta(seconds=9),
        )
    )
    snapshot = hub.snapshot(now=now)
    item = snapshot["items"][0]
    assert item["available"] is True
    assert item["stale"] is True
    assert item["last"] == 65000.0
    assert snapshot["fresh_count"] == 0
