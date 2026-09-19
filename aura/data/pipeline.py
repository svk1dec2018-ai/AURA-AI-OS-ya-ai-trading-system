from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aura.data.normalization import CandleNormalizationError, normalize_candle
from aura.data.quality import CandleQualityGate, DataQualityReport
from aura.domain.models import NormalizedCandle


class RawCandlePayload(BaseModel):
    """Provider-neutral candle primitives accepted at the ingestion boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    open_time: datetime
    close_time: datetime
    open_price: str | float | Decimal
    high_price: str | float | Decimal
    low_price: str | float | Decimal
    close_price: str | float | Decimal
    volume: str | float | Decimal = "0"
    closed: bool = True


@dataclass(slots=True, frozen=True)
class CandleIngestionAnomaly:
    record_index: int | None
    anomaly_type: str
    detail: str


@dataclass(slots=True, frozen=True)
class ValidatedCandleBatch:
    """Only successful pipeline output exposes candles to decision consumers."""

    candles: tuple[NormalizedCandle, ...]
    quality: DataQualityReport

    def __post_init__(self) -> None:
        if not self.candles or not self.quality.safe_for_decision:
            raise ValueError("validated candle batch requires safe, non-empty data")


@dataclass(slots=True, frozen=True)
class CandleIngestionResult:
    validated: ValidatedCandleBatch | None
    anomalies: tuple[CandleIngestionAnomaly, ...]

    @property
    def accepted(self) -> bool:
        return self.validated is not None


class CandleDataPipeline:
    """Normalize and validate a complete candle batch before releasing it.

    A single malformed record or critical series-quality issue rejects the whole
    batch. Callers can only obtain candles through ``validated`` after the gate
    passes, keeping partial/unvalidated input out of strategy and agent paths.
    """

    def __init__(self, quality_gate: CandleQualityGate) -> None:
        self.quality_gate = quality_gate

    def ingest(
        self,
        records: tuple[RawCandlePayload, ...] | list[RawCandlePayload],
        *,
        decision_time: datetime,
    ) -> CandleIngestionResult:
        normalized: list[NormalizedCandle] = []
        anomalies: list[CandleIngestionAnomaly] = []
        for index, record in enumerate(records):
            try:
                normalized.append(
                    normalize_candle(
                        symbol=record.symbol,
                        venue=record.venue,
                        timeframe=record.timeframe,
                        open_time=record.open_time,
                        close_time=record.close_time,
                        open_price=record.open_price,
                        high_price=record.high_price,
                        low_price=record.low_price,
                        close_price=record.close_price,
                        volume=record.volume,
                        closed=record.closed,
                    )
                )
            except CandleNormalizationError as exc:
                anomalies.append(
                    CandleIngestionAnomaly(index, "normalization_error", str(exc))
                )

        if anomalies:
            return CandleIngestionResult(validated=None, anomalies=tuple(anomalies))

        quality = self.quality_gate.assess(normalized, decision_time=decision_time)
        anomalies.extend(
            CandleIngestionAnomaly(None, issue.issue_type.value, issue.detail)
            for issue in quality.issues
        )
        if not quality.safe_for_decision:
            return CandleIngestionResult(validated=None, anomalies=tuple(anomalies))
        return CandleIngestionResult(
            validated=ValidatedCandleBatch(tuple(normalized), quality),
            anomalies=(),
        )
