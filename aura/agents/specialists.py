from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from aura.agents.base import SpecialistAgent
from aura.agents.models import (
    AgentContext,
    AgentEvidence,
    AgentRole,
    EvidenceSource,
    EvidenceSourceType,
)
from aura.domain.models import NormalizedCandle, SignalIntent


def _market_source(context: AgentContext, suffix: str) -> EvidenceSource:
    latest = context.candles[-1]
    return EvidenceSource(
        source_id=f"market:{latest.venue}:{latest.symbol}:{latest.timeframe}:{suffix}",
        source_type=EvidenceSourceType.MARKET_DATA,
        observed_at=latest.close_time,
        trust_score=1.0,
        point_in_time_safe=True,
    )


def _ema(values: Sequence[Decimal], period: int) -> Decimal:
    if period <= 0 or len(values) < period:
        raise ValueError("EMA requires a positive period and enough observations")
    value = sum(values[:period], Decimal(0)) / Decimal(period)
    alpha = Decimal(2) / Decimal(period + 1)
    for item in values[period:]:
        value = alpha * item + (Decimal(1) - alpha) * value
    return value


def _rsi(values: Sequence[Decimal], period: int = 14) -> Decimal:
    if len(values) < period + 1:
        raise ValueError("RSI requires period + 1 observations")
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    sample = changes[-period:]
    gains = sum((max(change, Decimal(0)) for change in sample), Decimal(0)) / Decimal(period)
    losses = sum((max(-change, Decimal(0)) for change in sample), Decimal(0)) / Decimal(period)
    if losses == 0:
        return Decimal(100)
    relative_strength = gains / losses
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


class TechnicalSpecialist(SpecialistAgent):
    agent_id = "deterministic:technical:v1"
    role = AgentRole.TECHNICAL

    def __init__(self, *, fast_ema: int = 8, slow_ema: int = 21, rsi_period: int = 14) -> None:
        if fast_ema <= 0 or slow_ema <= fast_ema or rsi_period <= 0:
            raise ValueError("invalid technical specialist periods")
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.rsi_period = rsi_period

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        closes = [candle.close for candle in context.candles]
        warmup = max(self.slow_ema, self.rsi_period + 1)
        if len(closes) < warmup:
            return AgentEvidence(
                agent_id=self.agent_id,
                role=self.role,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                thesis=f"technical warmup incomplete: {len(closes)}/{warmup} bars",
                risk_flags=("technical_warmup",),
                sources=(_market_source(context, "technical"),),
                generated_at=context.candles[-1].close_time,
            )

        fast = _ema(closes, self.fast_ema)
        slow = _ema(closes, self.slow_ema)
        rsi = _rsi(closes, self.rsi_period)
        trend_strength = abs(fast - slow) / context.candles[-1].close
        confidence = min(float(trend_strength * Decimal(100)), 1.0)
        if fast > slow and rsi >= Decimal(50):
            intent = SignalIntent.LONG
            thesis = f"EMA{self.fast_ema}>{self.slow_ema} with RSI {rsi:.2f}"
        elif fast < slow and rsi <= Decimal(50):
            intent = SignalIntent.SHORT
            thesis = f"EMA{self.fast_ema}<{self.slow_ema} with RSI {rsi:.2f}"
        else:
            intent = SignalIntent.FLAT
            thesis = f"technical evidence is mixed; RSI {rsi:.2f}"

        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=confidence,
            thesis=thesis,
            sources=(_market_source(context, "technical"),),
            features={"fast_ema": str(fast), "slow_ema": str(slow), "rsi": str(rsi)},
            generated_at=context.candles[-1].close_time,
        )


class SmcIctStructureSpecialist(SpecialistAgent):
    """Causal structural sweep/displacement features inspired by SMC/ICT terminology."""

    agent_id = "deterministic:smc_ict:v1"
    role = AgentRole.SMC_ICT

    def __init__(self, *, lookback: int = 5, displacement_multiple: Decimal = Decimal("1.5")) -> None:
        if lookback < 3 or displacement_multiple <= 0:
            raise ValueError("invalid SMC/ICT specialist settings")
        self.lookback = lookback
        self.displacement_multiple = displacement_multiple

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        candles = context.candles
        if len(candles) < self.lookback + 1:
            return AgentEvidence(
                agent_id=self.agent_id,
                role=self.role,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                thesis="structure warmup incomplete",
                risk_flags=("structure_warmup",),
                sources=(_market_source(context, "smc_ict"),),
                generated_at=candles[-1].close_time,
            )

        latest = candles[-1]
        prior = candles[-(self.lookback + 1) : -1]
        prior_low = min(candle.low for candle in prior)
        prior_high = max(candle.high for candle in prior)
        average_body = sum((abs(candle.close - candle.open) for candle in prior), Decimal(0)) / Decimal(
            len(prior)
        )
        latest_body = abs(latest.close - latest.open)
        displaced = average_body > 0 and latest_body >= average_body * self.displacement_multiple
        swept_low = latest.low < prior_low and latest.close > prior_low
        swept_high = latest.high > prior_high and latest.close < prior_high

        if swept_low and latest.close > latest.open:
            intent = SignalIntent.LONG
            thesis = "sell-side liquidity sweep reclaimed on closed candle"
        elif swept_high and latest.close < latest.open:
            intent = SignalIntent.SHORT
            thesis = "buy-side liquidity sweep rejected on closed candle"
        else:
            intent = SignalIntent.FLAT
            thesis = "no causal liquidity sweep/reclaim structure detected"

        confidence = 0.65 if intent != SignalIntent.FLAT else 0.0
        if intent != SignalIntent.FLAT and displaced:
            confidence = 0.8
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=confidence,
            thesis=thesis,
            sources=(_market_source(context, "smc_ict"),),
            features={
                "prior_low": str(prior_low),
                "prior_high": str(prior_high),
                "swept_low": swept_low,
                "swept_high": swept_high,
                "displacement": displaced,
            },
            generated_at=latest.close_time,
        )


class VolumeVwapSpecialist(SpecialistAgent):
    agent_id = "deterministic:volume_vwap:v1"
    role = AgentRole.VOLUME_VWAP

    def __init__(self, *, min_bars: int = 5) -> None:
        if min_bars < 2:
            raise ValueError("min_bars must be at least 2")
        self.min_bars = min_bars

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        candles = context.candles
        if len(candles) < self.min_bars:
            return AgentEvidence(
                agent_id=self.agent_id,
                role=self.role,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                thesis="volume/VWAP warmup incomplete",
                risk_flags=("volume_warmup",),
                sources=(_market_source(context, "volume_vwap"),),
                generated_at=candles[-1].close_time,
            )

        total_volume = sum((candle.volume for candle in candles), Decimal(0))
        if total_volume <= 0:
            return AgentEvidence(
                agent_id=self.agent_id,
                role=self.role,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                thesis="volume data unavailable or zero",
                risk_flags=("missing_volume",),
                sources=(_market_source(context, "volume_vwap"),),
                generated_at=candles[-1].close_time,
            )

        typical_notional = sum(
            (((candle.high + candle.low + candle.close) / Decimal(3)) * candle.volume for candle in candles),
            Decimal(0),
        )
        vwap = typical_notional / total_volume
        latest = candles[-1]
        prior_volumes = [candle.volume for candle in candles[:-1]]
        average_prior_volume = sum(prior_volumes, Decimal(0)) / Decimal(len(prior_volumes))
        relative_volume = (
            latest.volume / average_prior_volume if average_prior_volume > 0 else Decimal(0)
        )

        if latest.close > vwap and relative_volume >= Decimal(1):
            intent = SignalIntent.LONG
            thesis = "price above VWAP with at/above-average participation"
        elif latest.close < vwap and relative_volume >= Decimal(1):
            intent = SignalIntent.SHORT
            thesis = "price below VWAP with at/above-average participation"
        else:
            intent = SignalIntent.FLAT
            thesis = "VWAP direction lacks sufficient participation confirmation"

        distance = abs(latest.close - vwap) / latest.close
        confidence = min(float(distance * Decimal(50) + min(relative_volume, Decimal(2)) / Decimal(4)), 1.0)
        if intent == SignalIntent.FLAT:
            confidence = 0.0
        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=intent,
            confidence=confidence,
            thesis=thesis,
            sources=(_market_source(context, "volume_vwap"),),
            features={"vwap": str(vwap), "relative_volume": str(relative_volume)},
            generated_at=latest.close_time,
        )


class RegimeSpecialist(SpecialistAgent):
    """Advisory trend/chop classifier; it abstains from directional voting."""

    agent_id = "deterministic:regime:v1"
    role = AgentRole.REGIME

    def __init__(self, *, lookback: int = 10) -> None:
        if lookback < 3:
            raise ValueError("regime lookback must be at least 3")
        self.lookback = lookback

    async def analyze(self, context: AgentContext) -> AgentEvidence:
        candles = context.candles
        if len(candles) < self.lookback:
            return AgentEvidence(
                agent_id=self.agent_id,
                role=self.role,
                intent=SignalIntent.FLAT,
                confidence=0.0,
                thesis="regime warmup incomplete",
                risk_flags=("regime_warmup",),
                sources=(_market_source(context, "regime"),),
                generated_at=candles[-1].close_time,
            )

        sample = candles[-self.lookback :]
        true_ranges = [candle.high - candle.low for candle in sample]
        atr = sum(true_ranges, Decimal(0)) / Decimal(len(true_ranges))
        net_move = abs(sample[-1].close - sample[0].open)
        path = sum((abs(candle.close - candle.open) for candle in sample), Decimal(0))
        efficiency = net_move / path if path > 0 else Decimal(0)
        regime = "trend" if efficiency >= Decimal("0.45") else "chop"
        risk_flags = ("choppy_regime",) if regime == "chop" else ()

        return AgentEvidence(
            agent_id=self.agent_id,
            role=self.role,
            intent=SignalIntent.FLAT,
            confidence=min(float(efficiency), 1.0),
            thesis=f"regime classified as {regime}",
            risk_flags=risk_flags,
            sources=(_market_source(context, "regime"),),
            features={"atr": str(atr), "efficiency": str(efficiency), "regime": regime},
            generated_at=sample[-1].close_time,
        )
