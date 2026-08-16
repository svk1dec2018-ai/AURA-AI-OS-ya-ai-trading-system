from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    INDEX = "INDEX"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"
    COMMODITY = "COMMODITY"


class OptionRight(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(slots=True, frozen=True)
class Instrument:
    """Broker-neutral instrument identity used throughout AURA."""

    instrument_id: str
    asset_class: AssetClass
    base: str
    quote: str
    expiry: date | None = None
    strike: Decimal | None = None
    option_right: OptionRight | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id is required")
        if not self.base.strip() or not self.quote.strip():
            raise ValueError("base and quote are required")
        if self.asset_class == AssetClass.OPTION:
            if self.expiry is None or self.strike is None or self.option_right is None:
                raise ValueError("options require expiry, strike and option_right")
            if self.strike <= 0:
                raise ValueError("option strike must be positive")
        elif self.strike is not None or self.option_right is not None:
            raise ValueError("strike/option_right are valid only for options")


@dataclass(slots=True, frozen=True)
class VenueSymbol:
    instrument_id: str
    venue: str
    symbol: str

    def __post_init__(self) -> None:
        if not self.instrument_id.strip() or not self.venue.strip() or not self.symbol.strip():
            raise ValueError("instrument_id, venue and symbol are required")


class SymbolMappingError(KeyError):
    pass


class SymbolMapper:
    """Bidirectional registry between canonical AURA IDs and venue symbols."""

    def __init__(self) -> None:
        self._to_venue: dict[tuple[str, str], str] = {}
        self._to_canonical: dict[tuple[str, str], str] = {}

    @staticmethod
    def _venue_key(venue: str) -> str:
        return venue.strip().upper()

    @staticmethod
    def _symbol_key(symbol: str) -> str:
        return symbol.strip().upper()

    @staticmethod
    def _instrument_key(instrument_id: str) -> str:
        return instrument_id.strip().upper()

    def register(self, mapping: VenueSymbol) -> None:
        venue = self._venue_key(mapping.venue)
        symbol = self._symbol_key(mapping.symbol)
        instrument_id = self._instrument_key(mapping.instrument_id)
        forward_key = (instrument_id, venue)
        reverse_key = (venue, symbol)

        existing_symbol = self._to_venue.get(forward_key)
        if existing_symbol is not None and existing_symbol != symbol:
            raise ValueError(
                f"mapping conflict for {instrument_id} on {venue}: {existing_symbol} != {symbol}"
            )
        existing_instrument = self._to_canonical.get(reverse_key)
        if existing_instrument is not None and existing_instrument != instrument_id:
            raise ValueError(
                f"venue symbol collision for {venue}:{symbol}: {existing_instrument}"
            )

        self._to_venue[forward_key] = symbol
        self._to_canonical[reverse_key] = instrument_id

    def to_venue(self, instrument_id: str, venue: str) -> str:
        key = (self._instrument_key(instrument_id), self._venue_key(venue))
        try:
            return self._to_venue[key]
        except KeyError as exc:
            raise SymbolMappingError(f"no venue mapping for {key[0]} on {key[1]}") from exc

    def to_canonical(self, venue: str, symbol: str) -> str:
        key = (self._venue_key(venue), self._symbol_key(symbol))
        try:
            return self._to_canonical[key]
        except KeyError as exc:
            raise SymbolMappingError(f"unknown venue symbol {key[0]}:{key[1]}") from exc
