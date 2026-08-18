from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from aura.domain.models import NormalizedCandle
from aura.markets.universe import AssetClass, CanonicalInstrument


class DhanRadarPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    top_k_tradable: int = Field(default=40, ge=1, le=500)
    lookback_bars: int = Field(default=6, ge=3, le=30)
    min_history_bars: int = Field(default=3, ge=2, le=30)
    one_bar_weight: float = Field(default=0.40, ge=0)
    rolling_move_weight: float = Field(default=0.35, ge=0)
    acceleration_weight: float = Field(default=0.25, ge=0)


@dataclass(slots=True, frozen=True)
class RadarScore:
    symbol: str
    score: float
    one_bar_move_bps: float
    rolling_move_bps: float
    acceleration_bps: float


@dataclass(slots=True, frozen=True)
class DhanRadarSelection:
    selected_tradable_symbols: tuple[str, ...]
    context_index_symbols: tuple[str, ...]
    ranked: tuple[RadarScore, ...]


class DhanOpportunityRadar:
    """Cheap broad-universe radar before expensive AURA deep intelligence.

    It uses only causal 1-minute price action available from Dhan Ticker mode.
    It deliberately does not fabricate volume/order-book features. Full depth/OI,
    options intelligence and the ten-agent desk belong to the second stage.
    """

    def __init__(
        self,
        instruments: tuple[CanonicalInstrument, ...] | list[CanonicalInstrument],
        *,
        policy: DhanRadarPolicy | None = None,
    ) -> None:
        self.policy = policy or DhanRadarPolicy()
        self._instrument_by_symbol = {
            item.canonical_symbol: item for item in instruments
        }
        self._history: dict[str, list[NormalizedCandle]] = {}
        self._priority_symbols: set[str] = set()
        self._last_selection = DhanRadarSelection((), (), ())

    @property
    def last_selection(self) -> DhanRadarSelection:
        return self._last_selection

    def set_priority_symbols(self, symbols: set[str] | frozenset[str]) -> None:
        self._priority_symbols = {
            symbol for symbol in symbols if symbol in self._instrument_by_symbol
        }

    def observe(
        self,
        candles: tuple[NormalizedCandle, ...] | list[NormalizedCandle],
    ) -> DhanRadarSelection:
        for candle in candles:
            if candle.timeframe != "1m" or not candle.closed:
                continue
            if candle.symbol not in self._instrument_by_symbol:
                continue
            history = self._history.setdefault(candle.symbol, [])
            if history and candle.close_time <= history[-1].close_time:
                if candle.close_time == history[-1].close_time:
                    history[-1] = candle
                    continue
                raise ValueError(f"out-of-order radar candle for {candle.symbol}")
            history.append(candle)
            del history[: max(0, len(history) - self.policy.lookback_bars)]

        scores: list[RadarScore] = []
        context_indices: list[str] = []
        for symbol, instrument in self._instrument_by_symbol.items():
            if instrument.asset_class == AssetClass.INDEX:
                if len(self._history.get(symbol, ())) >= self.policy.min_history_bars:
                    context_indices.append(symbol)
                continue
            if not instrument.tradable:
                continue
            history = self._history.get(symbol, [])
            if len(history) < self.policy.min_history_bars:
                continue
            scores.append(_score(symbol, history, self.policy))

        scores.sort(key=lambda item: (-item.score, item.symbol))
        selected = [item.symbol for item in scores[: self.policy.top_k_tradable]]
        for symbol in sorted(self._priority_symbols):
            instrument = self._instrument_by_symbol[symbol]
            if instrument.tradable and symbol not in selected:
                selected.append(symbol)
        self._last_selection = DhanRadarSelection(
            selected_tradable_symbols=tuple(selected),
            context_index_symbols=tuple(sorted(context_indices)),
            ranked=tuple(scores),
        )
        return self._last_selection

    def history(self, symbol: str) -> tuple[NormalizedCandle, ...]:
        return tuple(self._history.get(symbol, ()))


def _score(
    symbol: str,
    history: list[NormalizedCandle],
    policy: DhanRadarPolicy,
) -> RadarScore:
    latest = history[-1]
    previous = history[-2]
    first = history[0]
    one_bar = _return_bps(latest.open, latest.close)
    previous_bar = _return_bps(previous.open, previous.close)
    rolling = _return_bps(first.close, latest.close)
    acceleration = one_bar - previous_bar
    score = (
        policy.one_bar_weight * abs(one_bar)
        + policy.rolling_move_weight * abs(rolling)
        + policy.acceleration_weight * abs(acceleration)
    )
    return RadarScore(
        symbol=symbol,
        score=score,
        one_bar_move_bps=one_bar,
        rolling_move_bps=rolling,
        acceleration_bps=acceleration,
    )


def _return_bps(start: Decimal, end: Decimal) -> float:
    if start <= 0:
        return 0.0
    return float((end - start) / start * Decimal(10000))
