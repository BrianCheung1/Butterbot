from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Any, Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from butterbot.application.operations.telemetry import emit_operational_telemetry
from butterbot.infrastructure.persistence.repositories import (
    AggregateCompletenessTracker,
    SqlAlchemyAccountRepository,
    SqlAlchemyPlayerRepository,
    SqlAlchemyTransportIdempotencyRepository,
)
from butterbot.infrastructure.persistence.safety import SqlAlchemySafetyRepository
from butterbot.infrastructure.persistence.storage import (
    DatabaseIdentityGuard,
    DatabaseIdentityMismatch,
)

logger = logging.getLogger(__name__)


class TransactionPhase(Enum):
    NEW = "new"
    STARTING = "starting"
    ACTIVE = "active"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ShutdownIncomplete(RuntimeError):
    """Shutdown reached its fail-stop bound while transaction owners remained alive."""


class WriterAdmissionTimeout(RuntimeError):
    """A writer slot was unavailable within the transaction attempt budget."""


@dataclass(frozen=True, slots=True)
class ShutdownCapture:
    owners: frozenset[asyncio.Task[object]]


class UnitOfWorkLifecycle:
    def __init__(self) -> None:
        self._active: dict[SqlAlchemyUnitOfWork, asyncio.Task[object]] = {}
        self._unresolved: set[SqlAlchemyUnitOfWork] = set()
        self._waiting: set[asyncio.Task[object]] = set()
        self._accepting = True
        self._writer_slots = asyncio.Semaphore(4)

    async def register(
        self,
        unit_of_work: SqlAlchemyUnitOfWork,
        admission_budget_ms: int,
    ) -> float:
        if not self._accepting:
            raise RuntimeError("database lifecycle is draining and rejects new transactions")
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("unit of work requires an asyncio task")
        self._waiting.add(task)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + admission_budget_ms / 1_000
        try:
            try:
                await asyncio.wait_for(
                    self._writer_slots.acquire(),
                    timeout=max(0.0, deadline - loop.time()),
                )
            except TimeoutError as error:
                raise WriterAdmissionTimeout(
                    "writer admission exhausted the transaction attempt budget"
                ) from error
            if not self._accepting:
                self._writer_slots.release()
                raise RuntimeError("database lifecycle is draining and rejects new transactions")
            self._active[unit_of_work] = task
            if deadline <= loop.time():
                raise WriterAdmissionTimeout(
                    "writer admission exhausted the transaction attempt budget"
                )
            return deadline
        finally:
            self._waiting.discard(task)

    def finish(self, unit_of_work: SqlAlchemyUnitOfWork) -> None:
        if unit_of_work in self._active:
            del self._active[unit_of_work]
            self._writer_slots.release()
            if not unit_of_work.resources_closed:
                self._unresolved.add(unit_of_work)

    def begin_shutdown(self) -> ShutdownCapture:
        self._accepting = False
        waiting = frozenset(self._waiting)
        owners = frozenset({*waiting, *self._active.values()})
        for task in waiting:
            task.cancel()
        return ShutdownCapture(owners=owners)

    async def drain(
        self,
        capture: ShutdownCapture,
        timeout_seconds: float,
        cancellation_timeout_seconds: float,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        pending = await self._wait_for_tasks(capture.owners, max(0.0, deadline - loop.time()))
        if pending:
            active_by_owner: dict[asyncio.Task[object], list[SqlAlchemyUnitOfWork]] = {}
            for unit_of_work, owner in self._active.items():
                active_by_owner.setdefault(owner, []).append(unit_of_work)
            for owner in pending:
                active_units = active_by_owner.get(owner, [])
                if not active_units:
                    owner.cancel()
                    continue
                if all(unit.shutdown_cancellable for unit in active_units):
                    for unit in active_units:
                        unit.request_shutdown_cancel()
                    owner.cancel()
            pending = await self._wait_for_tasks(pending, cancellation_timeout_seconds)
        if pending:
            raise ShutdownIncomplete(
                "transaction owner tasks exceeded the bounded shutdown cleanup window"
            )
        if self._active:
            raise ShutdownIncomplete(
                "transaction owner tasks ended without closing their units of work"
            )
        await self._retry_unresolved_cleanup(cancellation_timeout_seconds)

    def owns_task(self, task: asyncio.Task[object]) -> bool:
        return task in self._active.values()

    async def _retry_unresolved_cleanup(self, timeout_seconds: float) -> None:
        attempts: dict[asyncio.Task[None], SqlAlchemyUnitOfWork] = {}
        for unit_of_work in tuple(self._unresolved):
            task = unit_of_work.start_cleanup_attempt()
            if task is None:
                self._unresolved.discard(unit_of_work)
            else:
                attempts[task] = unit_of_work
        if not attempts:
            return
        done, pending = await asyncio.wait(attempts, timeout=timeout_seconds)
        failures: list[BaseException] = []
        for task in done:
            unit_of_work = attempts[task]
            try:
                unit_of_work.finish_cleanup_attempt(task)
            except BaseException as error:
                unit_of_work.record_cleanup_failure(error)
                failures.append(error)
            if unit_of_work.resources_closed:
                self._unresolved.discard(unit_of_work)
        if pending:
            raise ShutdownIncomplete(
                "database resource cleanup exceeded the bounded shutdown window"
            )
        if failures or self._unresolved:
            raise ShutdownIncomplete(
                "database resources remain usable after shutdown cleanup"
            ) from (failures[0] if failures else None)

    @staticmethod
    async def _wait_for_tasks(
        tasks: frozenset[asyncio.Task[object]],
        timeout_seconds: float,
    ) -> frozenset[asyncio.Task[object]]:
        if not tasks:
            return frozenset()
        done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        for task in done:
            if not task.cancelled():
                task.exception()
        return frozenset(pending)


class SqlAlchemyUnitOfWork:
    def __init__(
        self,
        engine: AsyncEngine,
        lifecycle: UnitOfWorkLifecycle,
        maximum_busy_timeout_ms: int,
        admission_budget_ms: int,
        identity_guard: DatabaseIdentityGuard,
        *,
        read_snapshot: bool = False,
    ) -> None:
        self._engine = engine
        self._lifecycle = lifecycle
        self._maximum_busy_timeout_ms = maximum_busy_timeout_ms
        self._admission_budget_ms = admission_budget_ms
        self._identity_guard = identity_guard
        self._read_snapshot = read_snapshot
        self._connection: AsyncConnection | None = None
        self._session: AsyncSession | None = None
        self._after_commit: list[Callable[[], None]] = []
        self._shutdown_cancel_requested = False
        self._cleanup_failed = False
        self._cleanup_task: asyncio.Task[None] | None = None
        self._phase = TransactionPhase.NEW
        self._aggregates: AggregateCompletenessTracker
        self.safety: SqlAlchemySafetyRepository
        self.players: SqlAlchemyPlayerRepository
        self.accounts: SqlAlchemyAccountRepository
        self.transport_requests: SqlAlchemyTransportIdempotencyRepository

    async def __aenter__(self) -> Self:
        self._phase = TransactionPhase.STARTING
        try:
            deadline = await self._lifecycle.register(self, self._admission_budget_ms)
            self._identity_guard.verify_path()
            loop = asyncio.get_running_loop()
            try:
                connection = await asyncio.wait_for(
                    self._engine.connect(), timeout=max(0.0, deadline - loop.time())
                )
            except TimeoutError as error:
                raise WriterAdmissionTimeout(
                    "connection checkout exhausted the transaction attempt budget"
                ) from error
            self._connection = connection
            remaining_budget_ms = int((deadline - loop.time()) * 1_000)
            if remaining_budget_ms < 1:
                raise WriterAdmissionTimeout(
                    "connection checkout exhausted the transaction attempt budget"
                )
            busy_timeout_ms = min(self._maximum_busy_timeout_ms, remaining_budget_ms)
            await connection.execute(text(f"PRAGMA busy_timeout={busy_timeout_ms}"))
            await connection.rollback()
            session = AsyncSession(bind=connection, expire_on_commit=False, autoflush=True)
            self._session = session
            await session.execute(text("BEGIN" if self._read_snapshot else "BEGIN IMMEDIATE"))
            self._phase = TransactionPhase.ACTIVE
            aggregates = AggregateCompletenessTracker()
            self._aggregates = aggregates
            self.safety = SqlAlchemySafetyRepository(session)
            self.players = SqlAlchemyPlayerRepository(session, aggregates)
            self.accounts = SqlAlchemyAccountRepository(session, aggregates)
            self.transport_requests = SqlAlchemyTransportIdempotencyRepository(session)
            return self
        except BaseException:
            self._phase = TransactionPhase.FAILED
            try:
                await self._await_cleanup_completion()
            except BaseException as cleanup_error:
                self.record_cleanup_failure(cleanup_error)
            finally:
                self._lifecycle.finish(self)
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        committed = False
        cancellation_requested = self._cancellation_requested(exc_type)
        completion_error: BaseException | None = None
        try:
            if exc_type is None and not cancellation_requested:
                self.transport_requests.assert_no_pending_requests()
                self._aggregates.assert_complete()
                self._phase = TransactionPhase.COMMITTING
                commit_cancelled = await self._await_completion(self._commit(session))
                cancellation_requested = cancellation_requested or commit_cancelled
                self._phase = TransactionPhase.COMMITTED
                committed = True
                self._run_after_commit_callbacks()
            else:
                self._phase = TransactionPhase.ROLLING_BACK
                rollback_cancelled = await self._await_completion(session.rollback())
                cancellation_requested = cancellation_requested or rollback_cancelled
                self._phase = TransactionPhase.ROLLED_BACK
        except BaseException as error:
            completion_error = error
            if not committed:
                self._phase = TransactionPhase.FAILED
            try:
                await self._await_completion(session.rollback())
            except BaseException:
                emit_operational_telemetry(
                    "database.rollback_cleanup_failure",
                    lambda: logger.exception(
                        "Rollback after transaction completion failure also failed"
                    ),
                )
        finally:
            try:
                close_cancelled = await self._await_cleanup_completion()
                cancellation_requested = cancellation_requested or close_cancelled
            except BaseException as cleanup_error:
                self.record_cleanup_failure(cleanup_error)
            finally:
                self._lifecycle.finish(self)
        if not committed:
            self._after_commit.clear()
        if completion_error is not None:
            raise completion_error.with_traceback(completion_error.__traceback__)
        if cancellation_requested and not committed and exc_type is None:
            raise asyncio.CancelledError

    def defer_until_commit(self, callback: Callable[[], None]) -> None:
        self._require_session()
        self._after_commit.append(callback)

    def request_shutdown_cancel(self) -> None:
        if not self.shutdown_cancellable:
            raise RuntimeError("shutdown cannot cancel a transaction after commit has begun")
        self._shutdown_cancel_requested = True

    @property
    def shutdown_cancellable(self) -> bool:
        return self._phase in {
            TransactionPhase.NEW,
            TransactionPhase.STARTING,
            TransactionPhase.ACTIVE,
        }

    @property
    def transaction_phase(self) -> TransactionPhase:
        return self._phase

    @property
    def resources_closed(self) -> bool:
        return self._session is None and self._connection is None

    @property
    def cleanup_failed(self) -> bool:
        return self._cleanup_failed

    async def _close_resources_attempt(self) -> None:
        session = self._session
        connection = self._connection
        failures: list[BaseException] = []
        if session is not None:
            try:
                await session.close()
            except BaseException as error:
                failures.append(error)
            else:
                if self._session is session:
                    self._session = None
        if connection is not None:
            try:
                await connection.close()
            except BaseException as error:
                failures.append(error)
            else:
                if self._connection is connection:
                    self._connection = None
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("database resource cleanup failed", failures)

    def start_cleanup_attempt(self) -> asyncio.Task[None] | None:
        task = self._cleanup_task
        if task is not None:
            if not task.done():
                return task
            try:
                self.finish_cleanup_attempt(task)
            except BaseException as error:
                self.record_cleanup_failure(error)
        if self.resources_closed:
            return None
        task = asyncio.create_task(self._close_resources_attempt())
        self._cleanup_task = task
        return task

    def finish_cleanup_attempt(self, task: asyncio.Task[None]) -> None:
        if task is not self._cleanup_task:
            raise RuntimeError("database cleanup task ownership changed")
        if not task.done():
            raise RuntimeError("database cleanup task has not finished")
        self._cleanup_task = None
        task.result()

    async def _await_cleanup_completion(self) -> bool:
        task = self.start_cleanup_attempt()
        if task is None:
            return False
        cancellation_requested = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.done():
                    break
                cancellation_requested = True
        self.finish_cleanup_attempt(task)
        return cancellation_requested

    def record_cleanup_failure(self, error: BaseException) -> None:
        self._cleanup_failed = True
        self._identity_guard.mark_unsafe("database_resource_cleanup_failed")
        emit_operational_telemetry(
            "database.resource_cleanup_failure",
            lambda: logger.error(
                "Database unit-of-work resource cleanup failed; runtime mutations are unsafe",
                exc_info=(type(error), error, error.__traceback__),
            ),
        )

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        return self._session

    async def _commit(self, session: AsyncSession) -> None:
        connection = self._connection
        if connection is None:
            raise RuntimeError("unit of work has no active connection")
        main_path = await self._connection_main_path(connection)
        self._identity_guard.verify_connection_path(main_path)
        await session.commit()
        try:
            main_path = await self._connection_main_path(connection)
            self._identity_guard.verify_connection_path(main_path)
        except DatabaseIdentityMismatch:
            self._identity_guard.mark_unsafe("database_identity_mismatch")
            emit_operational_telemetry(
                "database.post_commit_confirmation_failure",
                lambda: logger.critical(
                    "Database identity changed in the final validation-to-commit window; "
                    "the commit remains successful and mutations are now unsafe"
                ),
            )
        except asyncio.CancelledError as error:
            self._identity_guard.mark_unsafe("post_commit_confirmation_failed")
            cancellation_exc_info = (type(error), error, error.__traceback__)
            emit_operational_telemetry(
                "database.post_commit_confirmation_failure",
                lambda cancellation_exc_info=cancellation_exc_info: logger.error(
                    "Post-commit database identity confirmation was cancelled; "
                    "the commit remains successful and mutations are now unsafe",
                    exc_info=cancellation_exc_info,
                ),
            )
        except Exception:
            self._identity_guard.mark_unsafe("post_commit_confirmation_failed")
            emit_operational_telemetry(
                "database.post_commit_confirmation_failure",
                lambda: logger.exception(
                    "Post-commit database identity confirmation failed; the commit remains "
                    "successful and mutations are now unsafe"
                ),
            )

    @staticmethod
    async def _connection_main_path(connection: AsyncConnection) -> str:
        database_rows = (await connection.execute(text("PRAGMA database_list"))).all()
        main_paths = [str(row[2]) for row in database_rows if str(row[1]) == "main"]
        if len(main_paths) != 1:
            raise RuntimeError("SQLite transaction must have exactly one main database")
        return main_paths[0]

    @staticmethod
    async def _await_completion(operation: Coroutine[Any, Any, None]) -> bool:
        task = asyncio.create_task(operation)
        cancellation_requested = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.done():
                    break
                cancellation_requested = True
        task.result()
        return cancellation_requested

    def _run_after_commit_callbacks(self) -> None:
        callbacks, self._after_commit = self._after_commit, []
        for callback in callbacks:
            try:
                callback()
            except BaseException:
                emit_operational_telemetry(
                    "database.post_commit_callback_failure",
                    lambda: logger.exception("Post-commit callback failed"),
                )

    def _cancellation_requested(
        self,
        exc_type: type[BaseException] | None,
    ) -> bool:
        task = asyncio.current_task()
        return (
            self._shutdown_cancel_requested
            or exc_type is asyncio.CancelledError
            or (task is not None and task.cancelling() > 0)
        )


class SqlAlchemyUnitOfWorkFactory:
    def __init__(
        self,
        engine: AsyncEngine,
        lifecycle: UnitOfWorkLifecycle,
        *,
        identity_guard: DatabaseIdentityGuard,
        maximum_busy_timeout_ms: int = 1_000,
    ) -> None:
        self._engine = engine
        self._lifecycle = lifecycle
        self._maximum_busy_timeout_ms = maximum_busy_timeout_ms
        self._identity_guard = identity_guard

    @property
    def identity_guard(self) -> DatabaseIdentityGuard:
        return self._identity_guard

    def __call__(
        self,
        *,
        attempt: int = 1,
        remaining_budget_ms: int = 1_000,
    ) -> SqlAlchemyUnitOfWork:
        if attempt < 1:
            raise ValueError("transaction attempt must be positive")
        if remaining_budget_ms < 1:
            raise ValueError("remaining transaction budget must be positive")
        return SqlAlchemyUnitOfWork(
            self._engine,
            self._lifecycle,
            self._maximum_busy_timeout_ms,
            remaining_budget_ms,
            self._identity_guard,
        )

    def read_snapshot(
        self, *, attempt: int = 1, remaining_budget_ms: int = 1_000
    ) -> SqlAlchemyUnitOfWork:
        """Deferred snapshot for query services, sharing ownership/drain/identity checks.

        Callers must use only repository reads; this is not a write-capability sandbox.
        """
        if attempt < 1 or remaining_budget_ms < 1:
            raise ValueError("read attempt and budget must be positive")
        return SqlAlchemyUnitOfWork(
            self._engine,
            self._lifecycle,
            self._maximum_busy_timeout_ms,
            remaining_budget_ms,
            self._identity_guard,
            read_snapshot=True,
        )
