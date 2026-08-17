from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from enum import Enum
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from aura.markets.universe import (
    AssetClass,
    CanonicalInstrument,
    OptionType,
    VenueFamily,
)

DHAN_DETAILED_SCRIP_MASTER_URL = (
    "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
)


class DhanInstrumentMasterError(RuntimeError):
    pass


class DhanExchangeSegment(str, Enum):
    NSE_EQ = "NSE_EQ"
    NSE_FNO = "NSE_FNO"
    BSE_EQ = "BSE_EQ"
    BSE_FNO = "BSE_FNO"
    MCX_COMM = "MCX_COMM"


@dataclass(slots=True, frozen=True)
class DhanInstrumentRecord:
    exchange_segment: str
    security_id: str
    trading_symbol: str
    custom_symbol: str
    instrument_name: str
    series: str
    expiry_date: str
    strike_price: str
    option_type: str
    lot_units: str
    tick_size: str
    symbol_name: str


class DhanInstrumentMaster:
    """Parse Dhan's detailed scrip master into AURA canonical instruments.

    Column lookup is alias-based because Dhan has historically exposed both
    compact and detailed labels. Unsupported segments are ignored rather than
    silently mislabeled. F&O quantities are represented in exchange units, so
    `lot_size`/`min_quantity` carry the lot while contract multiplier remains 1.
    """

    def __init__(self, records: tuple[DhanInstrumentRecord, ...]) -> None:
        self.records = records

    @classmethod
    def from_csv_text(cls, text: str) -> DhanInstrumentMaster:
        if not text.strip():
            raise DhanInstrumentMasterError("Dhan instrument master is empty")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise DhanInstrumentMasterError("Dhan instrument master has no header")
        records: list[DhanInstrumentRecord] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                record = DhanInstrumentRecord(
                    exchange_segment=_pick(
                        row,
                        "SEM_SEGMENT",
                        "EXCH_ID",
                        "EXCHANGE_SEGMENT",
                        "SEGMENT",
                    ),
                    security_id=_pick(
                        row,
                        "SEM_SMST_SECURITY_ID",
                        "SECURITY_ID",
                        "SECURITY_ID_V2",
                    ),
                    trading_symbol=_pick(
                        row,
                        "SEM_TRADING_SYMBOL",
                        "TRADING_SYMBOL",
                        required=False,
                    ),
                    custom_symbol=_pick(
                        row,
                        "SEM_CUSTOM_SYMBOL",
                        "CUSTOM_SYMBOL",
                        required=False,
                    ),
                    instrument_name=_pick(
                        row,
                        "SEM_INSTRUMENT_NAME",
                        "INSTRUMENT",
                        "INSTRUMENT_NAME",
                        required=False,
                    ),
                    series=_pick(
                        row,
                        "SEM_SERIES",
                        "SERIES",
                        required=False,
                    ),
                    expiry_date=_pick(
                        row,
                        "SEM_EXPIRY_DATE",
                        "EXPIRY_DATE",
                        required=False,
                    ),
                    strike_price=_pick(
                        row,
                        "SEM_STRIKE_PRICE",
                        "STRIKE_PRICE",
                        required=False,
                    ),
                    option_type=_pick(
                        row,
                        "SEM_OPTION_TYPE",
                        "OPTION_TYPE",
                        required=False,
                    ),
                    lot_units=_pick(
                        row,
                        "SEM_LOT_UNITS",
                        "LOT_SIZE",
                        "LOT_UNITS",
                        required=False,
                    ),
                    tick_size=_pick(
                        row,
                        "SEM_TICK_SIZE",
                        "TICK_SIZE",
                        required=False,
                    ),
                    symbol_name=_pick(
                        row,
                        "SM_SYMBOL_NAME",
                        "SYMBOL_NAME",
                        "UNDERLYING_SYMBOL",
                        required=False,
                    ),
                )
            except (KeyError, ValueError) as exc:
                raise DhanInstrumentMasterError(
                    f"invalid Dhan instrument row {row_number}: {exc}"
                ) from exc
            if record.exchange_segment and record.security_id:
                records.append(record)
        return cls(tuple(records))

    def to_canonical_universe(
        self,
        *,
        include_segments: frozenset[DhanExchangeSegment] | None = None,
    ) -> tuple[CanonicalInstrument, ...]:
        allowed = include_segments or frozenset(DhanExchangeSegment)
        instruments: list[CanonicalInstrument] = []
        for record in self.records:
            try:
                segment = DhanExchangeSegment(record.exchange_segment)
            except ValueError:
                continue
            if segment not in allowed:
                continue
            instrument = _canonicalize(record, segment)
            if instrument is not None:
                instruments.append(instrument)
        instruments.sort(
            key=lambda item: (
                item.exchange or "",
                item.asset_class.value,
                item.canonical_symbol,
                item.expiry.isoformat() if item.expiry else "",
                item.strike or Decimal(0),
                item.option_type.value if item.option_type else "",
            )
        )
        return tuple(instruments)


class DhanInstrumentMasterDownloader:
    def __init__(
        self,
        url: str = DHAN_DETAILED_SCRIP_MASTER_URL,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not url.startswith("https://"):
            raise ValueError("Dhan instrument master URL must use HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.url = url
        self.timeout_seconds = timeout_seconds

    def download(self) -> DhanInstrumentMaster:
        request = Request(
            self.url,
            headers={"User-Agent": "AURA-AI-OS/0.1 instrument-master"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                text = response.read().decode("utf-8-sig")
        except HTTPError as exc:
            raise DhanInstrumentMasterError(
                f"Dhan instrument master HTTP {exc.code}"
            ) from exc
        except URLError as exc:
            raise DhanInstrumentMasterError(
                f"Dhan instrument master network error: {exc.reason}"
            ) from exc
        return DhanInstrumentMaster.from_csv_text(text)


def _canonicalize(
    record: DhanInstrumentRecord,
    segment: DhanExchangeSegment,
) -> CanonicalInstrument | None:
    symbol = record.trading_symbol or record.custom_symbol or record.symbol_name
    if not symbol:
        return None
    tick_size = _decimal(record.tick_size, default=Decimal("0.05"))
    if tick_size <= 0:
        tick_size = Decimal("0.05")
    lot_size = _decimal(record.lot_units, default=Decimal(1))
    if lot_size <= 0:
        lot_size = Decimal(1)

    instrument_text = f"{record.instrument_name} {record.series} {record.option_type}".upper()
    exchange = "MCX" if segment == DhanExchangeSegment.MCX_COMM else segment.value.split("_")[0]

    if segment in {DhanExchangeSegment.NSE_EQ, DhanExchangeSegment.BSE_EQ}:
        asset_class = (
            AssetClass.ETF
            if "ETF" in instrument_text or record.series.upper() == "ETF"
            else AssetClass.CASH_EQUITY
        )
        return CanonicalInstrument(
            instrument_id=f"dhan:{segment.value}:{record.security_id}",
            canonical_symbol=symbol,
            venue_family=VenueFamily.DHAN_INDIA,
            venue_symbol=record.security_id,
            asset_class=asset_class,
            exchange=exchange,
            segment=segment.value,
            currency="INR",
            contract_size=Decimal(1),
            lot_size=Decimal(1),
            tick_size=tick_size,
            min_quantity=Decimal(1),
            quantity_step=Decimal(1),
        )

    is_option = (
        record.option_type.upper() in {"CE", "PE", "CALL", "PUT"}
        or "OPT" in instrument_text
    )
    is_future = "FUT" in instrument_text or not is_option
    underlying = record.symbol_name or _infer_underlying(record.custom_symbol or symbol)
    expiry = _parse_expiry(record.expiry_date)
    if expiry is None:
        return None

    if is_option:
        option_type = _option_type(record.option_type, record.custom_symbol or symbol)
        strike = _decimal(record.strike_price, default=Decimal(0))
        if option_type is None or strike <= 0 or not underlying:
            return None
        canonical_symbol = (
            f"{underlying}-{expiry.date().isoformat()}-{strike.normalize()}-"
            f"{option_type.value}"
        )
        return CanonicalInstrument(
            instrument_id=f"dhan:{segment.value}:{record.security_id}",
            canonical_symbol=canonical_symbol,
            venue_family=VenueFamily.DHAN_INDIA,
            venue_symbol=record.security_id,
            asset_class=AssetClass.OPTION,
            exchange=exchange,
            segment=segment.value,
            currency="INR",
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            contract_size=Decimal(1),
            lot_size=lot_size,
            tick_size=tick_size,
            min_quantity=lot_size,
            quantity_step=lot_size,
        )

    if is_future and underlying:
        return CanonicalInstrument(
            instrument_id=f"dhan:{segment.value}:{record.security_id}",
            canonical_symbol=f"{underlying}-{expiry.date().isoformat()}-FUT",
            venue_family=VenueFamily.DHAN_INDIA,
            venue_symbol=record.security_id,
            asset_class=AssetClass.FUTURE,
            exchange=exchange,
            segment=segment.value,
            currency="INR",
            underlying=underlying,
            expiry=expiry,
            contract_size=Decimal(1),
            lot_size=lot_size,
            tick_size=tick_size,
            min_quantity=lot_size,
            quantity_step=lot_size,
        )
    return None


def _pick(
    row: dict[str, str | None],
    *names: str,
    required: bool = True,
) -> str:
    normalized = {str(key).strip().upper(): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name.upper())
        if value is not None and str(value).strip():
            return str(value).strip()
    if required:
        raise KeyError(f"missing any of columns: {', '.join(names)}")
    return ""


def _decimal(value: str, *, default: Decimal) -> Decimal:
    if not value:
        return default
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        return default


def _parse_expiry(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip().split(" ")[0]
    formats = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d")
    parsed = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    return datetime.combine(parsed, time.min, tzinfo=ZoneInfo("Asia/Kolkata"))


def _option_type(value: str, symbol: str) -> OptionType | None:
    text = f"{value} {symbol}".upper()
    if " CE" in f" {text}" or "CALL" in text or text.endswith("CE"):
        return OptionType.CALL
    if " PE" in f" {text}" or "PUT" in text or text.endswith("PE"):
        return OptionType.PUT
    return None


def _infer_underlying(symbol: str) -> str:
    text = symbol.strip().upper()
    for token in (" FUT", " CE", " PE", "-FUT", "-CE", "-PE"):
        if token in text:
            text = text.split(token, 1)[0]
    return text.split()[0] if text else ""
