from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

from aura.domain.models import NormalizedCandle, SignalIntent, StrategySignal
from aura.research.strategy_factory import ExitPrimitive, StrategyBlueprint, StrategyPrimitive
from aura.strategy.base import Strategy, StrategyRuntimeContext
from aura.strategy.ema import _ema


class BlueprintCompilationError(ValueError):
    pass


EXECUTABLE_ENTRY_PRIMITIVES = (
    StrategyPrimitive.EMA_TREND,
    StrategyPrimitive.MACD_MOMENTUM,
    StrategyPrimitive.BOLLINGER_REVERSION,
    StrategyPrimitive.KELTNER_BREAKOUT,
    StrategyPrimitive.VWAP,
    StrategyPrimitive.LIQUIDITY_SWEEP,
    StrategyPrimitive.BOS_CHOCH,
    StrategyPrimitive.FAIR_VALUE_GAP,
)

EXECUTABLE_CONFIRMATION_PRIMITIVES = (
    StrategyPrimitive.RSI_STATE,
    StrategyPrimitive.ATR_VOLATILITY,
    StrategyPrimitive.RELATIVE_VOLUME,
    StrategyPrimitive.OBV_VPT,
    StrategyPrimitive.PREMIUM_DISCOUNT,
    StrategyPrimitive.REGIME,
)

EXECUTABLE_EXIT_PRIMITIVES = (
    ExitPrimitive.ATR_STOP,
    ExitPrimitive.STRUCTURE_STOP,
    ExitPrimitive.RISK_REWARD_TARGET,
    ExitPrimitive.ATR_TRAILING,
    ExitPrimitive.VWAP_EXIT,
    ExitPrimitive.TIME_STOP,
    ExitPrimitive.REGIME_EXIT,
)


class CompiledBlueprintStrategy(Strategy):
    """Causal executable strategy compiled from an immutable safe blueprint.

    Only candle-native primitives are accepted here. Context-dependent primitives
    such as options flow, macro, cross-market or execution-quality evidence are not
    approximated or silently substituted. Exits request FLAT through the shared
    DecisionPipeline and therefore remain subject to the independent RiskEngine.
    """

    def __init__(self, blueprint: StrategyBlueprint) -> None:
        _validate_executable_blueprint(blueprint)
        self.blueprint = blueprint
        self.strategy_id = f"compiled.{blueprint.blueprint_id}"
        self.warmup_bars = _warmup_bars(blueprint)

    def on_closed_candle(
        self,
        history: Sequence[NormalizedCandle],
    ) -> StrategySignal | None:
        return self.on_closed_candle_with_context(history, StrategyRuntimeContext())

    def on_closed_candle_with_context(
        self,
        history: Sequence[NormalizedCandle],
        runtime: StrategyRuntimeContext,
    ) -> StrategySignal | None:
        if len(history) < self.warmup_bars:
            return None
        recent = history[-self.warmup_bars :]
        latest = history[-1]
        if any(not item.closed for item in recent):
            return None
        if any(
            item.symbol != latest.symbol or item.timeframe != latest.timeframe
            for item in recent
        ):
            return None

        if runtime.current_position_quantity != 0:
            exit_reason = self._exit_reason(history, runtime)
            if exit_reason is None:
                return None
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=latest.symbol,
                intent=SignalIntent.FLAT,
                confidence=1.0,
                reference_price=latest.close,
                generated_at=latest.close_time,
                reason=f"compiled blueprint exit: {exit_reason}",
                exit_position=True,
            )

        entry_votes = {
            primitive.value: self._primitive_vote(primitive, history)
            for primitive in self.blueprint.entries
        }
        long_entries = sum(value > 0 for value in entry_votes.values())
        short_entries = sum(value < 0 for value in entry_votes.values())
        required_entries = max(1, len(entry_votes) // 2 + 1)
        if long_entries >= required_entries and long_entries > short_entries:
            direction = 1
            intent = SignalIntent.LONG
            entry_strength = long_entries / len(entry_votes)
        elif short_entries >= required_entries and short_entries > long_entries:
            direction = -1
            intent = SignalIntent.SHORT
            entry_strength = short_entries / len(entry_votes)
        else:
            return None

        confirmation_votes = {
            primitive.value: self._primitive_vote(primitive, history)
            for primitive in self.blueprint.confirmations
        }
        aligned_confirmations = sum(
            value == direction for value in confirmation_votes.values()
        )
        required_confirmations = min(
            len(confirmation_votes),
            int(self.blueprint.parameters.get("minimum_confirmations", 1)),
        )
        if aligned_confirmations < required_confirmations:
            return None

        confirmation_strength = (
            aligned_confirmations / len(confirmation_votes)
            if confirmation_votes
            else 1.0
        )
        confidence = min(
            0.99,
            0.50 + 0.30 * entry_strength + 0.19 * confirmation_strength,
        )
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=latest.symbol,
            intent=intent,
            confidence=confidence,
            reference_price=latest.close,
            generated_at=latest.close_time,
            reason=(
                f"compiled blueprint entries={entry_votes}; "
                f"confirmations={confirmation_votes}"
            ),
        )

    def _primitive_vote(
        self,
        primitive: StrategyPrimitive,
        history: Sequence[NormalizedCandle],
    ) -> int:
        params = self.blueprint.parameters
        closes = [item.close for item in history]
        latest = history[-1]

        if primitive == StrategyPrimitive.EMA_TREND:
            fast = int(params.get("ema_fast", 8))
            slow = int(params.get("ema_slow", 21))
            return _sign(_ema(closes, fast) - _ema(closes, slow))

        if primitive == StrategyPrimitive.MACD_MOMENTUM:
            fast = int(params.get("macd_fast", 12))
            slow = int(params.get("macd_slow", 26))
            signal_period = int(params.get("macd_signal", 9))
            macd_series = _macd_series(closes, fast=fast, slow=slow)
            if len(macd_series) < signal_period:
                return 0
            signal = _ema(macd_series, signal_period)
            return _sign(macd_series[-1] - signal)

        if primitive == StrategyPrimitive.BOLLINGER_REVERSION:
            period = int(params.get("bollinger_period", 20))
            sigma = Decimal(str(params.get("bollinger_sigma", 2.0)))
            window = closes[-period:]
            mean = sum(window, Decimal(0)) / Decimal(len(window))
            variance = sum((value - mean) ** 2 for value in window) / Decimal(len(window))
            stdev = variance.sqrt() if variance > 0 else Decimal(0)
            upper = mean + sigma * stdev
            lower = mean - sigma * stdev
            return -1 if latest.close >= upper else 1 if latest.close <= lower else 0

        if primitive == StrategyPrimitive.KELTNER_BREAKOUT:
            period = int(params.get("keltner_period", 20))
            multiple = Decimal(str(params.get("keltner_atr_multiple", 2.0)))
            middle = _ema(closes, period)
            atr = _atr(history[-(period + 1) :])
            upper = middle + multiple * atr
            lower = middle - multiple * atr
            return 1 if latest.close > upper else -1 if latest.close < lower else 0

        if primitive == StrategyPrimitive.VWAP:
            vwap = _session_vwap(history)
            return _sign(latest.close - vwap)

        if primitive == StrategyPrimitive.LIQUIDITY_SWEEP:
            lookback = int(params.get("structure_lookback", 13))
            prior = history[-1 - lookback : -1]
            prior_high = max(item.high for item in prior)
            prior_low = min(item.low for item in prior)
            if latest.low < prior_low and latest.close > prior_low:
                return 1
            if latest.high > prior_high and latest.close < prior_high:
                return -1
            return 0

        if primitive == StrategyPrimitive.BOS_CHOCH:
            lookback = int(params.get("structure_lookback", 13))
            prior = history[-1 - lookback : -1]
            prior_high = max(item.high for item in prior)
            prior_low = min(item.low for item in prior)
            return 1 if latest.close > prior_high else -1 if latest.close < prior_low else 0

        if primitive == StrategyPrimitive.FAIR_VALUE_GAP:
            if len(history) < 3:
                return 0
            left = history[-3]
            atr_period = int(params.get("atr_period", 14))
            atr = _atr(history[-(atr_period + 1) :])
            minimum = atr * Decimal(str(params.get("fvg_min_atr_fraction", 0.2)))
            bullish_gap = latest.low - left.high
            bearish_gap = left.low - latest.high
            if bullish_gap > minimum:
                return 1
            if bearish_gap > minimum:
                return -1
            return 0

        if primitive == StrategyPrimitive.RSI_STATE:
            rsi = _rsi(closes, int(params.get("rsi_period", 14)))
            long_threshold = float(params.get("rsi_long_threshold", 52))
            short_threshold = float(params.get("rsi_short_threshold", 48))
            return 1 if rsi >= long_threshold else -1 if rsi <= short_threshold else 0

        if primitive == StrategyPrimitive.ATR_VOLATILITY:
            period = int(params.get("atr_period", 14))
            current = _atr(history[-(period + 1) :])
            prior_slice = history[-(period + 2) : -1]
            prior = _atr(prior_slice)
            if prior <= 0 or current <= prior:
                return 0
            return _sign(latest.close - latest.open)

        if primitive == StrategyPrimitive.RELATIVE_VOLUME:
            period = 20
            prior = history[-1 - period : -1]
            average = sum((item.volume for item in prior), Decimal(0)) / Decimal(len(prior))
            minimum = Decimal(str(params.get("relative_volume_min", 1.2)))
            if average <= 0 or latest.volume < average * minimum:
                return 0
            return _sign(latest.close - latest.open)

        if primitive == StrategyPrimitive.OBV_VPT:
            lookback = min(20, len(history) - 1)
            if lookback < 2:
                return 0
            score = Decimal(0)
            for prior, current in pairwise(history[-(lookback + 1) :]):
                if current.close > prior.close:
                    score += current.volume
                elif current.close < prior.close:
                    score -= current.volume
            return _sign(score)

        if primitive == StrategyPrimitive.PREMIUM_DISCOUNT:
            lookback = int(params.get("structure_lookback", 20))
            window = history[-lookback:]
            high = max(item.high for item in window)
            low = min(item.low for item in window)
            equilibrium = (high + low) / Decimal(2)
            return 1 if latest.close < equilibrium else -1 if latest.close > equilibrium else 0

        if primitive == StrategyPrimitive.REGIME:
            fast = int(params.get("ema_fast", 8))
            slow = int(params.get("ema_slow", 21))
            atr = _atr(history[-22:])
            spread = _ema(closes, fast) - _ema(closes, slow)
            if atr <= 0 or abs(spread) < atr * Decimal("0.25"):
                return 0
            return _sign(spread)

        raise BlueprintCompilationError(
            f"primitive is not executable in candle compiler: {primitive.value}"
        )

    def _exit_reason(
        self,
        history: Sequence[NormalizedCandle],
        runtime: StrategyRuntimeContext,
    ) -> str | None:
        latest = history[-1]
        params = self.blueprint.parameters
        is_long = runtime.current_position_quantity > 0
        entry = runtime.average_entry_price
        atr_period = int(params.get("atr_period", 14))
        atr = _atr(history[-(atr_period + 1) :])

        for exit_primitive in self.blueprint.exits:
            if exit_primitive == ExitPrimitive.ATR_STOP and atr > 0:
                multiple = Decimal(str(params.get("atr_stop_multiple", 1.5)))
                stop = entry - atr * multiple if is_long else entry + atr * multiple
                if (is_long and latest.close <= stop) or (
                    not is_long and latest.close >= stop
                ):
                    return f"atr_stop@{stop}"

            elif exit_primitive == ExitPrimitive.STRUCTURE_STOP:
                lookback = int(params.get("structure_lookback", 13))
                prior = history[-1 - lookback : -1]
                if prior:
                    stop = (
                        min(item.low for item in prior)
                        if is_long
                        else max(item.high for item in prior)
                    )
                    if (is_long and latest.close <= stop) or (
                        not is_long and latest.close >= stop
                    ):
                        return f"structure_stop@{stop}"

            elif exit_primitive == ExitPrimitive.RISK_REWARD_TARGET and atr > 0:
                stop_multiple = Decimal(str(params.get("atr_stop_multiple", 1.5)))
                reward_multiple = Decimal(str(params.get("reward_risk_multiple", 2.0)))
                risk_distance = atr * stop_multiple
                target = (
                    entry + risk_distance * reward_multiple
                    if is_long
                    else entry - risk_distance * reward_multiple
                )
                if (is_long and latest.close >= target) or (
                    not is_long and latest.close <= target
                ):
                    return f"risk_reward_target@{target}"

            elif exit_primitive == ExitPrimitive.ATR_TRAILING and atr > 0:
                bars = max(1, min(runtime.bars_in_position, len(history)))
                position_window = history[-bars:]
                multiple = Decimal(str(params.get("trailing_atr_multiple", 1.5)))
                trailing = (
                    max(item.high for item in position_window) - atr * multiple
                    if is_long
                    else min(item.low for item in position_window) + atr * multiple
                )
                if (is_long and latest.close <= trailing) or (
                    not is_long and latest.close >= trailing
                ):
                    return f"atr_trailing@{trailing}"

            elif exit_primitive == ExitPrimitive.VWAP_EXIT:
                vwap = _session_vwap(history)
                if (is_long and latest.close < vwap) or (
                    not is_long and latest.close > vwap
                ):
                    return f"vwap_exit@{vwap}"

            elif exit_primitive == ExitPrimitive.TIME_STOP:
                maximum = int(params.get("max_holding_bars", 13))
                if runtime.bars_in_position >= maximum:
                    return f"time_stop@{maximum}_bars"

            elif exit_primitive == ExitPrimitive.REGIME_EXIT:
                regime_vote = self._primitive_vote(StrategyPrimitive.REGIME, history)
                if (is_long and regime_vote < 0) or (not is_long and regime_vote > 0):
                    return "regime_exit"

        return None


def compile_blueprint(blueprint: StrategyBlueprint) -> CompiledBlueprintStrategy:
    return CompiledBlueprintStrategy(blueprint)


def _validate_executable_blueprint(blueprint: StrategyBlueprint) -> None:
    unsupported_entries = [
        item.value for item in blueprint.entries if item not in EXECUTABLE_ENTRY_PRIMITIVES
    ]
    unsupported_confirmations = [
        item.value
        for item in blueprint.confirmations
        if item not in EXECUTABLE_CONFIRMATION_PRIMITIVES
    ]
    unsupported_exits = [
        item.value for item in blueprint.exits if item not in EXECUTABLE_EXIT_PRIMITIVES
    ]
    if unsupported_entries or unsupported_confirmations or unsupported_exits:
        pieces = []
        if unsupported_entries:
            pieces.append(f"entries={unsupported_entries}")
        if unsupported_confirmations:
            pieces.append(f"confirmations={unsupported_confirmations}")
        if unsupported_exits:
            pieces.append(f"exits={unsupported_exits}")
        raise BlueprintCompilationError(
            "blueprint requires non-candle execution context: " + "; ".join(pieces)
        )


def _warmup_bars(blueprint: StrategyBlueprint) -> int:
    params = blueprint.parameters
    values = [30]
    for key in (
        "ema_slow",
        "macd_slow",
        "bollinger_period",
        "keltner_period",
        "rsi_period",
        "atr_period",
        "structure_lookback",
    ):
        value = params.get(key)
        if isinstance(value, (int, float)):
            values.append(int(value) + 5)
    values.append(25)
    return max(values)


def _ema_series(values: Sequence[Decimal], period: int) -> list[Decimal]:
    if not values:
        return []
    alpha = Decimal(2) / Decimal(period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (Decimal(1) - alpha) * output[-1])
    return output


def _macd_series(
    values: Sequence[Decimal],
    *,
    fast: int,
    slow: int,
) -> list[Decimal]:
    fast_values = _ema_series(values, fast)
    slow_values = _ema_series(values, slow)
    return [fast_value - slow_value for fast_value, slow_value in zip(fast_values, slow_values)]


def _rsi(values: Sequence[Decimal], period: int) -> float:
    window = values[-(period + 1) :]
    gains = Decimal(0)
    losses = Decimal(0)
    for prior, current in pairwise(window):
        change = current - prior
        if change > 0:
            gains += change
        elif change < 0:
            losses -= change
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return float(Decimal(100) - Decimal(100) / (Decimal(1) + rs))


def _atr(candles: Sequence[NormalizedCandle]) -> Decimal:
    if len(candles) < 2:
        return Decimal(0)
    values: list[Decimal] = []
    for prior, current in pairwise(candles):
        values.append(
            max(
                current.high - current.low,
                abs(current.high - prior.close),
                abs(current.low - prior.close),
            )
        )
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else Decimal(0)


def _session_vwap(history: Sequence[NormalizedCandle]) -> Decimal:
    latest_date = history[-1].close_time.date()
    session = [item for item in history if item.close_time.date() == latest_date]
    total_volume = sum((item.volume for item in session), Decimal(0))
    if total_volume <= 0:
        return sum((item.close for item in session), Decimal(0)) / Decimal(len(session))
    weighted = sum(
        (((item.high + item.low + item.close) / Decimal(3)) * item.volume for item in session),
        Decimal(0),
    )
    return weighted / total_volume


def _sign(value: Decimal) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0
