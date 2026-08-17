from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from aura.markets.universe import AssetClass, CanonicalInstrument, VenueFamily


class MT5SymbolMetadata(BaseModel):
    """AURA-normalized subset of MetaTrader 5 symbol_info/symbols_get metadata."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    path: str = ""
    currency_base: str = ""
    currency_profit: str = ""
    description: str = ""
    trade_contract_size: Decimal = Field(default=Decimal(1), gt=0)
    point: Decimal = Field(gt=0)
    volume_min: Decimal = Field(gt=0)
    volume_step: Decimal = Field(gt=0)
    volume_max: Decimal | None = Field(default=None, gt=0)
    trade_mode: int = 0
    visible: bool = True


@dataclass(slots=True, frozen=True)
class MT5AccountState:
    login: int
    server: str
    currency: str
    balance: Decimal
    equity: Decimal
    margin: Decimal
    margin_free: Decimal
    margin_level: Decimal | None


@runtime_checkable
class MT5TerminalGateway(Protocol):
    """Dependency boundary around the official MetaTrader5 Python package.

    A production implementation can wrap `MetaTrader5` on the terminal host.
    Tests and Linux CI use fakes without importing the platform-specific package.
    """

    def initialize(self) -> bool: ...

    def shutdown(self) -> None: ...

    def symbols_get(self) -> tuple[Any, ...] | None: ...

    def symbol_info(self, symbol: str) -> Any | None: ...

    def symbol_info_tick(self, symbol: str) -> Any | None: ...

    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: int,
        start_pos: int,
        count: int,
    ) -> Any: ...

    def orders_get(self, **kwargs: Any) -> tuple[Any, ...] | None: ...

    def positions_get(self, **kwargs: Any) -> tuple[Any, ...] | None: ...

    def account_info(self) -> Any | None: ...

    def order_check(self, request: dict[str, Any]) -> Any: ...

    def order_send(self, request: dict[str, Any]) -> Any: ...

    def last_error(self) -> Any: ...


class MT5UniverseDiscovery:
    """Discover the full MT5 account symbol universe and normalize it for AURA."""

    def __init__(self, gateway: MT5TerminalGateway) -> None:
        self.gateway = gateway

    def discover(self) -> tuple[CanonicalInstrument, ...]:
        symbols = self.gateway.symbols_get()
        if symbols is None:
            raise RuntimeError(f"MT5 symbols_get failed: {self.gateway.last_error()}")

        instruments: list[CanonicalInstrument] = []
        for raw in symbols:
            metadata = self._metadata(raw)
            asset_class = classify_mt5_asset(metadata)
            instruments.append(
                CanonicalInstrument(
                    instrument_id=f"exness-mt5:{metadata.name}",
                    canonical_symbol=metadata.name,
                    venue_family=VenueFamily.EXNESS_MT5,
                    venue_symbol=metadata.name,
                    asset_class=asset_class,
                    currency=metadata.currency_profit or None,
                    contract_size=metadata.trade_contract_size,
                    lot_size=Decimal(1),
                    tick_size=metadata.point,
                    min_quantity=metadata.volume_min,
                    quantity_step=metadata.volume_step,
                    max_quantity=metadata.volume_max,
                    tradable=metadata.trade_mode != 0,
                    market_data_enabled=True,
                )
            )
        instruments.sort(key=lambda item: item.venue_symbol)
        return tuple(instruments)

    @staticmethod
    def _metadata(raw: Any) -> MT5SymbolMetadata:
        source = raw._asdict() if hasattr(raw, "_asdict") else vars(raw)
        return MT5SymbolMetadata(
            name=str(source["name"]),
            path=str(source.get("path", "")),
            currency_base=str(source.get("currency_base", "")),
            currency_profit=str(source.get("currency_profit", "")),
            description=str(source.get("description", "")),
            trade_contract_size=Decimal(str(source.get("trade_contract_size", 1))),
            point=Decimal(str(source["point"])),
            volume_min=Decimal(str(source["volume_min"])),
            volume_step=Decimal(str(source["volume_step"])),
            volume_max=(
                Decimal(str(source["volume_max"]))
                if source.get("volume_max") not in (None, 0)
                else None
            ),
            trade_mode=int(source.get("trade_mode", 0)),
            visible=bool(source.get("visible", True)),
        )


def classify_mt5_asset(metadata: MT5SymbolMetadata) -> AssetClass:
    """Conservative category mapping from broker-provided MT5 path/description.

    Unknown groups remain OTHER_CFD rather than being silently misclassified.
    """

    text = f"{metadata.path} {metadata.description}".lower()
    if any(token in text for token in ("forex", "currency", "currencies")):
        return AssetClass.FOREX
    if any(token in text for token in ("metal", "gold", "silver", "xau", "xag")):
        return AssetClass.METAL
    if any(token in text for token in ("energy", "oil", "gas")):
        return AssetClass.ENERGY
    if any(token in text for token in ("crypto", "bitcoin", "ethereum")):
        return AssetClass.CRYPTO_CFD
    if any(token in text for token in ("index", "indices")):
        return AssetClass.INDEX_CFD
    if any(token in text for token in ("stock", "stocks", "equity", "shares")):
        return AssetClass.STOCK_CFD

    # Currency-base/profit metadata is a useful secondary clue for FX pairs, but
    # only use it when both currencies are populated; metals/CFDs often lack a
    # conventional base currency and therefore fall through safely.
    if metadata.currency_base and metadata.currency_profit:
        return AssetClass.FOREX
    return AssetClass.OTHER_CFD
