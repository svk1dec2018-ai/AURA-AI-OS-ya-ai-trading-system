from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    DAY = "DAY"


class SignalIntent(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class NormalizedCandle(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    venue: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal(0)
    closed: bool = True

    @field_validator("open_time", "close_time")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_ohlc(self) -> NormalizedCandle:
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is inconsistent with OHLC")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is inconsistent with OHLC")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")
        return self


class StrategySignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    symbol: str
    intent: SignalIntent
    confidence: float = Field(ge=0.0, le=1.0)
    reference_price: Decimal
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""
    exit_position: bool = False

    @model_validator(mode="after")
    def validate_exit_semantics(self) -> StrategySignal:
        if self.reference_price <= 0:
            raise ValueError("strategy signal reference_price must be positive")
        if self.exit_position and self.intent != SignalIntent.FLAT:
            raise ValueError("explicit position exit requires FLAT intent")
        return self


class OrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str = Field(default_factory=lambda: str(uuid4()))
    client_order_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    venue: str
    side: Side
    quantity: Decimal = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_prices(self) -> OrderRequest:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit order requires limit_price")
        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("stop order requires stop_price")
        return self


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    fill_id: str
    order_id: str
    symbol: str
    side: Side
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(default=Decimal(0), ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    reason: str
    requested_quantity: Decimal
    approved_quantity: Decimal = Decimal(0)


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    cash: Decimal
    equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    peak_equity: Decimal
    drawdown_pct: Decimal
    position_values: dict[str, Decimal] = Field(default_factory=dict)
