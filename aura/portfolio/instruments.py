from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AccountingMode(str, Enum):
    """How fills and marks affect cash/equity for an instrument."""

    SPOT = "spot"
    PREMIUM = "premium"
    DERIVATIVE = "derivative"


class InstrumentLedgerSpec(BaseModel):
    """Financial accounting metadata independent of a broker symbol format.

    SPOT: cash exchanges full notional; multiplier defaults to 1.
    PREMIUM: option-like premium accounting; cash exchanges premium * multiplier.
    DERIVATIVE: futures/CFD-style P&L accounting; full notional is exposure but is
    not debited/credited as principal when opening/closing the position.
    """

    model_config = ConfigDict(frozen=True)

    accounting: AccountingMode = AccountingMode.SPOT
    contract_multiplier: Decimal = Field(default=Decimal(1), gt=0)


DEFAULT_INSTRUMENT_SPEC = InstrumentLedgerSpec()
