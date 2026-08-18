from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuoteObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    last: Decimal = Field(gt=0)
    bid: Decimal | None = Field(default=None, gt=0)
    ask: Decimal | None = Field(default=None, gt=0)
    observed_at: datetime
    received_at: datetime
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("observed_at", "received_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quote timestamps must be timezone-aware")
        return value


@dataclass(slots=True, frozen=True)
class CrossFeedPolicy:
    max_age: timedelta = timedelta(seconds=5)
    max_provider_divergence_bps: Decimal = Decimal(35)
    max_spread_bps: Decimal = Decimal(100)
    min_trust_score: float = 0.5
    min_providers_for_consensus: int = 2

    def __post_init__(self) -> None:
        if self.max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        if self.max_provider_divergence_bps <= 0 or self.max_spread_bps <= 0:
            raise ValueError("cross-feed bps limits must be positive")
        if not 0 <= self.min_trust_score <= 1:
            raise ValueError("min_trust_score must be between 0 and 1")
        if self.min_providers_for_consensus < 1:
            raise ValueError("min_providers_for_consensus must be positive")


class CrossFeedDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    safe: bool
    symbol: str
    consensus_price: Decimal | None
    accepted_providers: tuple[str, ...]
    rejected_providers: tuple[str, ...]
    reasons: tuple[str, ...]
    max_divergence_bps: Decimal = Decimal(0)


class CrossFeedQuoteGuard:
    """Robust median consensus so one broker/feed cannot silently poison AURA."""

    def __init__(self, policy: CrossFeedPolicy | None = None) -> None:
        self.policy = policy or CrossFeedPolicy()

    def evaluate(
        self,
        observations: tuple[QuoteObservation, ...] | list[QuoteObservation],
        *,
        as_of: datetime,
    ) -> CrossFeedDecision:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not observations:
            return CrossFeedDecision(
                safe=False,
                symbol="UNKNOWN",
                consensus_price=None,
                accepted_providers=(),
                rejected_providers=(),
                reasons=("no quote observations",),
            )
        symbols = {item.symbol for item in observations}
        if len(symbols) != 1:
            raise ValueError("cross-feed comparison requires one canonical symbol")
        symbol = next(iter(symbols))
        valid: list[QuoteObservation] = []
        rejected: list[str] = []
        reasons: list[str] = []
        for item in observations:
            if item.observed_at > as_of or item.received_at > as_of:
                rejected.append(item.provider)
                reasons.append(f"{item.provider}:future_quote")
                continue
            if as_of - item.observed_at > self.policy.max_age:
                rejected.append(item.provider)
                reasons.append(f"{item.provider}:stale_quote")
                continue
            if item.trust_score < self.policy.min_trust_score:
                rejected.append(item.provider)
                reasons.append(f"{item.provider}:low_trust")
                continue
            if item.bid is not None and item.ask is not None:
                if item.ask < item.bid:
                    rejected.append(item.provider)
                    reasons.append(f"{item.provider}:crossed_book")
                    continue
                midpoint = (item.bid + item.ask) / Decimal(2)
                spread_bps = (item.ask - item.bid) / midpoint * Decimal(10000)
                if spread_bps > self.policy.max_spread_bps:
                    rejected.append(item.provider)
                    reasons.append(f"{item.provider}:spread_too_wide")
                    continue
            valid.append(item)
        if not valid:
            return CrossFeedDecision(
                safe=False,
                symbol=symbol,
                consensus_price=None,
                accepted_providers=(),
                rejected_providers=tuple(sorted(set(rejected))),
                reasons=tuple(reasons or ("no valid providers",)),
            )

        median = _median([item.last for item in valid])
        accepted: list[QuoteObservation] = []
        max_divergence = Decimal(0)
        for item in valid:
            divergence = abs(item.last - median) / median * Decimal(10000)
            max_divergence = max(max_divergence, divergence)
            if divergence > self.policy.max_provider_divergence_bps:
                rejected.append(item.provider)
                reasons.append(f"{item.provider}:price_outlier_{divergence:.4f}bps")
                continue
            accepted.append(item)
        if accepted:
            consensus = _weighted_median_price(accepted)
        else:
            consensus = None
        safe = len(accepted) >= self.policy.min_providers_for_consensus
        if not safe:
            reasons.append(
                f"consensus providers {len(accepted)} < {self.policy.min_providers_for_consensus}"
            )
        return CrossFeedDecision(
            safe=safe,
            symbol=symbol,
            consensus_price=consensus,
            accepted_providers=tuple(sorted(item.provider for item in accepted)),
            rejected_providers=tuple(sorted(set(rejected))),
            reasons=tuple(reasons),
            max_divergence_bps=max_divergence,
        )


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _weighted_median_price(observations: list[QuoteObservation]) -> Decimal:
    ordered = sorted(observations, key=lambda item: item.last)
    total = sum(item.trust_score for item in ordered)
    if total <= 0:
        return _median([item.last for item in ordered])
    threshold = total / 2.0
    running = 0.0
    for item in ordered:
        running += item.trust_score
        if running >= threshold:
            return item.last
    return ordered[-1].last
