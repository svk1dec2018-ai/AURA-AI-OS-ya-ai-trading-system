from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aura.markets.universe import OptionType
from aura.options.intelligence import (
    OptionChainAggregator,
    OptionContractObservation,
    OptionGreeks,
)


def _obs(
    side: OptionType,
    strike: int,
    *,
    oi: int,
    volume: int,
    iv: float,
    delta: float,
    gamma: float = 0.001,
    bid: str = "99",
    ask: str = "101",
):
    now = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    return OptionContractObservation(
        underlying="NIFTY",
        expiry=now + timedelta(days=10),
        strike=Decimal(strike),
        option_type=side,
        spot=Decimal(25020),
        last_price=Decimal(100),
        bid=Decimal(bid),
        ask=Decimal(ask),
        open_interest=Decimal(oi),
        volume=Decimal(volume),
        implied_volatility=iv,
        greeks=OptionGreeks(delta=delta, gamma=gamma, theta=-5, vega=10),
        observed_at=now,
    )


def test_option_chain_aggregates_pcr_atm_iv_skew_and_greeks() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    observations = (
        _obs(OptionType.CALL, 25000, oi=100, volume=50, iv=0.18, delta=0.52),
        _obs(OptionType.PUT, 25000, oi=150, volume=75, iv=0.20, delta=-0.48),
        _obs(OptionType.CALL, 25100, oi=50, volume=20, iv=0.19, delta=0.40),
        _obs(OptionType.PUT, 25100, oi=100, volume=40, iv=0.22, delta=-0.60),
    )
    result = OptionChainAggregator().aggregate(observations, as_of=now)
    assert result.put_call_oi_ratio == 250 / 150
    assert result.put_call_volume_ratio == 115 / 70
    assert result.atm_strike == Decimal(25000)
    assert result.atm_iv == 0.19
    assert abs(result.put_minus_call_atm_iv - 0.02) < 1e-12
    assert result.expected_move_1sigma is not None
    assert result.expected_move_1sigma > 0
    assert result.weighted_greeks.open_interest_weight == 400.0
    assert result.unsigned_gamma_oi_proxy > 0
    assert result.liquid_contracts == 4


def test_future_observations_cannot_leak_into_point_in_time_chain() -> None:
    now = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    visible = _obs(OptionType.CALL, 25000, oi=100, volume=50, iv=0.18, delta=0.52)
    future = visible.model_copy(
        update={
            "observed_at": now + timedelta(minutes=1),
            "open_interest": Decimal(999999),
        }
    )
    result = OptionChainAggregator().aggregate((visible, future), as_of=now)
    assert result.weighted_greeks.open_interest_weight == 100.0
