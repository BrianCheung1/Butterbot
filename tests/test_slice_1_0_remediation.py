from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from butterbot.application.exact_integer import (
    INT64_MAX,
    INT64_MIN,
    ExactIntegerOutOfRange,
    checked_add_int64,
)
from butterbot.application.operations.idempotency import (
    NullOperationsTelemetry,
    RetentionRegistry,
    TransportIdempotencyCoordinator,
    TransportRequest,
)
from butterbot.application.operations.outcome_codec import InvalidStableOutcome
from butterbot.application.operations.ports import (
    DatabaseStorageSnapshot,
    JsonValue,
    StableOutcome,
    TransportActor,
)
from butterbot.infrastructure.persistence.database import (
    DatabaseRuntime,
    create_database_runtime,
)
from butterbot.infrastructure.persistence.process_lock import (
    DatabaseProcessLock,
    ProcessLockUnavailable,
)
from butterbot.infrastructure.persistence.readiness import DatabaseReadinessError
from butterbot.infrastructure.persistence.repositories import CorruptTransportOutcome
from butterbot.infrastructure.persistence.storage import (
    DatabaseIdentityMismatch,
    DatabaseStorageContract,
    validate_database_storage,
)
from butterbot.infrastructure.persistence.storage_monitor import DatabaseStorageMonitor
from butterbot.infrastructure.persistence.unit_of_work import (
    ShutdownIncomplete,
    SqlAlchemyUnitOfWork,
    TransactionPhase,
)
from butterbot.infrastructure.persistence.verification import (
    HistoricalVerificationError,
    verify_historical_persistence,
)


def _player_count(database: Path, discord_user_id: int) -> int:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM players WHERE discord_user_id = ?", (discord_user_id,)
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        connection.close()


async def test_cancellation_immediately_before_commit_rolls_back_cleanly(
    database_runtime: DatabaseRuntime,
) -> None:
    callbacks: list[str] = []
    observed: SqlAlchemyUnitOfWork | None = None

    async def owner() -> None:
        nonlocal observed
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            observed = unit_of_work
            await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=1_001, created_at_ms=1
            )
            unit_of_work.defer_until_commit(lambda: callbacks.append("committed"))
            task = asyncio.current_task()
            assert task is not None
            task.cancel()

    result = (await asyncio.gather(asyncio.create_task(owner()), return_exceptions=True))[0]

    assert isinstance(result, asyncio.CancelledError)
    assert observed is not None
    assert observed.transaction_phase is TransactionPhase.ROLLED_BACK
    assert observed.resources_closed
    assert callbacks == []
    assert _player_count(database_runtime.database_path, 1_001) == 0


async def test_cancellation_while_commit_executes_returns_committed_result(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    callbacks: list[str] = []
    observed: SqlAlchemyUnitOfWork | None = None
    original_commit = AsyncSession.commit

    async def delayed_commit(session: AsyncSession) -> None:
        commit_started.set()
        await allow_commit.wait()
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", delayed_commit)

    async def owner() -> str:
        nonlocal observed
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            observed = unit_of_work
            player, player_created = await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=1_002, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player.id,
                created_at_ms=1,
                player_was_created=player_created,
            )
            unit_of_work.defer_until_commit(lambda: callbacks.append("committed"))
        return "committed-result"

    task = asyncio.create_task(owner())
    await commit_started.wait()
    task.cancel()
    allow_commit.set()

    assert await task == "committed-result"
    assert observed is not None
    assert observed.transaction_phase is TransactionPhase.COMMITTED
    assert observed.resources_closed
    assert callbacks == ["committed"]
    assert _player_count(database_runtime.database_path, 1_002) == 1


async def test_cancellation_after_sqlite_commit_before_await_returns_preserves_outcome(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_committed = asyncio.Event()
    allow_return = asyncio.Event()
    callbacks: list[str] = []
    observed: SqlAlchemyUnitOfWork | None = None
    original_commit = AsyncSession.commit

    async def committed_then_delayed(session: AsyncSession) -> None:
        await original_commit(session)
        sqlite_committed.set()
        await allow_return.wait()

    monkeypatch.setattr(AsyncSession, "commit", committed_then_delayed)

    async def owner() -> str:
        nonlocal observed
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            observed = unit_of_work
            player, player_created = await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=1_003, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player.id,
                created_at_ms=1,
                player_was_created=player_created,
            )
            unit_of_work.defer_until_commit(lambda: callbacks.append("committed"))
        return "stable-outcome"

    task = asyncio.create_task(owner())
    await sqlite_committed.wait()
    assert _player_count(database_runtime.database_path, 1_003) == 1
    task.cancel()
    allow_return.set()

    assert await task == "stable-outcome"
    assert observed is not None
    assert observed.transaction_phase is TransactionPhase.COMMITTED
    assert observed.resources_closed
    assert callbacks == ["committed"]


async def test_cancellation_immediately_after_commit_and_during_callbacks_is_suppressed(
    database_runtime: DatabaseRuntime,
) -> None:
    callbacks: list[str] = []

    def cancel_owner_after_commit() -> None:
        callbacks.append("first")
        task = asyncio.current_task()
        assert task is not None
        task.cancel()

    async def owner() -> str:
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            player, player_created = await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=1_004, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player.id,
                created_at_ms=1,
                player_was_created=player_created,
            )
            unit_of_work.defer_until_commit(cancel_owner_after_commit)
            unit_of_work.defer_until_commit(lambda: callbacks.append("second"))
        return "committed-result"

    assert await asyncio.create_task(owner()) == "committed-result"
    assert callbacks == ["first", "second"]
    assert _player_count(database_runtime.database_path, 1_004) == 1


async def test_cancelled_post_commit_callback_does_not_skip_later_telemetry(
    database_runtime: DatabaseRuntime,
) -> None:
    callbacks: list[str] = []

    def cancelled_callback() -> None:
        callbacks.append("cancelled")
        raise asyncio.CancelledError

    async with database_runtime.unit_of_work_factory() as unit_of_work:
        player, player_created = await unit_of_work.players.create_if_absent(
            player_id=uuid4(), discord_user_id=1_005, created_at_ms=1
        )
        await unit_of_work.accounts.create_wallet_if_absent(
            account_id=uuid4(),
            player_id=player.id,
            created_at_ms=1,
            player_was_created=player_created,
        )
        unit_of_work.defer_until_commit(cancelled_callback)
        unit_of_work.defer_until_commit(lambda: callbacks.append("recorded"))

    assert callbacks == ["cancelled", "recorded"]
    assert _player_count(database_runtime.database_path, 1_005) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"items": (1, 2)},
        {1: "not-a-string-key"},
        {"number": float("nan")},
        {"number": float("inf")},
    ],
)
async def test_transport_persistence_rejects_payloads_that_do_not_round_trip_canonically(
    database_runtime: DatabaseRuntime,
    payload: object,
) -> None:
    coordinator = TransportIdempotencyCoordinator(RetentionRegistry({"operations.test": 10}))
    request = TransportRequest(
        namespace="operations.test",
        transport_key="invalid-outcome",
        actor=TransportActor("discord_user", "1"),
        semantic_input={},
    )

    async def invalid_outcome() -> StableOutcome:
        return StableOutcome.success(
            "test.applied",
            cast("Mapping[str, JsonValue]", payload),
        )

    with pytest.raises(InvalidStableOutcome):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await coordinator.execute(
                unit_of_work,
                request,
                completed_at_ms=1,
                operation=invalid_outcome,
            )

    connection = sqlite3.connect(database_runtime.database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM operations_transport_requests"
        ).fetchone() == (0,)
    finally:
        connection.close()


async def test_repository_itself_rejects_noncanonical_outcome_values(
    database_runtime: DatabaseRuntime,
) -> None:
    invalid_payload = cast("Mapping[str, JsonValue]", {"items": (1, 2)})

    with pytest.raises(InvalidStableOutcome):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            claim = await unit_of_work.transport_requests.claim(
                request_id=uuid4(),
                namespace="operations.test",
                transport_key="repository-invalid-outcome",
                actor=TransportActor("discord_user", "1"),
                request_fingerprint="f" * 64,
            )
            await unit_of_work.transport_requests.complete(
                request_id=claim.request_id,
                outcome=StableOutcome.success("test.applied", invalid_payload),
                completed_at_ms=1,
                retain_until_ms=2,
            )


@pytest.mark.parametrize(
    "payload",
    [
        '{"duplicate":1,"duplicate":2}',
        '{"number":1e400}',
        '{"z":1, "a":2}',
        '{"number":' + ("1" * 5_000) + "}",
    ],
)
async def test_offline_verifier_rejects_ambiguous_nonfinite_or_noncanonical_outcomes(
    migrated_database: Path,
    payload: str,
) -> None:
    _insert_bypassed_transport_outcome(migrated_database, payload, key="readiness-corrupt")

    runtime = await create_database_runtime(migrated_database)
    try:
        with pytest.raises(HistoricalVerificationError) as caught:
            await verify_historical_persistence(runtime.engine)
        assert caught.value.category == "invalid_transport_request"
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


@pytest.mark.parametrize(
    "payload",
    [
        '{"duplicate":1,"duplicate":2}',
        '{"number":1e400}',
        '{"z":1, "a":2}',
        '{"number":' + ("1" * 5_000) + "}",
    ],
)
async def test_replay_rejects_post_startup_noncanonical_outcome_corruption(
    database_runtime: DatabaseRuntime,
    payload: str,
) -> None:
    _insert_bypassed_transport_outcome(
        database_runtime.database_path,
        payload,
        key="replay-corrupt",
    )

    with pytest.raises(CorruptTransportOutcome):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await unit_of_work.transport_requests.claim(
                request_id=uuid4(),
                namespace="operations.test",
                transport_key="replay-corrupt",
                actor=TransportActor("discord_user", "1"),
                request_fingerprint="f" * 64,
            )


async def test_post_commit_confirmation_failure_preserves_commit_and_disables_mutations(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_main_path: Callable[[AsyncConnection], Awaitable[str]] = (
        SqlAlchemyUnitOfWork._connection_main_path  # pyright: ignore[reportPrivateUsage]
    )
    confirmations = 0
    callbacks: list[str] = []

    async def fail_post_commit_confirmation(connection: AsyncConnection) -> str:
        nonlocal confirmations
        confirmations += 1
        if confirmations == 2:
            raise RuntimeError("post-commit confirmation unavailable")
        return await original_main_path(connection)

    monkeypatch.setattr(
        SqlAlchemyUnitOfWork,
        "_connection_main_path",
        staticmethod(fail_post_commit_confirmation),
    )

    async with database_runtime.unit_of_work_factory() as unit_of_work:
        player, player_created = await unit_of_work.players.create_if_absent(
            player_id=uuid4(), discord_user_id=1_006, created_at_ms=1
        )
        await unit_of_work.accounts.create_wallet_if_absent(
            account_id=uuid4(),
            player_id=player.id,
            created_at_ms=1,
            player_was_created=player_created,
        )
        unit_of_work.defer_until_commit(lambda: callbacks.append("committed"))

    assert _player_count(database_runtime.database_path, 1_006) == 1
    assert callbacks == ["committed"]
    assert database_runtime.storage_monitor.is_safe() is False


async def test_committed_cleanup_failure_preserves_result_callbacks_and_lifecycle(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import unit_of_work as unit_of_work_module

    operational_errors: list[str] = []

    def record_operational_error(message: str, *args: object, **kwargs: object) -> None:
        del args, kwargs
        operational_errors.append(message)

    monkeypatch.setattr(unit_of_work_module.logger, "error", record_operational_error)
    runtime = await create_database_runtime(migrated_database)
    original_close = AsyncSession.close
    close_calls = 0
    callbacks: list[str] = []
    observed: SqlAlchemyUnitOfWork | None = None

    async def fail_first_close(session: AsyncSession) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeError("session cleanup failed")
        await original_close(session)

    monkeypatch.setattr(AsyncSession, "close", fail_first_close)

    async def owner() -> str:
        nonlocal observed
        async with runtime.unit_of_work_factory() as unit_of_work:
            observed = unit_of_work
            player, player_created = await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=1_007, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player.id,
                created_at_ms=1,
                player_was_created=player_created,
            )
            unit_of_work.defer_until_commit(lambda: callbacks.append("committed"))
        return "committed-result"

    try:
        assert await owner() == "committed-result"
        assert observed is not None
        assert observed.transaction_phase is TransactionPhase.COMMITTED
        assert observed.cleanup_failed is True
        assert observed.resources_closed is False
        assert callbacks == ["committed"]
        assert _player_count(migrated_database, 1_007) == 1
        assert runtime.storage_monitor.is_safe() is False
        assert any("resource cleanup failed" in message for message in operational_errors)

    finally:
        await runtime.close(drain_timeout_seconds=0.1)
    assert observed.resources_closed


async def test_cleanup_failure_does_not_replace_the_body_failure(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original_close = AsyncSession.close
    close_calls = 0

    class BodyFailure(RuntimeError):
        pass

    async def fail_first_close(session: AsyncSession) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeError("session cleanup failed")
        await original_close(session)

    monkeypatch.setattr(AsyncSession, "close", fail_first_close)
    try:
        with pytest.raises(BodyFailure):
            async with runtime.unit_of_work_factory():
                raise BodyFailure("primary business failure")
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


@pytest.mark.parametrize(
    ("fail_session", "fail_connection"),
    [(True, False), (False, True), (True, True)],
)
async def test_failed_resources_remain_tracked_until_shutdown_retry_succeeds(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_session: bool,
    fail_connection: bool,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original_session_close = AsyncSession.close
    original_connection_close = AsyncConnection.close
    session_failures = 1 if fail_session else 0
    connection_failures = 1 if fail_connection else 0
    observed: SqlAlchemyUnitOfWork | None = None

    async def flaky_session_close(session: AsyncSession) -> None:
        nonlocal session_failures
        if session_failures:
            session_failures -= 1
            raise RuntimeError("session close failed")
        await original_session_close(session)

    async def flaky_connection_close(connection: AsyncConnection) -> None:
        nonlocal connection_failures
        if connection_failures:
            connection_failures -= 1
            raise RuntimeError("connection close failed")
        await original_connection_close(connection)

    monkeypatch.setattr(AsyncSession, "close", flaky_session_close)
    monkeypatch.setattr(AsyncConnection, "close", flaky_connection_close)

    async def commit() -> str:
        nonlocal observed
        async with runtime.unit_of_work_factory() as unit_of_work:
            observed = unit_of_work
            player, player_created = await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=1_008, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player.id,
                created_at_ms=1,
                player_was_created=player_created,
            )
        return "committed"

    assert await commit() == "committed"
    assert observed is not None
    assert observed.cleanup_failed is True
    assert observed.resources_closed is False

    await runtime.close(drain_timeout_seconds=0.1)
    assert observed.resources_closed is True


async def test_rolled_back_uow_cleanup_failure_is_retained_for_shutdown(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original_close = AsyncSession.close
    fail_close = True
    observed: SqlAlchemyUnitOfWork | None = None

    async def flaky_close(session: AsyncSession) -> None:
        nonlocal fail_close
        if fail_close:
            fail_close = False
            raise RuntimeError("session close failed")
        await original_close(session)

    monkeypatch.setattr(AsyncSession, "close", flaky_close)

    class BodyFailure(RuntimeError):
        pass

    with pytest.raises(BodyFailure):
        async with runtime.unit_of_work_factory() as unit_of_work:
            observed = unit_of_work
            raise BodyFailure("rollback")

    assert observed is not None
    assert observed.transaction_phase is TransactionPhase.ROLLED_BACK
    assert observed.resources_closed is False
    await runtime.close(drain_timeout_seconds=0.1)
    assert observed.resources_closed is True


async def test_repeated_cleanup_failure_keeps_process_ownership_until_later_retry(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original_close = AsyncConnection.close
    allow_close = False

    async def controlled_close(connection: AsyncConnection) -> None:
        if not allow_close:
            raise RuntimeError("connection remains usable")
        await original_close(connection)

    monkeypatch.setattr(AsyncConnection, "close", controlled_close)
    async with runtime.unit_of_work_factory():
        pass

    for _ in range(2):
        with pytest.raises(ShutdownIncomplete, match="resources remain usable"):
            await runtime.close(drain_timeout_seconds=0.01)
        _assert_lock_held(migrated_database)

    allow_close = True
    await runtime.close(drain_timeout_seconds=0.1)


async def test_successor_cannot_acquire_until_every_old_connection_is_unusable(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original_close = AsyncConnection.close
    allow_close = False
    failed_connections: list[AsyncConnection] = []

    async def controlled_close(connection: AsyncConnection) -> None:
        if not allow_close:
            failed_connections.append(connection)
            raise RuntimeError("connection remains usable")
        await original_close(connection)

    monkeypatch.setattr(AsyncConnection, "close", controlled_close)
    async with runtime.unit_of_work_factory() as unit_of_work:
        player, player_created = await unit_of_work.players.create_if_absent(
            player_id=uuid4(), discord_user_id=1_009, created_at_ms=1
        )
        await unit_of_work.accounts.create_wallet_if_absent(
            account_id=uuid4(),
            player_id=player.id,
            created_at_ms=1,
            player_was_created=player_created,
        )

    assert len(failed_connections) == 1
    old_connection = failed_connections[0]
    assert (await old_connection.exec_driver_sql("SELECT 1")).scalar_one() == 1
    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "process_lock_unavailable"
    assert (await old_connection.exec_driver_sql("SELECT 1")).scalar_one() == 1

    allow_close = True
    await runtime.close(drain_timeout_seconds=0.1)
    assert old_connection.closed
    successor = await create_database_runtime(migrated_database)
    await successor.close(drain_timeout_seconds=0.1)


async def test_caller_cancellation_during_unresolved_cleanup_cannot_release_ownership(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original_close = AsyncSession.close
    cleanup_retry_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    close_calls = 0

    async def controlled_close(session: AsyncSession) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeError("initial session cleanup failed")
        cleanup_retry_started.set()
        await allow_cleanup.wait()
        await original_close(session)

    monkeypatch.setattr(AsyncSession, "close", controlled_close)
    async with runtime.unit_of_work_factory():
        pass

    closing = asyncio.create_task(runtime.close(drain_timeout_seconds=0.1))
    await cleanup_retry_started.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    _assert_lock_held(migrated_database)

    allow_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    replacement = DatabaseProcessLock(migrated_database.parent / ".butterbot-process.lock")
    replacement.acquire()
    replacement.release()


@pytest.mark.parametrize("payload", ["not-json", "null", "1", '"scalar"', "[]"])
def test_completed_transport_payload_requires_a_json_object(
    migrated_database: Path,
    payload: str,
) -> None:
    connection = sqlite3.connect(migrated_database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO operations_transport_requests"
                "(id, namespace, transport_key, actor_kind, actor_reference, "
                "request_fingerprint, outcome_kind, outcome_code, outcome_payload, "
                "completed_at_ms, retain_until_ms) VALUES "
                "(?, 'operations.test', 'key', 'discord_user', '1', ?, "
                "'success', 'test.applied', ?, 1, 2)",
                (uuid4().hex, "f" * 64, payload),
            )
    finally:
        connection.close()


@pytest.mark.parametrize("payload", ["not-json", "null", "1", "[]"])
async def test_offline_verifier_rejects_malformed_committed_transport_payload(
    migrated_database: Path,
    payload: str,
) -> None:
    connection = sqlite3.connect(migrated_database)
    connection.execute("PRAGMA ignore_check_constraints=ON")
    connection.execute(
        "INSERT INTO operations_transport_requests"
        "(id, namespace, transport_key, actor_kind, actor_reference, request_fingerprint, "
        "outcome_kind, outcome_code, outcome_payload, completed_at_ms, retain_until_ms) "
        "VALUES (?, 'operations.test', 'key', 'discord_user', '1', ?, "
        "'success', 'test.applied', ?, 1, 2)",
        (uuid4().hex, "f" * 64, payload),
    )
    connection.commit()
    connection.close()

    runtime = await create_database_runtime(migrated_database)
    try:
        with pytest.raises(HistoricalVerificationError) as caught:
            await verify_historical_persistence(runtime.engine)
        assert caught.value.category in {"corrupt_database", "invalid_persisted_state"}
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


@pytest.mark.parametrize(
    ("table", "column", "setup"),
    [
        ("players", "id", "player"),
        ("operations_transport_requests", "id", "transport"),
        ("economy_accounts", "id", "account"),
        ("economy_accounts", "player_id", "account"),
        ("economy_account_balances", "account_id", "balance"),
        ("economy_ledger_transactions", "id", "transaction"),
        ("economy_ledger_transactions", "correlation_id", "transaction"),
        ("economy_ledger_transactions", "transport_request_id", "transaction"),
        ("economy_ledger_postings", "transaction_id", "posting"),
        ("economy_ledger_postings", "account_id", "posting"),
    ],
)
def test_sqlite_uuid_columns_reject_malformed_storage(
    migrated_database: Path,
    table: str,
    column: str,
    setup: str,
) -> None:
    ids = _seed_exact_state(migrated_database)
    connection = sqlite3.connect(migrated_database)
    try:
        if (setup == "transaction" and column == "transport_request_id") or setup == "posting":
            target = ids["transaction"]
        else:
            target = ids["account" if setup == "balance" else setup]
        key_column = {
            "players": "id",
            "operations_transport_requests": "id",
            "economy_accounts": "id",
            "economy_account_balances": "account_id",
            "economy_ledger_transactions": "id",
            "economy_ledger_postings": "transaction_id",
        }[table]
        with pytest.raises(sqlite3.IntegrityError, match="CHECK|aggregate identity is immutable"):
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {key_column} = ?",
                ("not-a-uuid", target),
            )
    finally:
        connection.close()


async def test_offline_verifier_rejects_malformed_uuid_even_if_checks_were_bypassed(
    migrated_database: Path,
) -> None:
    _seed_exact_state(migrated_database)
    connection = sqlite3.connect(migrated_database)
    connection.execute("PRAGMA ignore_check_constraints=ON")
    connection.execute("UPDATE operations_transport_requests SET id = 'malformed'")
    connection.commit()
    connection.close()

    runtime = await create_database_runtime(migrated_database)
    try:
        with pytest.raises(HistoricalVerificationError) as caught:
            await verify_historical_persistence(runtime.engine)
        assert caught.value.category in {"corrupt_database", "invalid_persisted_state"}
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


async def test_replay_wraps_parser_failures_from_post_startup_external_corruption(
    database_runtime: DatabaseRuntime,
) -> None:
    request_id = uuid4()
    connection = sqlite3.connect(database_runtime.database_path)
    connection.execute("PRAGMA ignore_check_constraints=ON")
    connection.execute(
        "INSERT INTO operations_transport_requests"
        "(id, namespace, transport_key, actor_kind, actor_reference, request_fingerprint, "
        "outcome_kind, outcome_code, outcome_payload, completed_at_ms, retain_until_ms) "
        "VALUES (?, 'operations.test', 'corrupt', 'discord_user', '1', ?, "
        "'success', 'test.applied', 'not-json', 1, 2)",
        (request_id.hex, "f" * 64),
    )
    connection.commit()
    connection.close()

    with pytest.raises(CorruptTransportOutcome) as caught:
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await unit_of_work.transport_requests.claim(
                request_id=uuid4(),
                namespace="operations.test",
                transport_key="corrupt",
                actor=TransportActor("discord_user", "1"),
                request_fingerprint="f" * 64,
            )
    assert not isinstance(caught.value, ValueError)


@pytest.mark.parametrize(
    ("table", "column", "target_key"),
    [
        ("players", "discord_user_id", "player"),
        ("players", "created_at_ms", "player"),
        ("economy_accounts", "created_at_ms", "account"),
        ("operations_transport_requests", "completed_at_ms", "transport"),
        ("operations_transport_requests", "retain_until_ms", "transport"),
        ("economy_account_balances", "amount", "account"),
        ("economy_account_balances", "version", "account"),
        ("economy_ledger_transactions", "committed_at_ms", "transaction"),
        ("economy_ledger_transactions", "discord_interaction_id", "transaction"),
        ("economy_ledger_postings", "amount", "transaction"),
    ],
)
@pytest.mark.parametrize("value", [1.5, 1e20])
def test_sqlite_exact_integer_columns_reject_real_storage(
    migrated_database: Path,
    table: str,
    column: str,
    target_key: str,
    value: float,
) -> None:
    ids = _seed_exact_state(migrated_database)
    key_column = {
        "players": "id",
        "economy_accounts": "id",
        "operations_transport_requests": "id",
        "economy_account_balances": "account_id",
        "economy_ledger_transactions": "id",
        "economy_ledger_postings": "transaction_id",
    }[table]
    connection = sqlite3.connect(migrated_database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK|aggregate identity is immutable"):
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {key_column} = ?",
                (value, ids[target_key]),
            )
    finally:
        connection.close()


def test_sqlite_exact_integer_boundaries_and_out_of_range_literals(
    migrated_database: Path,
) -> None:
    ids = _seed_exact_state(migrated_database)
    connection = sqlite3.connect(migrated_database)
    try:
        connection.execute(
            "UPDATE economy_account_balances SET amount = ? WHERE account_id = ?",
            (INT64_MAX, ids["account"]),
        )
        connection.execute(
            "UPDATE economy_ledger_postings SET amount = ? WHERE transaction_id = ?",
            (INT64_MIN, ids["transaction"]),
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "UPDATE economy_account_balances SET amount = 9223372036854775808 "
                "WHERE account_id = ?",
                (ids["account"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "UPDATE economy_ledger_postings SET amount = -9223372036854775809 "
                "WHERE transaction_id = ?",
                (ids["transaction"],),
            )
    finally:
        connection.close()


async def test_application_integer_boundaries_reject_whole_mutation(
    database_runtime: DatabaseRuntime,
) -> None:
    with pytest.raises(ExactIntegerOutOfRange):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=INT64_MAX + 1, created_at_ms=1
            )
    with pytest.raises(ExactIntegerOutOfRange):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=2_001, created_at_ms=-1
            )
    assert _player_count(database_runtime.database_path, 2_001) == 0


def test_checked_posting_arithmetic_rejects_overflow_and_underflow() -> None:
    assert checked_add_int64(INT64_MAX - 1, 1, "balance") == INT64_MAX
    assert checked_add_int64(INT64_MIN + 1, -1, "posting") == INT64_MIN
    with pytest.raises(ExactIntegerOutOfRange):
        checked_add_int64(INT64_MAX, 1, "balance")
    with pytest.raises(ExactIntegerOutOfRange):
        checked_add_int64(INT64_MIN, -1, "posting")
    with pytest.raises(ExactIntegerOutOfRange):
        RetentionRegistry({"operations.test": 1}).retain_until_ms("operations.test", INT64_MAX)


async def test_stuck_monitor_shutdown_is_bounded_and_retains_ownership(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    allow_monitor = asyncio.Event()

    async def stuck_close() -> None:
        await allow_monitor.wait()

    monkeypatch.setattr(runtime.storage_monitor, "close", stuck_close)
    started = time.perf_counter()
    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    assert time.perf_counter() - started < 1.5
    _assert_lock_held(migrated_database)

    allow_monitor.set()
    await runtime.close(drain_timeout_seconds=0.1)


async def test_stuck_monitor_does_not_prevent_active_owner_drain(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    allow_monitor = asyncio.Event()
    entered = asyncio.Event()

    async def stuck_close() -> None:
        await allow_monitor.wait()

    async def owner() -> None:
        async with runtime.unit_of_work_factory():
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(runtime.storage_monitor, "close", stuck_close)
    owner_task = asyncio.create_task(owner())
    await entered.wait()
    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    assert owner_task.done()
    assert isinstance(
        (await asyncio.gather(owner_task, return_exceptions=True))[0], asyncio.CancelledError
    )
    _assert_lock_held(migrated_database)

    allow_monitor.set()
    await runtime.close(drain_timeout_seconds=0.1)


async def test_monitor_failure_waits_for_transaction_drain_and_fail_stops(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    entered = asyncio.Event()
    owner_finished = asyncio.Event()
    original_close = runtime.storage_monitor.close

    async def failed_close() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("monitor shutdown failed")

    async def owner() -> None:
        try:
            async with runtime.unit_of_work_factory():
                entered.set()
                await asyncio.Event().wait()
        finally:
            owner_finished.set()

    monkeypatch.setattr(runtime.storage_monitor, "close", failed_close)
    owner_task = asyncio.create_task(owner())
    await entered.wait()
    with pytest.raises(ShutdownIncomplete, match="storage-monitor"):
        await runtime.close(drain_timeout_seconds=0.01)
    assert owner_finished.is_set()
    _assert_lock_held(migrated_database)
    await asyncio.gather(owner_task, return_exceptions=True)
    monkeypatch.setattr(runtime.storage_monitor, "close", original_close)
    await runtime.close(drain_timeout_seconds=0.1)


async def test_stuck_monitor_does_not_prevent_waiting_writer_drain(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    allow_monitor = asyncio.Event()

    async def stuck_close() -> None:
        await allow_monitor.wait()

    async def owner() -> None:
        async with runtime.unit_of_work_factory():
            await asyncio.Event().wait()

    monkeypatch.setattr(runtime.storage_monitor, "close", stuck_close)
    owners = [asyncio.create_task(owner()) for _ in range(5)]
    await asyncio.sleep(0.05)
    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    results = await asyncio.gather(*owners, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    _assert_lock_held(migrated_database)

    allow_monitor.set()
    await runtime.close(drain_timeout_seconds=0.1)


async def test_caller_cancellation_cannot_bypass_stuck_monitor_shutdown(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    monitor_started = asyncio.Event()
    allow_monitor = asyncio.Event()

    async def stuck_close() -> None:
        monitor_started.set()
        await allow_monitor.wait()

    monkeypatch.setattr(runtime.storage_monitor, "close", stuck_close)
    closing = asyncio.create_task(runtime.close(drain_timeout_seconds=0.1))
    await monitor_started.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    _assert_lock_held(migrated_database)

    allow_monitor.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    replacement = DatabaseProcessLock(migrated_database.parent / ".butterbot-process.lock")
    replacement.acquire()
    replacement.release()


async def test_shutdown_retry_retains_original_post_transaction_owner_capture(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    entered = asyncio.Event()
    leave_transaction = asyncio.Event()
    transaction_exited = asyncio.Event()
    cancellation_observed = asyncio.Event()
    finish_owner = asyncio.Event()

    async def owner() -> None:
        async with runtime.unit_of_work_factory():
            entered.set()
            await leave_transaction.wait()
        transaction_exited.set()
        while not finish_owner.is_set():
            try:
                await finish_owner.wait()
            except asyncio.CancelledError:
                cancellation_observed.set()

    owner_task = asyncio.create_task(owner())
    await entered.wait()
    first_close = asyncio.create_task(runtime.close(drain_timeout_seconds=0.01))
    await asyncio.sleep(0)
    leave_transaction.set()
    await transaction_exited.wait()

    with pytest.raises(ShutdownIncomplete):
        await first_close
    assert cancellation_observed.is_set()
    _assert_lock_held(migrated_database)

    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    assert not owner_task.done()
    _assert_lock_held(migrated_database)

    finish_owner.set()
    await owner_task
    await runtime.close(drain_timeout_seconds=0.1)


async def test_shutdown_retry_cannot_orphan_timed_out_monitor_cleanup(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    monitor_started = asyncio.Event()
    release_monitor = asyncio.Event()
    original_close = runtime.storage_monitor.close

    async def stuck_close() -> None:
        monitor_started.set()
        await release_monitor.wait()
        await original_close()

    monkeypatch.setattr(runtime.storage_monitor, "close", stuck_close)
    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    assert monitor_started.is_set()
    _assert_lock_held(migrated_database)

    monkeypatch.setattr(runtime.storage_monitor, "close", original_close)
    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    _assert_lock_held(migrated_database)

    release_monitor.set()
    await runtime.close(drain_timeout_seconds=0.1)


async def test_engine_disposal_failure_retains_ownership_until_successful_retry(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original_dispose = AsyncEngine.dispose
    dispose_calls = 0

    async def fail_first_dispose(engine: AsyncEngine, *, close: bool = True) -> None:
        nonlocal dispose_calls
        dispose_calls += 1
        if engine is runtime.engine and dispose_calls == 1:
            raise RuntimeError("engine disposal failed")
        await original_dispose(engine, close=close)

    monkeypatch.setattr(AsyncEngine, "dispose", fail_first_dispose)

    with pytest.raises(ShutdownIncomplete, match="engine disposal"):
        await runtime.close(drain_timeout_seconds=0.1)
    _assert_lock_held(migrated_database)

    await runtime.close(drain_timeout_seconds=0.1)


async def test_engine_disposal_timeout_is_bounded_and_retains_ownership(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import database as database_module

    runtime = await create_database_runtime(migrated_database)
    original_dispose = AsyncEngine.dispose

    async def stuck_dispose(engine: AsyncEngine, *, close: bool = True) -> None:
        del engine, close
        await asyncio.Event().wait()

    monkeypatch.setattr(database_module, "ENGINE_DISPOSAL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(AsyncEngine, "dispose", stuck_dispose)
    with pytest.raises(ShutdownIncomplete, match="engine disposal"):
        await runtime.close(drain_timeout_seconds=0.1)
    _assert_lock_held(migrated_database)

    monkeypatch.setattr(AsyncEngine, "dispose", original_dispose)
    await runtime.close(drain_timeout_seconds=0.1)


class _TransitionTelemetry(NullOperationsTelemetry):
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts: list[tuple[bool, str]] = []
        self.recorded: list[tuple[bool, str]] = []

    def database_storage(
        self,
        *,
        snapshot: DatabaseStorageSnapshot,
        outcome: str,
        error_category: str | None,
    ) -> None:
        del snapshot, outcome, error_category

    def mutations_state(self, *, enabled: bool, reason: str) -> None:
        event = (enabled, reason)
        self.attempts.append(event)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("transition telemetry failed")
        self.recorded.append(event)


class _ExplodingStorageTelemetry(NullOperationsTelemetry):
    def database_storage(
        self,
        *,
        snapshot: DatabaseStorageSnapshot,
        outcome: str,
        error_category: str | None,
    ) -> None:
        del snapshot, outcome, error_category
        raise RuntimeError("storage telemetry failed")

    def mutations_state(self, *, enabled: bool, reason: str) -> None:
        del enabled, reason
        raise RuntimeError("mutation telemetry failed")


async def test_telemetry_failures_do_not_replace_primary_identity_failure(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(
        migrated_database,
        telemetry=_ExplodingStorageTelemetry(),
    )
    alias = migrated_database.with_name("identity-alias.sqlite3")
    os.link(migrated_database, alias)
    try:
        with pytest.raises(DatabaseIdentityMismatch):
            async with runtime.unit_of_work_factory():
                pass
        assert runtime.storage_monitor.is_safe() is False
    finally:
        alias.unlink()
        await runtime.close(drain_timeout_seconds=0.1)


async def test_post_commit_cleanup_reporting_failure_preserves_result_and_fail_stop(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(
        migrated_database,
        telemetry=_ExplodingStorageTelemetry(),
    )
    original_close = AsyncSession.close
    allow_close = False

    async def controlled_close(session: AsyncSession) -> None:
        if not allow_close:
            raise RuntimeError("session remains unresolved")
        await original_close(session)

    monkeypatch.setattr(AsyncSession, "close", controlled_close)

    async def owner() -> str:
        async with runtime.unit_of_work_factory() as unit_of_work:
            player, player_created = await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=1_010, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player.id,
                created_at_ms=1,
                player_was_created=player_created,
            )
        return "committed-result"

    assert await owner() == "committed-result"
    assert _player_count(migrated_database, 1_010) == 1
    assert runtime.storage_monitor.is_safe() is False
    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)
    _assert_lock_held(migrated_database)

    allow_close = True
    await runtime.close(drain_timeout_seconds=0.1)


async def test_failed_mutation_transition_retries_without_losing_state(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import storage_monitor as monitor_module

    runtime = await create_database_runtime(migrated_database)
    await runtime.storage_monitor.close()
    telemetry = _TransitionTelemetry(failures=2)
    contract = DatabaseStorageContract(runtime.database_path.parent)
    monitor = DatabaseStorageMonitor(
        storage=validate_database_storage(runtime.database_path, contract),
        contract=contract,
        engine=runtime.engine,
        telemetry=telemetry,
        configured_mutations_enabled=True,
    )
    original_validate = monitor_module.validate_database_storage

    def unsafe(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("unsafe sample")

    monkeypatch.setattr(monitor_module, "validate_database_storage", unsafe)
    await monitor.sample()
    await monitor.sample()
    await monitor.sample()
    assert monitor.is_safe() is False
    assert telemetry.attempts == [(False, "runtime_storage_unsafe")] * 3
    assert telemetry.recorded == [(False, "runtime_storage_unsafe")]

    monkeypatch.setattr(monitor_module, "validate_database_storage", original_validate)
    await monitor.sample()
    assert telemetry.recorded[-1] == (True, "enabled")

    monkeypatch.setattr(monitor_module, "validate_database_storage", unsafe)
    await monitor.sample()
    await monitor.sample()
    assert telemetry.recorded[-1] == (False, "runtime_storage_unsafe")
    assert telemetry.attempts[-1] == (False, "runtime_storage_unsafe")
    await runtime.close(drain_timeout_seconds=0.1)


async def test_failed_unsafe_transition_then_immediate_recovery_emits_both_in_order(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import storage_monitor as monitor_module

    runtime = await create_database_runtime(migrated_database)
    await runtime.storage_monitor.close()
    telemetry = _TransitionTelemetry(failures=1)
    contract = DatabaseStorageContract(runtime.database_path.parent)
    monitor = DatabaseStorageMonitor(
        storage=validate_database_storage(runtime.database_path, contract),
        contract=contract,
        engine=runtime.engine,
        telemetry=telemetry,
        configured_mutations_enabled=True,
    )
    original_validate = monitor_module.validate_database_storage

    def unsafe(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("unsafe sample")

    monkeypatch.setattr(monitor_module, "validate_database_storage", unsafe)
    await monitor.sample()
    monkeypatch.setattr(monitor_module, "validate_database_storage", original_validate)
    await monitor.sample()

    assert telemetry.recorded == [
        (False, "runtime_storage_unsafe"),
        (True, "enabled"),
    ]
    assert telemetry.attempts == [
        (False, "runtime_storage_unsafe"),
        (False, "runtime_storage_unsafe"),
        (True, "enabled"),
    ]
    await runtime.close(drain_timeout_seconds=0.1)


async def test_unsafe_safe_unsafe_transitions_remain_ordered_while_emission_pending(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import storage_monitor as monitor_module

    runtime = await create_database_runtime(migrated_database)
    await runtime.storage_monitor.close()
    telemetry = _TransitionTelemetry(failures=2)
    contract = DatabaseStorageContract(runtime.database_path.parent)
    monitor = DatabaseStorageMonitor(
        storage=validate_database_storage(runtime.database_path, contract),
        contract=contract,
        engine=runtime.engine,
        telemetry=telemetry,
        configured_mutations_enabled=True,
    )
    original_validate = monitor_module.validate_database_storage

    def unsafe(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("unsafe sample")

    monkeypatch.setattr(monitor_module, "validate_database_storage", unsafe)
    await monitor.sample()
    monkeypatch.setattr(monitor_module, "validate_database_storage", original_validate)
    await monitor.sample()
    monkeypatch.setattr(monitor_module, "validate_database_storage", unsafe)
    await monitor.sample()
    await monitor.sample()

    assert telemetry.recorded == [
        (False, "runtime_storage_unsafe"),
        (True, "enabled"),
        (False, "runtime_storage_unsafe"),
    ]
    assert telemetry.recorded.count((False, "runtime_storage_unsafe")) == 2
    await runtime.close(drain_timeout_seconds=0.1)


def _seed_exact_state(database: Path) -> dict[str, str]:
    ids = {
        "player": uuid4().hex,
        "account": uuid4().hex,
        "transaction": uuid4().hex,
        "correlation": uuid4().hex,
        "transport": uuid4().hex,
    }
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        connection.execute(
            "INSERT INTO players(id, discord_user_id, created_at_ms, lifecycle_state) "
            "VALUES (?, 1, 1, 'active')",
            (ids["player"],),
        )
        connection.execute(
            "INSERT INTO economy_accounts"
            "(id, player_id, account_kind, currency_key, system_key, created_at_ms) "
            "VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
            (ids["account"], ids["player"]),
        )
        connection.execute(
            "INSERT INTO economy_account_balances(account_id, account_kind, amount, version) "
            "VALUES (?, 'wallet', 1, 0)",
            (ids["account"],),
        )
        connection.execute(
            "INSERT INTO operations_transport_requests"
            "(id, namespace, transport_key, actor_kind, actor_reference, request_fingerprint, "
            "outcome_kind, outcome_code, outcome_payload, completed_at_ms, retain_until_ms) "
            "VALUES (?, 'operations.test', 'key', 'discord_user', '1', ?, "
            "'success', 'test.applied', '{}', 1, 2)",
            (ids["transport"], "f" * 64),
        )
        connection.execute(
            "INSERT INTO economy_ledger_transactions"
            "(id, transaction_kind, committed_at_ms, actor_kind, actor_reference, reason_code, "
            "correlation_id, transport_request_id, discord_interaction_id) "
            "VALUES (?, 'test', 1, 'system', 'test', 'test.reason', ?, ?, 1)",
            (ids["transaction"], ids["correlation"], ids["transport"]),
        )
        connection.execute(
            "INSERT INTO economy_ledger_postings(transaction_id, account_id, amount) "
            "VALUES (?, ?, 1)",
            (ids["transaction"], ids["account"]),
        )
        connection.commit()
    finally:
        connection.close()
    return ids


def _insert_bypassed_transport_outcome(database: Path, payload: str, *, key: str) -> None:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA ignore_check_constraints=ON")
    try:
        connection.execute(
            "INSERT INTO operations_transport_requests"
            "(id, namespace, transport_key, actor_kind, actor_reference, request_fingerprint, "
            "outcome_kind, outcome_code, outcome_payload, completed_at_ms, retain_until_ms) "
            "VALUES (?, 'operations.test', ?, 'discord_user', '1', ?, "
            "'success', 'test.applied', ?, 1, 2)",
            (uuid4().hex, key, "f" * 64, payload),
        )
        connection.commit()
    finally:
        connection.close()


def _assert_lock_held(database: Path) -> None:
    replacement = DatabaseProcessLock(database.parent / ".butterbot-process.lock")
    with pytest.raises(ProcessLockUnavailable):
        replacement.acquire()
