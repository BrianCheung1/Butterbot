from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import URL, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from butterbot.application.operations.idempotency import NullOperationsTelemetry
from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.infrastructure.persistence.process_lock import (
    DatabaseProcessLock,
    ProcessLockUnavailable,
)
from butterbot.infrastructure.persistence.readiness import (
    DEFAULT_REVISION_CONTRACT,
    DatabaseReadinessError,
    RevisionContract,
    SchemaReadinessReport,
    check_schema_readiness,
    validate_database_file,
)
from butterbot.infrastructure.persistence.storage import (
    DatabaseIdentityGuard,
    DatabaseStorageContract,
    fixed_process_lock_path,
)
from butterbot.infrastructure.persistence.storage_monitor import DatabaseStorageMonitor
from butterbot.infrastructure.persistence.unit_of_work import (
    ShutdownCapture,
    ShutdownIncomplete,
    SqlAlchemyUnitOfWorkFactory,
    UnitOfWorkLifecycle,
    WriterAdmissionTimeout,
)

ENGINE_DISPOSAL_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class DatabaseRuntime:
    database_path: Path
    engine: AsyncEngine
    unit_of_work_factory: SqlAlchemyUnitOfWorkFactory
    readiness: SchemaReadinessReport
    storage_monitor: DatabaseStorageMonitor
    _lifecycle: UnitOfWorkLifecycle
    _process_lock: DatabaseProcessLock
    _close_task: asyncio.Task[None] | None = None
    _shutdown_capture: ShutdownCapture | None = None
    _monitor_close_task: asyncio.Task[None] | None = None

    async def close(self, *, drain_timeout_seconds: float = 10.0) -> None:
        current = asyncio.current_task()
        if current is not None and self._lifecycle.owns_task(current):
            raise RuntimeError("database runtime cannot close from inside an active transaction")
        if self._close_task is not None and self._close_task.done():
            try:
                self._close_task.result()
            except ShutdownIncomplete:
                self._close_task = None
        if self._close_task is None:
            if self._shutdown_capture is None:
                self._shutdown_capture = self._lifecycle.begin_shutdown()
            self._close_task = asyncio.create_task(
                self._close(drain_timeout_seconds, self._shutdown_capture)
            )
        cancellation_requested = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                cancellation_requested = True
        await asyncio.shield(self._close_task)
        if cancellation_requested:
            raise asyncio.CancelledError

    async def _close(
        self,
        drain_timeout_seconds: float,
        capture: ShutdownCapture,
    ) -> None:
        monitor_timeout_seconds = max(0.01, drain_timeout_seconds)
        monitor_close = self._monitor_close_for_attempt()
        transaction_drain = asyncio.create_task(
            self._lifecycle.drain(
                capture,
                drain_timeout_seconds,
                cancellation_timeout_seconds=1.0,
            )
        )
        monitor_result, drain_result = await asyncio.gather(
            self._bounded_monitor_close(monitor_close, monitor_timeout_seconds),
            transaction_drain,
            return_exceptions=True,
        )
        failures = [
            result for result in (monitor_result, drain_result) if isinstance(result, BaseException)
        ]
        if failures:
            for failure in failures:
                if isinstance(failure, ShutdownIncomplete):
                    raise failure
            raise ShutdownIncomplete(
                "required storage-monitor shutdown failed; engine and ownership retained"
            ) from failures[0]
        try:
            await asyncio.wait_for(self.engine.dispose(), timeout=ENGINE_DISPOSAL_TIMEOUT_SECONDS)
        except Exception as error:
            raise ShutdownIncomplete(
                "database engine disposal failed; process ownership retained"
            ) from error
        try:
            self._process_lock.release()
        except Exception as error:
            raise ShutdownIncomplete("database process ownership release failed") from error

    def _monitor_close_for_attempt(self) -> asyncio.Task[None]:
        task = self._monitor_close_task
        if task is not None and task.done():
            try:
                task.result()
            except BaseException:
                task = None
        if task is None:
            task = asyncio.create_task(self.storage_monitor.close())
            self._monitor_close_task = task
        return task

    @staticmethod
    async def _bounded_monitor_close(
        monitor_close: asyncio.Task[None],
        timeout_seconds: float,
    ) -> None:
        done, _ = await asyncio.wait({monitor_close}, timeout=timeout_seconds)
        if not done:
            raise ShutdownIncomplete("storage monitor exceeded the bounded shutdown window")
        monitor_close.result()


def sqlite_async_url(database_path: Path) -> URL:
    return URL.create(
        "sqlite+aiosqlite",
        database=f"file:{database_path.as_posix()}",
        query={"mode": "rw", "uri": "true"},
    )


def _configure_sqlite_connection(
    dbapi_connection: DBAPIConnection,
    connection_record: object,
    identity_guard: DatabaseIdentityGuard,
) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA busy_timeout=1000")
        cursor.execute("PRAGMA database_list")
        database_rows = cursor.fetchall()
        main_paths = [str(row[2]) for row in database_rows if str(row[1]) == "main"]
        if len(main_paths) != 1:
            raise RuntimeError("SQLite connection must have exactly one main database")
        identity_guard.verify_connection_path(main_paths[0])
    finally:
        cursor.close()


def _reset_sqlite_connection(
    dbapi_connection: DBAPIConnection,
    connection_record: object,
    connection_proxy: object,
    identity_guard: DatabaseIdentityGuard,
) -> None:
    del connection_proxy
    _configure_sqlite_connection(dbapi_connection, connection_record, identity_guard)


def create_sqlite_engine(
    database_path: Path,
    identity_guard: DatabaseIdentityGuard,
) -> AsyncEngine:
    engine = create_async_engine(
        sqlite_async_url(database_path),
        pool_pre_ping=True,
    )

    def configure_on_connect(connection: DBAPIConnection, record: object) -> None:
        _configure_sqlite_connection(connection, record, identity_guard)

    def configure_on_checkout(
        connection: DBAPIConnection,
        record: object,
        proxy: object,
    ) -> None:
        _reset_sqlite_connection(connection, record, proxy, identity_guard)

    event.listen(
        engine.sync_engine,
        "connect",
        configure_on_connect,
    )
    event.listen(
        engine.sync_engine,
        "checkout",
        configure_on_checkout,
    )
    return engine


async def create_database_runtime(
    database_path: Path,
    *,
    storage_contract: DatabaseStorageContract | None = None,
    revision_contract: RevisionContract = DEFAULT_REVISION_CONTRACT,
    telemetry: OperationsTelemetry | None = None,
    configured_mutations_enabled: bool = False,
) -> DatabaseRuntime:
    effective_contract = storage_contract or DatabaseStorageContract(database_path.parent)
    storage = validate_database_file(database_path, effective_contract)
    process_lock = DatabaseProcessLock(fixed_process_lock_path(storage))
    engine: AsyncEngine | None = None
    try:
        process_lock.acquire()
    except ProcessLockUnavailable as error:
        raise DatabaseReadinessError(
            "process_lock_unavailable",
            "another process owns the database writer lock",
            expected_revision=revision_contract.expected,
        ) from error
    try:
        storage = validate_database_file(database_path, effective_contract)
        canonical_path = storage.database_path
        identity_guard = DatabaseIdentityGuard(storage)
        engine = create_sqlite_engine(canonical_path, identity_guard)
        readiness = await check_schema_readiness(
            engine,
            canonical_path,
            storage=storage,
            storage_contract=effective_contract,
            revision_contract=revision_contract,
        )
        lifecycle = UnitOfWorkLifecycle()
        storage_monitor = DatabaseStorageMonitor(
            storage=storage,
            contract=effective_contract,
            engine=engine,
            telemetry=telemetry or NullOperationsTelemetry(),
            configured_mutations_enabled=configured_mutations_enabled,
        )
        identity_guard.set_failure_callback(storage_monitor.identity_failure)
        await storage_monitor.sample()
        if not storage_monitor.is_safe():
            raise DatabaseReadinessError(
                "unsafe_storage",
                "initial database storage monitoring sample failed",
                expected_revision=revision_contract.expected,
            )
        storage_monitor.start()
    except BaseException:
        if engine is not None:
            await engine.dispose()
        process_lock.release()
        raise
    return DatabaseRuntime(
        database_path=canonical_path,
        engine=engine,
        unit_of_work_factory=SqlAlchemyUnitOfWorkFactory(
            engine,
            lifecycle,
            identity_guard=identity_guard,
        ),
        readiness=readiness,
        storage_monitor=storage_monitor,
        _lifecycle=lifecycle,
        _process_lock=process_lock,
    )


def is_sqlite_busy(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, WriterAdmissionTimeout):
            return True
        if isinstance(current, sqlite3.OperationalError) and "locked" in str(current).lower():
            return True
        current = current.__cause__
    return False
