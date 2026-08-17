from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from aura.markets.universe import AssetClass, CanonicalInstrument


@dataclass(slots=True, frozen=True)
class DhanUniversePolicy:
    max_stream_instruments: int = 5000
    max_primary_cash_symbols: int = 3500
    max_primary_futures: int = 1200
    max_option_contracts_per_underlying: int = 40
    max_option_expiries_per_underlying: int = 2
    strikes_each_side: int = 10

    def __post_init__(self) -> None:
        if self.max_stream_instruments <= 0:
            raise ValueError("max_stream_instruments must be positive")
        if self.max_primary_cash_symbols < 0 or self.max_primary_futures < 0:
            raise ValueError("primary universe caps cannot be negative")
        if self.max_option_contracts_per_underlying <= 0:
            raise ValueError("option contract cap must be positive")
        if self.max_option_expiries_per_underlying <= 0 or self.strikes_each_side <= 0:
            raise ValueError("option expiry/strike windows must be positive")


@dataclass(slots=True, frozen=True)
class DhanPrimaryUniversePlan:
    streamed: tuple[CanonicalInstrument, ...]
    indexed_options: tuple[CanonicalInstrument, ...]
    deferred: tuple[CanonicalInstrument, ...]


class DhanUniversePlanner:
    """Plan an A-to-Z Indian universe under broker streaming limits.

    The complete cash/F&O/MCX master remains indexed. Broad primary scanning uses
    cash, futures and liquid underlyings, while options are activated dynamically
    around an underlying opportunity instead of wasting the connection budget on
    thousands of far-OTM strikes. This is universe staging, not a manual watchlist.
    """

    def __init__(self, policy: DhanUniversePolicy | None = None) -> None:
        self.policy = policy or DhanUniversePolicy()

    def primary_plan(
        self,
        instruments: tuple[CanonicalInstrument, ...],
        *,
        as_of: datetime | None = None,
    ) -> DhanPrimaryUniversePlan:
        decision_time = as_of or datetime.now(UTC)
        cash = [
            item
            for item in instruments
            if item.asset_class in {AssetClass.CASH_EQUITY, AssetClass.ETF}
            and item.tradable
            and item.market_data_enabled
        ]
        futures = [
            item
            for item in instruments
            if item.asset_class == AssetClass.FUTURE
            and item.tradable
            and item.market_data_enabled
            and (item.expiry is None or item.expiry >= decision_time)
        ]
        options = [
            item
            for item in instruments
            if item.asset_class == AssetClass.OPTION
            and item.tradable
            and item.market_data_enabled
            and (item.expiry is None or item.expiry >= decision_time)
        ]

        cash.sort(key=lambda item: (item.exchange or "", item.canonical_symbol))
        futures.sort(
            key=lambda item: (
                item.expiry.isoformat() if item.expiry else "",
                item.underlying or item.canonical_symbol,
            )
        )
        options.sort(
            key=lambda item: (
                item.underlying or "",
                item.expiry.isoformat() if item.expiry else "",
                item.strike or Decimal(0),
            )
        )

        selected: list[CanonicalInstrument] = []
        selected.extend(cash[: self.policy.max_primary_cash_symbols])
        remaining = self.policy.max_stream_instruments - len(selected)
        if remaining > 0:
            selected.extend(
                futures[: min(self.policy.max_primary_futures, remaining)]
            )
        selected = selected[: self.policy.max_stream_instruments]
        selected_ids = {item.instrument_id for item in selected}
        deferred = tuple(
            item
            for item in (*cash, *futures)
            if item.instrument_id not in selected_ids
        )
        return DhanPrimaryUniversePlan(
            streamed=tuple(selected),
            indexed_options=tuple(options),
            deferred=deferred,
        )

    def option_window(
        self,
        indexed_options: tuple[CanonicalInstrument, ...],
        *,
        underlying: str,
        spot_price: Decimal,
        as_of: datetime,
    ) -> tuple[CanonicalInstrument, ...]:
        if spot_price <= 0:
            raise ValueError("spot_price must be positive")
        matching = [
            item
            for item in indexed_options
            if (item.underlying or "").upper() == underlying.upper()
            and item.expiry is not None
            and item.expiry >= as_of
            and item.strike is not None
        ]
        if not matching:
            return ()
        expiries = sorted({item.expiry for item in matching})[
            : self.policy.max_option_expiries_per_underlying
        ]
        selected: list[CanonicalInstrument] = []
        for expiry in expiries:
            chain = [item for item in matching if item.expiry == expiry]
            strikes = sorted({item.strike for item in chain if item.strike is not None})
            nearest_index = min(
                range(len(strikes)),
                key=lambda index: abs(strikes[index] - spot_price),
            )
            start = max(0, nearest_index - self.policy.strikes_each_side)
            stop = nearest_index + self.policy.strikes_each_side + 1
            strike_window = set(strikes[start:stop])
            selected.extend(item for item in chain if item.strike in strike_window)
        selected.sort(
            key=lambda item: (
                item.expiry.isoformat() if item.expiry else "",
                abs((item.strike or spot_price) - spot_price),
                item.strike or Decimal(0),
                item.option_type.value if item.option_type else "",
            )
        )
        return tuple(selected[: self.policy.max_option_contracts_per_underlying])
