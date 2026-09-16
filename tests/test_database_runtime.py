from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import aiosqlite
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.application.operations.idempotency import NullOperationsTelemetry
from butterbot.application.operations.mutation_eligibility import GlobalMutationEligibility
from butterbot.application.operations.ports import DatabaseStorageSnapshot
from butterbot.application.transactions import (
    ApplicationTransactionRunner,
    DatabaseRetryExhausted,
    RetryPolicy,
    UnitOfWork,
)
from butterbot.infrastructure.persistence.database import (
    DatabaseRuntime,
    create_database_runtime,
    is_sqlite_busy,
)
from butterbot.infrastructure.persistence.process_lock import (
    DatabaseProcessLock,
    ProcessLockUnavailable,
)
from butterbot.infrastructure.persistence.readiness import (
    EXPECTED_SCHEMA_REVISION,
    DatabaseReadinessError,
    RevisionContract,
)
from butterbot.infrastructure.persistence.storage import (
    DatabaseIdentityMismatch,
    DatabaseStorageContract,
    validate_database_storage,
)
from butterbot.infrastructure.persistence.storage_monitor import DatabaseStorageMonitor
from butterbot.infrastructure.persistence.unit_of_work import (
    ShutdownIncomplete,
    SqlAlchemyUnitOfWork,
    SqlAlchemyUnitOfWorkFactory,
    TransactionPhase,
    UnitOfWorkLifecycle,
    WriterAdmissionTimeout,
)
from butterbot.infrastructure.persistence.verification import (
    HistoricalVerificationError,
    verify_historical_persistence,
)


async def test_runtime_applies_required_pragmas_to_every_connection(
    database_runtime: DatabaseRuntime,
) -> None:
    async with (
        database_runtime.engine.connect() as first,
        database_runtime.engine.connect() as second,
    ):
        for connection in (first, second):
            values = {
                "foreign_keys": await connection.scalar(text("PRAGMA foreign_keys")),
                "journal_mode": await connection.scalar(text("PRAGMA journal_mode")),
                "synchronous": await connection.scalar(text("PRAGMA synchronous")),
                "busy_timeout": await connection.scalar(text("PRAGMA busy_timeout")),
            }
            assert values == {
                "foreign_keys": 1,
                "journal_mode": "wal",
                "synchronous": 2,
                "busy_timeout": 1_000,
            }


async def test_unit_of_work_commits_complete_repository_changes(
    database_runtime: DatabaseRuntime,
) -> None:
    player_id = uuid4()
    account_id = uuid4()
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        _, player_created = await unit_of_work.players.create_if_absent(
            player_id=player_id, discord_user_id=100, created_at_ms=1
        )
        await unit_of_work.accounts.create_wallet_if_absent(
            account_id=account_id,
            player_id=player_id,
            created_at_ms=1,
            player_was_created=player_created,
        )

    async with database_runtime.unit_of_work_factory() as unit_of_work:
        assert await unit_of_work.players.get_by_discord_user_id(100) is not None
        assert await unit_of_work.accounts.get_wallet(player_id) is not None


async def test_repository_changes_do_not_commit_before_application_boundary(
    database_runtime: DatabaseRuntime,
    migrated_database: Path,
) -> None:
    player_id = uuid4()
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        _, player_created = await unit_of_work.players.create_if_absent(
            player_id=player_id, discord_user_id=101, created_at_ms=1
        )
        await unit_of_work.accounts.create_wallet_if_absent(
            account_id=uuid4(),
            player_id=player_id,
            created_at_ms=1,
            player_was_created=player_created,
        )
        reader = sqlite3.connect(migrated_database)
        try:
            visible = reader.execute(
                "SELECT COUNT(*) FROM players WHERE discord_user_id = 101"
            ).fetchone()
        finally:
            reader.close()
        assert visible == (0,)

    reader = sqlite3.connect(migrated_database)
    try:
        visible = reader.execute(
            "SELECT COUNT(*) FROM players WHERE discord_user_id = 101"
        ).fetchone()
    finally:
        reader.close()
    assert visible == (1,)


async def test_unit_of_work_rolls_back_all_repository_changes(
    database_runtime: DatabaseRuntime,
) -> None:
    player_id = uuid4()
    with pytest.raises(RuntimeError, match="injected"):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            _, player_created = await unit_of_work.players.create_if_absent(
                player_id=player_id, discord_user_id=102, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player_id,
                created_at_ms=1,
                player_was_created=player_created,
            )
            raise RuntimeError("injected failure")

    async with database_runtime.unit_of_work_factory() as unit_of_work:
        assert await unit_of_work.players.get_by_discord_user_id(102) is None


async def test_concurrent_account_creation_converges_on_one_player_and_wallet(
    database_runtime: DatabaseRuntime,
) -> None:
    runner = ApplicationTransactionRunner(
        database_runtime.unit_of_work_factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
    )

    async def create_account(unit_of_work: UnitOfWork) -> tuple[UUID, UUID]:
        player, player_created = await unit_of_work.players.create_if_absent(
            player_id=uuid4(), discord_user_id=500, created_at_ms=1
        )
        wallet, _ = await unit_of_work.accounts.create_wallet_if_absent(
            account_id=uuid4(),
            player_id=player.id,
            created_at_ms=1,
            player_was_created=player_created,
        )
        return player.id, wallet.id

    results = await asyncio.gather(
        *(runner.run("players.account_create", create_account) for _ in range(8))
    )

    assert len({player_id for player_id, _ in results}) == 1
    assert len({wallet_id for _, wallet_id in results}) == 1


async def test_missing_database_fails_without_creating_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(missing)

    assert caught.value.category == "missing_database"
    assert not missing.exists()


async def test_missing_schema_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.close()

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(database)

    assert caught.value.category == "missing_schema"


@pytest.mark.parametrize(
    ("observed", "contract", "category"),
    [
        (
            "older_revision",
            RevisionContract(known_behind=frozenset({"older_revision"})),
            "schema_behind",
        ),
        (
            "future_revision",
            RevisionContract(known_ahead=frozenset({"future_revision"})),
            "schema_ahead",
        ),
        (
            "other_branch",
            RevisionContract(known_incompatible=frozenset({"other_branch"})),
            "schema_incompatible",
        ),
        ("unrecognized", RevisionContract(), "schema_unknown"),
    ],
)
async def test_unexpected_schema_revisions_fail_closed(
    migrated_database: Path,
    observed: str,
    contract: RevisionContract,
    category: str,
) -> None:
    connection = sqlite3.connect(migrated_database)
    connection.execute("UPDATE alembic_version SET version_num = ?", (observed,))
    connection.commit()
    connection.close()

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database, revision_contract=contract)

    assert caught.value.category == category
    assert caught.value.observed_revision == observed


async def test_multiple_schema_heads_fail_closed(migrated_database: Path) -> None:
    connection = sqlite3.connect(migrated_database)
    connection.execute("INSERT INTO alembic_version(version_num) VALUES ('second_head')")
    connection.commit()
    connection.close()

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)

    assert caught.value.category == "multiple_or_missing_heads"


async def test_foreign_key_violation_fails_closed(migrated_database: Path) -> None:
    connection = sqlite3.connect(migrated_database)
    connection.execute("PRAGMA foreign_keys=OFF")
    account_id = uuid4().hex
    connection.execute(
        "INSERT INTO economy_accounts"
        "(id, player_id, account_kind, currency_key, system_key, created_at_ms) "
        "VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
        (account_id, uuid4().hex),
    )
    connection.execute(
        "INSERT INTO economy_account_balances(account_id, account_kind, amount, version) "
        "VALUES (?, 'wallet', 0, 0)",
        (account_id,),
    )
    connection.commit()
    connection.close()

    runtime = await create_database_runtime(migrated_database)
    try:
        with pytest.raises(HistoricalVerificationError) as caught:
            await verify_historical_persistence(runtime.engine)
        assert caught.value.category == "foreign_key_violation"
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


async def test_non_wal_database_fails_closed(migrated_database: Path) -> None:
    connection = sqlite3.connect(migrated_database)
    assert connection.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
    connection.close()

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)

    assert caught.value.category == "unsafe_pragmas"


async def test_corrupt_database_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.sqlite3"
    database.write_bytes(b"not a sqlite database")

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(database)

    assert caught.value.category == "corrupt_or_unreadable"


def test_exclusive_process_lock_rejects_second_owner(migrated_database: Path) -> None:
    lock_path = migrated_database.parent / ".butterbot-process.lock"
    first = DatabaseProcessLock(lock_path)
    second = DatabaseProcessLock(lock_path)
    try:
        first.acquire()
        with pytest.raises(ProcessLockUnavailable):
            second.acquire()
    finally:
        second.release()
        first.release()


async def test_runtime_reports_process_lock_failure_as_readiness(
    database_runtime: DatabaseRuntime,
) -> None:
    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(database_runtime.database_path)

    assert caught.value.category == "process_lock_unavailable"


async def test_transaction_runner_retries_only_busy_failure_with_original_work(
    database_runtime: DatabaseRuntime,
) -> None:
    locker = await aiosqlite.connect(database_runtime.database_path, isolation_level=None)
    await locker.execute("PRAGMA busy_timeout=1000")
    await locker.execute("BEGIN IMMEDIATE")
    retry_factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        UnitOfWorkLifecycle(),
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
        maximum_busy_timeout_ms=50,
    )
    runner = ApplicationTransactionRunner(
        retry_factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
        retry_policy=RetryPolicy(
            max_retries=2,
            total_budget_ms=500,
            backoff_ms=(25, 75),
            deadline_guard_ms=50,
        ),
    )

    async def release_lock() -> None:
        await asyncio.sleep(0.08)
        await locker.rollback()

    async def create_player(unit_of_work: UnitOfWork) -> UUID:
        player, player_created = await unit_of_work.players.create_if_absent(
            player_id=uuid4(), discord_user_id=700, created_at_ms=1
        )
        await unit_of_work.accounts.create_wallet_if_absent(
            account_id=uuid4(),
            player_id=player.id,
            created_at_ms=1,
            player_was_created=player_created,
        )
        return player.id

    release = asyncio.create_task(release_lock())
    try:
        player_id = await runner.run("players.retry_test", create_player)
    finally:
        await release
        await locker.close()

    async with database_runtime.unit_of_work_factory() as unit_of_work:
        stored = await unit_of_work.players.get_by_discord_user_id(700)
    assert stored is not None
    assert stored.id == player_id


async def test_transaction_runner_stops_inside_retry_budget(
    database_runtime: DatabaseRuntime,
) -> None:
    locker = await aiosqlite.connect(database_runtime.database_path, isolation_level=None)
    await locker.execute("BEGIN IMMEDIATE")
    retry_factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        UnitOfWorkLifecycle(),
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
        maximum_busy_timeout_ms=50,
    )
    runner = ApplicationTransactionRunner(
        retry_factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
        retry_policy=RetryPolicy(
            max_retries=2,
            total_budget_ms=300,
            backoff_ms=(25, 75),
            deadline_guard_ms=50,
        ),
    )

    async def no_op(unit_of_work: UnitOfWork) -> None:
        del unit_of_work
        await asyncio.sleep(0)

    started = time.perf_counter()
    try:
        with pytest.raises(DatabaseRetryExhausted):
            await runner.run("operations.retry_exhaustion", no_op)
    finally:
        elapsed = time.perf_counter() - started
        await locker.rollback()
        await locker.close()

    assert elapsed < 0.5


async def test_graceful_close_releases_lock_and_rejects_new_transactions(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    factory = runtime.unit_of_work_factory
    await runtime.close(drain_timeout_seconds=0.1)

    with pytest.raises(RuntimeError, match="draining"):
        async with factory():
            pass

    replacement = DatabaseProcessLock(migrated_database.parent / ".butterbot-process.lock")
    try:
        replacement.acquire()
    finally:
        replacement.release()


async def test_shutdown_rejects_admission_before_monitor_shutdown_completes(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    monitor_close_started = asyncio.Event()
    allow_monitor_close = asyncio.Event()
    original_close = DatabaseStorageMonitor.close

    async def delayed_monitor_close(monitor: DatabaseStorageMonitor) -> None:
        monitor_close_started.set()
        await allow_monitor_close.wait()
        await original_close(monitor)

    monkeypatch.setattr(DatabaseStorageMonitor, "close", delayed_monitor_close)
    closing = asyncio.create_task(runtime.close(drain_timeout_seconds=0.1))
    await monitor_close_started.wait()

    with pytest.raises(RuntimeError, match="draining"):
        async with runtime.unit_of_work_factory():
            pass

    allow_monitor_close.set()
    await closing


async def test_shutdown_retains_captured_owner_after_unit_of_work_exit(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    entered = asyncio.Event()
    leave_transaction = asyncio.Event()
    transaction_exited = asyncio.Event()
    finish_owner = asyncio.Event()

    async def transaction_owner() -> None:
        async with runtime.unit_of_work_factory():
            entered.set()
            await leave_transaction.wait()
        transaction_exited.set()
        await finish_owner.wait()

    owner = asyncio.create_task(transaction_owner())
    await entered.wait()
    closing = asyncio.create_task(runtime.close(drain_timeout_seconds=1.0))
    await asyncio.sleep(0)
    leave_transaction.set()
    await transaction_exited.wait()

    replacement = DatabaseProcessLock(migrated_database.parent / ".butterbot-process.lock")
    with pytest.raises(ProcessLockUnavailable):
        replacement.acquire()
    assert not closing.done()

    finish_owner.set()
    await asyncio.gather(owner, closing)
    replacement.acquire()
    replacement.release()


def test_expected_schema_revision_is_release_head() -> None:
    assert EXPECTED_SCHEMA_REVISION == "20260914_0003"


async def test_shutdown_timeout_cancels_and_awaits_active_transaction_owner(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    entered = asyncio.Event()
    body_finished = asyncio.Event()

    async def transaction() -> None:
        try:
            async with runtime.unit_of_work_factory() as unit_of_work:
                await unit_of_work.players.create_if_absent(
                    player_id=uuid4(), discord_user_id=801, created_at_ms=1
                )
                entered.set()
                await asyncio.Event().wait()
        finally:
            body_finished.set()

    owner = asyncio.create_task(transaction())
    await entered.wait()
    await runtime.close(drain_timeout_seconds=0.01)
    result = await asyncio.gather(owner, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert body_finished.is_set()
    connection = sqlite3.connect(migrated_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM players").fetchone() == (0,)
    finally:
        connection.close()


async def test_shutdown_cancels_transactions_waiting_for_writer_admission(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    release = asyncio.Event()

    async def transaction() -> None:
        async with runtime.unit_of_work_factory():
            await release.wait()

    owners = [asyncio.create_task(transaction()) for _ in range(5)]
    await asyncio.sleep(0.05)
    await runtime.close(drain_timeout_seconds=0.01)
    results = await asyncio.gather(*owners, return_exceptions=True)

    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert all(owner.done() for owner in owners)


async def test_shutdown_waits_for_commit_already_in_progress(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    original_commit = AsyncSession.commit

    async def delayed_commit(session: AsyncSession) -> None:
        commit_started.set()
        await allow_commit.wait()
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", delayed_commit)

    transaction_uow: SqlAlchemyUnitOfWork | None = None

    async def transaction() -> None:
        nonlocal transaction_uow
        async with runtime.unit_of_work_factory() as unit_of_work:
            transaction_uow = unit_of_work
            _, player_created = await unit_of_work.players.create_if_absent(
                player_id=(player_id := uuid4()), discord_user_id=802, created_at_ms=1
            )
            await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player_id,
                created_at_ms=1,
                player_was_created=player_created,
            )

    owner = asyncio.create_task(transaction())
    await commit_started.wait()
    closing = asyncio.create_task(runtime.close(drain_timeout_seconds=0.01))
    await asyncio.sleep(0.05)
    assert not closing.done()
    assert not owner.cancelled()
    assert transaction_uow is not None
    assert transaction_uow.transaction_phase is TransactionPhase.COMMITTING
    allow_commit.set()
    await asyncio.gather(owner, closing)

    connection = sqlite3.connect(migrated_database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM players WHERE discord_user_id = 802"
        ).fetchone() == (1,)
    finally:
        connection.close()


async def test_shutdown_fail_stops_without_releasing_ownership_for_stuck_owner(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    allow_finish = asyncio.Event()

    async def transaction() -> None:
        async with runtime.unit_of_work_factory():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await allow_finish.wait()

    owner = asyncio.create_task(transaction())
    await entered.wait()

    with pytest.raises(ShutdownIncomplete):
        await runtime.close(drain_timeout_seconds=0.01)

    assert cancelled.is_set()
    assert not owner.done()
    replacement = DatabaseProcessLock(migrated_database.parent / ".butterbot-process.lock")
    with pytest.raises(ProcessLockUnavailable):
        replacement.acquire()

    allow_finish.set()
    await asyncio.gather(owner, return_exceptions=True)
    await runtime.close(drain_timeout_seconds=0.1)
    replacement.acquire()
    replacement.release()


async def test_process_lock_remains_held_until_cancelled_owner_task_finishes(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    allow_finish = asyncio.Event()

    async def transaction() -> None:
        async with runtime.unit_of_work_factory() as unit_of_work:
            await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=803, created_at_ms=1
            )
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await allow_finish.wait()

    owner = asyncio.create_task(transaction())
    await entered.wait()
    closing = asyncio.create_task(runtime.close(drain_timeout_seconds=0.01))
    await cancelled.wait()

    replacement = DatabaseProcessLock(migrated_database.parent / ".butterbot-process.lock")
    with pytest.raises(ProcessLockUnavailable):
        replacement.acquire()
    assert not closing.done()
    assert not owner.done()

    allow_finish.set()
    await asyncio.gather(owner, return_exceptions=True)
    await closing
    replacement.acquire()
    replacement.release()


async def test_runtime_close_completes_safely_when_caller_is_cancelled(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    allow_finish = asyncio.Event()

    async def transaction() -> None:
        async with runtime.unit_of_work_factory():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await allow_finish.wait()

    owner = asyncio.create_task(transaction())
    await entered.wait()
    closing = asyncio.create_task(runtime.close(drain_timeout_seconds=0.01))
    await cancelled.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    allow_finish.set()
    await asyncio.gather(owner, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await closing

    replacement = DatabaseProcessLock(migrated_database.parent / ".butterbot-process.lock")
    replacement.acquire()
    replacement.release()


async def test_canonical_path_alias_cannot_acquire_independent_runtime(
    migrated_database: Path,
) -> None:
    alias_parent = migrated_database.parent / "alias-parent"
    alias_parent.mkdir()
    alias = alias_parent / ".." / migrated_database.name
    runtime = await create_database_runtime(migrated_database)
    try:
        with pytest.raises(DatabaseReadinessError) as caught:
            await create_database_runtime(
                alias,
                storage_contract=DatabaseStorageContract(migrated_database.parent),
            )
        assert caught.value.category == "process_lock_unavailable"
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


async def test_hard_link_alias_fails_closed_while_original_runtime_owns_database(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    alias = migrated_database.parent / "hard-link.sqlite3"
    os.link(migrated_database, alias)
    try:
        with pytest.raises(DatabaseReadinessError) as caught:
            await create_database_runtime(
                alias,
                storage_contract=DatabaseStorageContract(migrated_database.parent),
            )
        assert caught.value.category == "unsafe_path"
    finally:
        alias.unlink()
        await runtime.close(drain_timeout_seconds=0.1)


async def test_symlink_database_path_fails_closed(
    migrated_database: Path,
) -> None:
    alias = migrated_database.parent / "symlink.sqlite3"
    try:
        alias.symlink_to(migrated_database)
    except OSError:
        pytest.skip("creating a file symlink is not permitted on this host")
    try:
        with pytest.raises(DatabaseReadinessError) as caught:
            await create_database_runtime(
                alias,
                storage_contract=DatabaseStorageContract(migrated_database.parent),
            )
        assert caught.value.category == "unsafe_path"
    finally:
        alias.unlink()


async def test_database_outside_approved_root_fails_closed(
    migrated_database: Path,
    tmp_path: Path,
) -> None:
    approved_root = tmp_path / "approved"
    approved_root.mkdir()
    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(
            migrated_database,
            storage_contract=DatabaseStorageContract(approved_root),
        )
    assert caught.value.category == "unsafe_path"


async def test_unverifiable_production_volume_identity_fails_closed(
    migrated_database: Path,
) -> None:
    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(
            migrated_database,
            storage_contract=DatabaseStorageContract(
                migrated_database.parent,
                required_volume_id="not-the-current-volume",
                administrator_uid=0,
                service_group_gid=1000,
            ),
        )
    assert caught.value.category == "unsafe_storage"


def test_linux_ext4_volume_identity_can_be_verified(
    migrated_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import storage as storage_module

    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "29 23 8:1 / / rw,relatime - ext4 /dev/test rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(storage_module, "LINUX_MOUNTINFO_PATH", mountinfo)

    def accept_test_permissions(
        database_path: Path,
        approved_root: Path,
        *,
        administrator_uid: int,
        service_group_gid: int,
    ) -> None:
        del database_path, approved_root, administrator_uid, service_group_gid

    monkeypatch.setattr(
        storage_module, "_validate_linux_replacement_protection", accept_test_permissions
    )
    monkeypatch.setattr(storage_module, "validate_linux_network_namespace", lambda: None)

    storage = validate_database_storage(
        migrated_database,
        DatabaseStorageContract(
            migrated_database.parent,
            required_volume_id="8:1",
            administrator_uid=0,
            service_group_gid=1000,
        ),
    )

    assert storage.filesystem == "ext4"
    assert storage.volume_id == "8:1"


async def test_committed_incomplete_transport_claim_fails_readiness(
    migrated_database: Path,
) -> None:
    connection = sqlite3.connect(migrated_database)
    connection.execute(
        "INSERT INTO operations_transport_requests"
        "(id, namespace, transport_key, actor_kind, actor_reference, request_fingerprint) "
        "VALUES (?, 'operations.test', 'key', 'discord_user', '123', ?)",
        (uuid4().hex, "f" * 64),
    )
    connection.commit()
    connection.close()

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "incomplete_transport_request"


class _RetryTelemetry(NullOperationsTelemetry):
    def __init__(self) -> None:
        self.exhausted: list[tuple[str, int]] = []

    def database_busy_exhausted(
        self,
        *,
        operation: str,
        attempts: int,
        elapsed_ms: float,
    ) -> None:
        del elapsed_ms
        self.exhausted.append((operation, attempts))


class _ExplodingRetryTelemetry(NullOperationsTelemetry):
    def database_busy_retry(
        self,
        *,
        operation: str,
        attempt: int,
        wait_ms: int,
        elapsed_ms: float,
    ) -> None:
        del operation, attempt, wait_ms, elapsed_ms
        raise RuntimeError("retry telemetry failed")

    def database_busy_exhausted(
        self,
        *,
        operation: str,
        attempts: int,
        elapsed_ms: float,
    ) -> None:
        del operation, attempts, elapsed_ms
        raise RuntimeError("exhaustion telemetry failed")


async def test_busy_retry_telemetry_failure_does_not_prevent_retry(
    database_runtime: DatabaseRuntime,
) -> None:
    attempts = 0
    runner = ApplicationTransactionRunner(
        database_runtime.unit_of_work_factory,
        is_retryable=lambda error: isinstance(error, sqlite3.OperationalError),
        telemetry=_ExplodingRetryTelemetry(),
        retry_policy=RetryPolicy(
            max_retries=1,
            total_budget_ms=500,
            backoff_ms=(1,),
            deadline_guard_ms=20,
        ),
    )

    async def body(unit_of_work: UnitOfWork) -> str:
        del unit_of_work
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return "retried"

    assert await runner.run("operations.retry", body) == "retried"
    assert attempts == 2


async def test_busy_exhaustion_telemetry_failure_preserves_exhaustion_outcome(
    database_runtime: DatabaseRuntime,
) -> None:
    runner = ApplicationTransactionRunner(
        database_runtime.unit_of_work_factory,
        is_retryable=lambda error: isinstance(error, sqlite3.OperationalError),
        telemetry=_ExplodingRetryTelemetry(),
        retry_policy=RetryPolicy(
            max_retries=0,
            total_budget_ms=100,
            backoff_ms=(1,),
            deadline_guard_ms=10,
        ),
    )

    async def locked(unit_of_work: UnitOfWork) -> None:
        del unit_of_work
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(DatabaseRetryExhausted):
        await runner.run("operations.exhausted", locked)


class _WriterSlotHolder:
    @property
    def resources_closed(self) -> bool:
        return True


async def _occupy_all_writer_slots(
    lifecycle: UnitOfWorkLifecycle,
) -> tuple[list[asyncio.Event], list[asyncio.Task[None]]]:
    releases = [asyncio.Event() for _ in range(4)]
    entered = [asyncio.Event() for _ in range(4)]

    async def hold(index: int) -> None:
        token = cast("SqlAlchemyUnitOfWork", _WriterSlotHolder())
        await lifecycle.register(token, 1_000)
        entered[index].set()
        try:
            await releases[index].wait()
        finally:
            lifecycle.finish(token)

    tasks = [asyncio.create_task(hold(index)) for index in range(4)]
    await asyncio.gather(*(event.wait() for event in entered))
    return releases, tasks


async def _release_writer_holders(
    releases: list[asyncio.Event],
    tasks: list[asyncio.Task[None]],
) -> None:
    for release in releases:
        release.set()
    await asyncio.gather(*tasks)


async def test_fifth_writer_exceeding_short_budget_returns_retry_exhaustion(
    database_runtime: DatabaseRuntime,
) -> None:
    lifecycle = UnitOfWorkLifecycle()
    releases, holders = await _occupy_all_writer_slots(lifecycle)
    factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        lifecycle,
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
    )
    runner = ApplicationTransactionRunner(
        factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
        retry_policy=RetryPolicy(
            max_retries=0,
            total_budget_ms=80,
            backoff_ms=(1,),
            deadline_guard_ms=20,
        ),
    )
    started = time.perf_counter()
    try:
        with pytest.raises(DatabaseRetryExhausted):
            await runner.run("operations.fifth_writer", lambda unit_of_work: asyncio.sleep(0))
        assert time.perf_counter() - started < 0.5
    finally:
        await _release_writer_holders(releases, holders)


async def test_writer_slot_available_just_before_budget_expiry_is_admitted(
    database_runtime: DatabaseRuntime,
) -> None:
    lifecycle = UnitOfWorkLifecycle()
    releases, holders = await _occupy_all_writer_slots(lifecycle)
    factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        lifecycle,
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
    )

    async def enter_fifth() -> int:
        async with factory(remaining_budget_ms=150) as unit_of_work:
            session = unit_of_work._require_session()  # pyright: ignore[reportPrivateUsage]
            return int(await session.scalar(text("PRAGMA busy_timeout")) or 0)

    fifth = asyncio.create_task(enter_fifth())
    await asyncio.sleep(0.1)
    releases[0].set()
    try:
        busy_timeout_ms = await fifth
        assert 1 <= busy_timeout_ms < 150
    finally:
        await _release_writer_holders(releases, holders)


async def test_writer_slot_available_after_budget_expiry_is_rejected(
    database_runtime: DatabaseRuntime,
) -> None:
    lifecycle = UnitOfWorkLifecycle()
    releases, holders = await _occupy_all_writer_slots(lifecycle)
    factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        lifecycle,
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
    )
    fifth = asyncio.create_task(factory(remaining_budget_ms=30).__aenter__())
    await asyncio.sleep(0.05)
    releases[0].set()
    try:
        with pytest.raises(WriterAdmissionTimeout):
            await fifth
    finally:
        await _release_writer_holders(releases, holders)


async def test_caller_cancellation_while_waiting_for_writer_slot_propagates(
    database_runtime: DatabaseRuntime,
) -> None:
    lifecycle = UnitOfWorkLifecycle()
    releases, holders = await _occupy_all_writer_slots(lifecycle)
    factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        lifecycle,
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
    )

    async def enter_fifth() -> None:
        async with factory(remaining_budget_ms=1_000):
            pass

    fifth = asyncio.create_task(enter_fifth())
    await asyncio.sleep(0)
    fifth.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await fifth
    finally:
        await _release_writer_holders(releases, holders)


async def test_busy_retry_recomputes_timeout_after_nonzero_admission_delay(
    database_runtime: DatabaseRuntime,
) -> None:
    lifecycle = UnitOfWorkLifecycle()
    releases, holders = await _occupy_all_writer_slots(lifecycle)
    factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        lifecycle,
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
    )
    runner = ApplicationTransactionRunner(
        factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
        retry_policy=RetryPolicy(
            max_retries=1,
            total_budget_ms=300,
            backoff_ms=(1,),
            deadline_guard_ms=20,
        ),
    )
    observed_timeouts: list[int] = []

    async def body(unit_of_work: UnitOfWork) -> str:
        concrete = cast("SqlAlchemyUnitOfWork", unit_of_work)
        session = concrete._require_session()  # pyright: ignore[reportPrivateUsage]
        observed_timeouts.append(int(await session.scalar(text("PRAGMA busy_timeout")) or 0))
        if len(observed_timeouts) == 1:
            raise sqlite3.OperationalError("database is locked")
        return "retried"

    execution = asyncio.create_task(runner.run("operations.delayed_retry", body))
    await asyncio.sleep(0.05)
    releases[0].set()
    try:
        assert await execution == "retried"
        assert len(observed_timeouts) == 2
        assert observed_timeouts[0] < 280
        assert observed_timeouts[1] <= observed_timeouts[0]
    finally:
        await _release_writer_holders(releases, holders)


class _RuntimeStorageTelemetry(NullOperationsTelemetry):
    def __init__(self) -> None:
        self.storage_events: list[tuple[str, str | None]] = []
        self.mutation_events: list[tuple[bool, str]] = []

    def database_storage(
        self,
        *,
        snapshot: DatabaseStorageSnapshot,
        outcome: str,
        error_category: str | None,
    ) -> None:
        del snapshot
        self.storage_events.append((outcome, error_category))

    def mutations_state(self, *, enabled: bool, reason: str) -> None:
        self.mutation_events.append((enabled, reason))


async def test_final_lock_failure_emits_dedicated_telemetry(
    database_runtime: DatabaseRuntime,
) -> None:
    locker = await aiosqlite.connect(database_runtime.database_path, isolation_level=None)
    await locker.execute("BEGIN IMMEDIATE")
    telemetry = _RetryTelemetry()
    retry_factory = SqlAlchemyUnitOfWorkFactory(
        database_runtime.engine,
        UnitOfWorkLifecycle(),
        identity_guard=database_runtime.unit_of_work_factory.identity_guard,
        maximum_busy_timeout_ms=10,
    )
    runner = ApplicationTransactionRunner(
        retry_factory,
        is_retryable=is_sqlite_busy,
        telemetry=telemetry,
        retry_policy=RetryPolicy(
            max_retries=0,
            total_budget_ms=100,
            backoff_ms=(1,),
            deadline_guard_ms=10,
        ),
    )

    try:
        with pytest.raises(DatabaseRetryExhausted):
            await runner.run("operations.locked", lambda unit_of_work: asyncio.sleep(0))
    finally:
        await locker.rollback()
        await locker.close()

    assert telemetry.exhausted == [("operations.locked", 1)]


async def test_storage_identity_change_blocks_runtime_mutation_eligibility(
    migrated_database: Path,
) -> None:
    telemetry = _RuntimeStorageTelemetry()
    database_runtime = await create_database_runtime(
        migrated_database,
        telemetry=telemetry,
    )
    eligibility = GlobalMutationEligibility(
        configured_enabled=True,
        database_ready=True,
        runtime_safety=database_runtime.storage_monitor,
    )
    alias = database_runtime.database_path.parent / "runtime-hard-link.sqlite3"
    os.link(database_runtime.database_path, alias)
    try:
        with pytest.raises(DatabaseIdentityMismatch):
            async with database_runtime.unit_of_work_factory():
                pass
        decision = eligibility.evaluate()
        assert decision.allowed is False
        assert decision.reason == "runtime_storage_unsafe"
        assert telemetry.storage_events[-1] == (
            "unsafe",
            "database_identity_mismatch",
        )
        assert telemetry.mutation_events == [(False, "runtime_storage_unsafe")]
    finally:
        alias.unlink()
        await database_runtime.close(drain_timeout_seconds=0.1)


async def test_writer_admission_rejects_database_unlink_and_recreate(
    migrated_database: Path,
) -> None:
    telemetry = _RuntimeStorageTelemetry()
    runtime = await create_database_runtime(migrated_database, telemetry=telemetry)
    original_database = migrated_database.with_name("original.sqlite3")
    await runtime.engine.dispose()
    os.replace(migrated_database, original_database)
    shutil.copyfile(original_database, migrated_database)

    try:
        with pytest.raises(DatabaseIdentityMismatch):
            async with runtime.unit_of_work_factory():
                pass
        assert runtime.storage_monitor.is_safe() is False
        assert telemetry.storage_events[-1] == (
            "unsafe",
            "database_identity_mismatch",
        )
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


async def test_every_connection_checkout_revalidates_database_identity(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = database_runtime.unit_of_work_factory.identity_guard
    original_verify = guard.verify_connection_path
    checked_paths: list[str] = []

    def record_verify(connection_database_path: str) -> None:
        checked_paths.append(connection_database_path)
        original_verify(connection_database_path)

    monkeypatch.setattr(guard, "verify_connection_path", record_verify)

    async with database_runtime.engine.connect():
        pass
    async with database_runtime.engine.connect():
        pass

    assert len(checked_paths) >= 2
    assert all(Path(path) == database_runtime.database_path for path in checked_paths)


async def test_connection_identity_guard_rejects_another_database(
    database_runtime: DatabaseRuntime,
    tmp_path: Path,
) -> None:
    other_database = tmp_path / "other.sqlite3"
    other_database.write_bytes(database_runtime.database_path.read_bytes())

    with pytest.raises(DatabaseIdentityMismatch, match="checked-out connection"):
        database_runtime.unit_of_work_factory.identity_guard.verify_connection_path(
            str(other_database)
        )


async def test_storage_monitor_deduplicates_safety_transitions_and_recovers(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import storage_monitor as monitor_module

    telemetry = _RuntimeStorageTelemetry()
    runtime = await create_database_runtime(
        migrated_database,
        telemetry=telemetry,
        configured_mutations_enabled=True,
    )
    original_validate = monitor_module.validate_database_storage

    def fail_storage_validation(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("sampling probe failed")

    try:
        monkeypatch.setattr(
            monitor_module,
            "validate_database_storage",
            fail_storage_validation,
        )
        await runtime.storage_monitor.sample()
        await runtime.storage_monitor.sample()

        assert telemetry.storage_events[-2:] == [
            ("unsafe", "storage_check_failed"),
            ("unsafe", "storage_check_failed"),
        ]
        assert telemetry.mutation_events == [(False, "runtime_storage_unsafe")]

        monkeypatch.setattr(
            monitor_module,
            "validate_database_storage",
            original_validate,
        )
        await runtime.storage_monitor.sample()
        assert telemetry.mutation_events == [
            (False, "runtime_storage_unsafe"),
            (True, "enabled"),
        ]
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


class _FlakyStorageTelemetry(_RuntimeStorageTelemetry):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_sample = False
        self.sample_calls = 0

    def database_storage(
        self,
        *,
        snapshot: DatabaseStorageSnapshot,
        outcome: str,
        error_category: str | None,
    ) -> None:
        self.sample_calls += 1
        if self.fail_next_sample:
            self.fail_next_sample = False
            raise RuntimeError("telemetry sink failed")
        super().database_storage(
            snapshot=snapshot,
            outcome=outcome,
            error_category=error_category,
        )


async def test_periodic_storage_monitor_survives_sampling_telemetry_error(
    migrated_database: Path,
) -> None:
    telemetry = _FlakyStorageTelemetry()
    runtime = await create_database_runtime(migrated_database, telemetry=telemetry)
    await runtime.storage_monitor.close()
    storage = validate_database_storage(
        runtime.database_path,
        DatabaseStorageContract(runtime.database_path.parent),
    )
    monitor = DatabaseStorageMonitor(
        storage=storage,
        contract=DatabaseStorageContract(runtime.database_path.parent),
        engine=runtime.engine,
        telemetry=telemetry,
        interval_seconds=0.01,
    )
    telemetry.fail_next_sample = True
    calls_before_start = telemetry.sample_calls
    monitor.start()
    try:
        await asyncio.sleep(0.06)
    finally:
        await monitor.close()
        await runtime.close(drain_timeout_seconds=0.1)

    assert telemetry.sample_calls >= calls_before_start + 2
