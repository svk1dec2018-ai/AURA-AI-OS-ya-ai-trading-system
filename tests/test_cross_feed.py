from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.data.cross_feed import CrossFeedPolicy, CrossFeedQuoteGuard, QuoteObservation


def _quote(provider: str, price: str, now: datetime) -> QuoteObservation:
    value = Decimal(price)
    return QuoteObservation(
        provider=provider,
        symbol="NIFTY",
        last=value,
        bid=value - Decimal(1),
        ask=value + Decimal(1),
        observed_at=now,
        received_at=now,
    )


def test_cross_feed_rejects_large_outlier_and_keeps_consensus() -> None:
    now = datetime(2026, 8, 18, 4, 30, tzinfo=UTC)
    guard = CrossFeedQuoteGuard(
        CrossFeedPolicy(
            max_age=timedelta(seconds=5),
            max_provider_divergence_bps=Decimal(20),
            min_providers_for_consensus=2,
        )
    )
    decision = guard.evaluate(
        [
            _quote("SHOONYA", "25000", now),
            _quote("UPSTOX", "25002", now),
            _quote("BAD_FEED", "25500", now),
        ],
        as_of=now,
    )
    assert decision.safe
    assert set(decision.accepted_providers) == {"SHOONYA", "UPSTOX"}
    assert "BAD_FEED" in decision.rejected_providers
    assert decision.consensus_price in {Decimal(25000), Decimal(25002)}


def test_cross_feed_fails_closed_when_only_one_fresh_provider() -> None:
    now = datetime(2026, 8, 18, 4, 30, tzinfo=UTC)
    guard = CrossFeedQuoteGuard()
    stale = _quote("STALE", "25000", now - timedelta(seconds=10))
    fresh = _quote("FRESH", "25001", now)
    decision = guard.evaluate([stale, fresh], as_of=now)
    assert not decision.safe
    assert decision.accepted_providers == ("FRESH",)
