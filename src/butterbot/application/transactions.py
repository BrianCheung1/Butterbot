from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from types import TracebackType
from typing import Protocol, Self

from butterbot.application.economy.ports import AccountRepository
from butterbot.application.operations.ports import (
    OperationsTelemetry,
    TransportIdempotencyRepository,
)
from butterbot.application.operations.telemetry import emit_operational_telemetry
from butterbot.application.players.ports import PlayerRepository
from butterbot.application.safety.ports import SafetyRepository


class UnitOfWork(Protocol):
    @property
    def safety(self) -> SafetyRepository: ...

    @property
    def players(self) -> PlayerRepository: ...

    @property
    def accounts(self) -> AccountRepository: ...

    @property
    def transport_requests(self) -> TransportIdempotencyRepository: ...

    def defer_until_commit(self, callback: Callable[[], None]) -> None: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(
        self,
        *,
        attempt: int = 1,
        remaining_budget_ms: int = 1_000,
    ) -> UnitOfWork: ...


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 2
    total_budget_ms: int = 3_000
    backoff_ms: tuple[int, ...] = (25, 75)
    deadline_guard_ms: int = 200


DEFAULT_RETRY_POLICY = RetryPolicy()


class DatabaseRetryExhausted(RuntimeError):
    """The database remained unavailable beyond the accepted retry budget."""


class ApplicationTransactionRunner:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        is_retryable: Callable[[BaseException], bool],
        telemetry: OperationsTelemetry,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._is_retryable = is_retryable
        self._telemetry = telemetry
        self._policy = retry_policy

    async def run[T](
        self,
        operation_name: str,
        body: Callable[[UnitOfWork], Awaitable[T]],
    ) -> T:
        started = perf_counter()
        attempts = 0
        while True:
            elapsed_before_attempt_ms = (perf_counter() - started) * 1_000
            remaining_before_attempt_ms = self._policy.total_budget_ms - elapsed_before_attempt_ms
            if remaining_before_attempt_ms <= self._policy.deadline_guard_ms:
                emit_operational_telemetry(
                    "database.busy_exhausted",
                    lambda attempts=attempts, elapsed_before_attempt_ms=elapsed_before_attempt_ms: (
                        self._telemetry.database_busy_exhausted(
                            operation=operation_name,
                            attempts=attempts,
                            elapsed_ms=elapsed_before_attempt_ms,
                        )
                    ),
                )
                raise DatabaseRetryExhausted(
                    f"{operation_name} exhausted the database retry budget"
                )
            attempts += 1
            remaining_attempt_budget_ms = max(
                1,
                int(remaining_before_attempt_ms - self._policy.deadline_guard_ms),
            )
            try:
                async with self._unit_of_work_factory(
                    attempt=attempts,
                    remaining_budget_ms=remaining_attempt_budget_ms,
                ) as unit_of_work:
                    return await body(unit_of_work)
            except BaseException as error:
                if not self._is_retryable(error):
                    raise
                elapsed_ms = (perf_counter() - started) * 1_000
                if (
                    attempts > self._policy.max_retries
                    or elapsed_ms >= self._policy.total_budget_ms
                ):
                    emit_operational_telemetry(
                        "database.busy_exhausted",
                        lambda attempts=attempts, elapsed_ms=elapsed_ms: (
                            self._telemetry.database_busy_exhausted(
                                operation=operation_name,
                                attempts=attempts,
                                elapsed_ms=elapsed_ms,
                            )
                        ),
                    )
                    raise DatabaseRetryExhausted(
                        f"{operation_name} exhausted the database retry budget"
                    ) from error
                backoff_index = min(attempts - 1, len(self._policy.backoff_ms) - 1)
                wait_ms = min(
                    self._policy.backoff_ms[backoff_index],
                    max(
                        0,
                        int(
                            self._policy.total_budget_ms
                            - self._policy.deadline_guard_ms
                            - elapsed_ms
                        ),
                    ),
                )
                emit_operational_telemetry(
                    "database.busy_retry",
                    lambda attempts=attempts, wait_ms=wait_ms, elapsed_ms=elapsed_ms: (
                        self._telemetry.database_busy_retry(
                            operation=operation_name,
                            attempt=attempts,
                            wait_ms=wait_ms,
                            elapsed_ms=elapsed_ms,
                        )
                    ),
                )
                await asyncio.sleep(wait_ms / 1_000)
