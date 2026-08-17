from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar


T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds cannot be below base_delay_seconds")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be at least 1")


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    retry_on: tuple[type[Exception], ...] = (TimeoutError, ConnectionError),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Retry only explicitly declared transient failures with bounded backoff."""

    delay = policy.base_delay_seconds
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation()
        except retry_on:
            if attempt >= policy.max_attempts:
                raise
            await sleep(delay)
            delay = min(delay * policy.multiplier, policy.max_delay_seconds)

    raise RuntimeError("unreachable retry loop")


class CircuitBreaker:
    """Small deterministic connector circuit breaker.

    It blocks new connector requests after repeated failures, then permits one
    half-open probe after the recovery timeout. A successful probe closes the
    circuit; a failed probe reopens it.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_timeout_seconds < 0:
            raise ValueError("recovery_timeout_seconds cannot be negative")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False

    def acquire(self) -> None:
        if self.state == CircuitState.OPEN:
            if self._opened_at is None:
                raise CircuitOpenError("connector circuit is open without recovery timestamp")
            if self._clock() - self._opened_at < self.recovery_timeout_seconds:
                raise CircuitOpenError("connector circuit is open")
            self.state = CircuitState.HALF_OPEN
            self._half_open_probe_in_flight = False

        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_probe_in_flight:
                raise CircuitOpenError("connector circuit half-open probe already in flight")
            self._half_open_probe_in_flight = True

    def record_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self._opened_at = None
        self._half_open_probe_in_flight = False

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self._half_open_probe_in_flight = False
        if self.state == CircuitState.HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self._opened_at = self._clock()

    @property
    def accepting_requests(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.HALF_OPEN:
            return not self._half_open_probe_in_flight
        if self._opened_at is None:
            return False
        return self._clock() - self._opened_at >= self.recovery_timeout_seconds


class ResilientCallExecutor:
    """Apply connector circuit breaking and retry policy without duplicate-order risk.

    Calls marked non-idempotent get exactly one network attempt. This is the
    safe default for order submission when a timeout could mean the broker
    accepted the request but the acknowledgement was lost. Broker adapters may
    mark a call idempotent only when their client-order-id semantics are proven.
    """

    def __init__(
        self,
        *,
        breaker: CircuitBreaker,
        retry_policy: RetryPolicy | None = None,
        retry_on: tuple[type[Exception], ...] = (TimeoutError, ConnectionError),
    ) -> None:
        self.breaker = breaker
        self.retry_policy = retry_policy or RetryPolicy()
        self.retry_on = retry_on

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        idempotent: bool,
    ) -> T:
        self.breaker.acquire()
        try:
            if idempotent:
                result = await retry_async(
                    operation,
                    policy=self.retry_policy,
                    retry_on=self.retry_on,
                )
            else:
                result = await operation()
        except self.retry_on:
            self.breaker.record_failure()
            raise
        except Exception:
            self.breaker.record_failure()
            raise
        else:
            self.breaker.record_success()
            return result
