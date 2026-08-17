from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VenueFamily(str, Enum):
    EXNESS_MT5 = "exness_mt5"
    DHAN_INDIA = "dhan_india"
    BINANCE = "binance"
    KRAKEN = "kraken"
    OTHER = "other"


class AssetClass(str, Enum):
    CASH_EQUITY = "cash_equity"
    ETF = "etf"
    INDEX = "index"
    FUTURE = "future"
    OPTION = "option"
    FOREX = "forex"
    METAL = "metal"
    ENERGY = "energy"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    STOCK_CFD = "stock_cfd"
    INDEX_CFD = "index_cfd"
    CRYPTO_CFD = "crypto_cfd"
    OTHER_CFD = "other_cfd"


class OptionType(str, Enum):
    CALL = "CE"
    PUT = "PE"


class CanonicalInstrument(BaseModel):
    """Broker-neutral instrument identity used by AURA's universal scanner."""

    model_config = ConfigDict(frozen=True)

    instrument_id: str = Field(min_length=1)
    canonical_symbol: str = Field(min_length=1)
    venue_family: VenueFamily
    venue_symbol: str = Field(min_length=1)
    asset_class: AssetClass
    exchange: str | None = None
    segment: str | None = None
    currency: str | None = None
    underlying: str | None = None
    expiry: datetime | None = None
    strike: Decimal | None = None
    option_type: OptionType | None = None
    contract_size: Decimal = Field(default=Decimal(1), gt=0)
    lot_size: Decimal = Field(default=Decimal(1), gt=0)
    tick_size: Decimal = Field(gt=0)
    min_quantity: Decimal = Field(gt=0)
    quantity_step: Decimal = Field(gt=0)
    max_quantity: Decimal | None = Field(default=None, gt=0)
    tradable: bool = True
    market_data_enabled: bool = True

    @field_validator("expiry")
    @classmethod
    def expiry_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("instrument expiry must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_derivative_identity(self) -> CanonicalInstrument:
        if self.asset_class == AssetClass.OPTION:
            missing = [
                name
                for name, value in (
                    ("underlying", self.underlying),
                    ("expiry", self.expiry),
                    ("strike", self.strike),
                    ("option_type", self.option_type),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"option instrument missing fields: {', '.join(missing)}")
        if self.asset_class == AssetClass.FUTURE and (
            self.underlying is None or self.expiry is None
        ):
            raise ValueError("future instrument requires underlying and expiry")
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("max_quantity cannot be below min_quantity")
        return self


@dataclass(slots=True, frozen=True)
class UniverseEligibilityPolicy:
    supported_timeframes: tuple[str, ...] = (
        "1m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d",
    )
    require_tradable: bool = True
    require_market_data: bool = True

    def __post_init__(self) -> None:
        if not self.supported_timeframes:
            raise ValueError("universe must support at least one timeframe")
        if len(self.supported_timeframes) != len(set(self.supported_timeframes)):
            raise ValueError("supported_timeframes must be unique")


class UniversalMarketUniverse:
    """Canonical full-universe registry across all enabled AURA connectors.

    Connectors discover symbols dynamically and register them here. The scanner
    receives all eligible instruments rather than a permanently hard-coded
    watchlist. Venue-specific access remains explicit so Exness CFDs are never
    confused with Indian exchange-traded futures/options.
    """

    def __init__(self, policy: UniverseEligibilityPolicy | None = None) -> None:
        self.policy = policy or UniverseEligibilityPolicy()
        self._instruments: dict[str, CanonicalInstrument] = {}

    def upsert(self, instrument: CanonicalInstrument) -> None:
        existing = self._instruments.get(instrument.instrument_id)
        if existing is not None and existing.venue_family != instrument.venue_family:
            raise ValueError(
                f"instrument_id collision across venues: {instrument.instrument_id}"
            )
        self._instruments[instrument.instrument_id] = instrument

    def all(self) -> tuple[CanonicalInstrument, ...]:
        return tuple(self._instruments[key] for key in sorted(self._instruments))

    def eligible(
        self,
        *,
        venue_family: VenueFamily | None = None,
        asset_classes: frozenset[AssetClass] | None = None,
    ) -> tuple[CanonicalInstrument, ...]:
        selected: list[CanonicalInstrument] = []
        for instrument in self._instruments.values():
            if venue_family is not None and instrument.venue_family != venue_family:
                continue
            if asset_classes is not None and instrument.asset_class not in asset_classes:
                continue
            if self.policy.require_tradable and not instrument.tradable:
                continue
            if self.policy.require_market_data and not instrument.market_data_enabled:
                continue
            selected.append(instrument)
        selected.sort(
            key=lambda item: (
                item.venue_family.value,
                item.asset_class.value,
                item.canonical_symbol,
                item.expiry.isoformat() if item.expiry is not None else "",
                item.strike or Decimal(0),
                item.option_type.value if item.option_type is not None else "",
            )
        )
        return tuple(selected)

    def scan_plan(self) -> tuple[tuple[CanonicalInstrument, str], ...]:
        return tuple(
            (instrument, timeframe)
            for instrument in self.eligible()
            for timeframe in self.policy.supported_timeframes
        )
