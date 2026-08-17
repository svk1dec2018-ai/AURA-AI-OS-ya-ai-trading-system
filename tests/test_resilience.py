from __future__ import annotations

import pytest

from aura.execution.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    RetryPolicy,
    retry_async,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_circuit_opens_and_allows_single_half_open_probe() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10,
        clock=clock,
    )

    breaker.acquire()
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED

    breaker.acquire()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert not breaker.accepting_requests

    with pytest.raises(CircuitOpenError):
        breaker.acquire()

    clock.advance(10)
    assert breaker.accepting_requests
    breaker.acquire()
    assert breaker.state == CircuitState.HALF_OPEN

    with pytest.raises(CircuitOpenError):
        breaker.acquire()

    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


def test_failed_half_open_probe_reopens_circuit() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=5,
        clock=clock,
    )
    breaker.acquire()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    clock.advance(5)
    breaker.acquire()
    assert breaker.state == CircuitState.HALF_OPEN
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_retry_async_uses_bounded_exponential_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("temporary")
        return "ok"

    async def sleep(delay: float) -> None:
        delays.append(delay)

    result = await retry_async(
        operation,
        policy=RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.1,
            max_delay_seconds=0.2,
            multiplier=2,
        ),
        sleep=sleep,
    )

    assert result == "ok"
    assert attempts == 3
    assert delays == [0.1, 0.2]


@pytest.mark.asyncio
async def test_retry_async_does_not_retry_non_transient_failures() -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("bad request")

    with pytest.raises(ValueError, match="bad request"):
        await retry_async(operation, policy=RetryPolicy(max_attempts=5))

    assert attempts == 1
