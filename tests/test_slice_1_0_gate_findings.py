from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import create_async_engine

from butterbot.application.operations.ports import TransportActor
from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.readiness import DatabaseReadinessError
from butterbot.infrastructure.persistence.repositories import PersistenceInvariantError
from butterbot.infrastructure.persistence.schema_contract import (
    INTEGRITY_SENTINEL_INDEX,
    SQLITE_AGGREGATE_TRIGGER_SQL,
)
from butterbot.infrastructure.persistence.verification import (
    HistoricalVerificationError,
    verify_historical_persistence,
)


async def _create_player_wallet(database: Path, *, discord_user_id: int) -> tuple[UUID, UUID]:
    runtime = await create_database_runtime(database)
    try:
        async with runtime.unit_of_work_factory() as unit_of_work:
            player, player_created = await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=discord_user_id, created_at_ms=1
            )
            wallet, wallet_created = await unit_of_work.accounts.create_wallet_if_absent(
                account_id=uuid4(),
                player_id=player.id,
                created_at_ms=1,
                player_was_created=player_created,
            )
            assert player_created is True
            assert wallet_created is True
            return player.id, wallet.id
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


def _delete_wallet(database: Path, wallet_id: UUID) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "DELETE FROM economy_account_balances WHERE account_id = ?", (wallet_id.hex,)
        )
        connection.execute("DELETE FROM economy_accounts WHERE id = ?", (wallet_id.hex,))


async def test_join_retry_cannot_repair_committed_player_missing_wallet(
    migrated_database: Path,
) -> None:
    player_id, wallet_id = await _create_player_wallet(migrated_database, discord_user_id=9_001)
    runtime = await create_database_runtime(migrated_database)
    _delete_wallet(migrated_database, wallet_id)

    try:
        with pytest.raises(PersistenceInvariantError, match="existing player.*wallet"):
            async with runtime.unit_of_work_factory() as unit_of_work:
                claim = await unit_of_work.transport_requests.claim(
                    request_id=uuid4(),
                    namespace="players.join",
                    transport_key="join-retry-9001",
                    actor=TransportActor("discord_user", "9001"),
                    request_fingerprint="f" * 64,
                )
                assert claim.is_new is True
                player, player_created = await unit_of_work.players.create_if_absent(
                    player_id=uuid4(), discord_user_id=9_001, created_at_ms=2
                )
                assert player.id == player_id
                assert player_created is False
                await unit_of_work.accounts.create_wallet_if_absent(
                    account_id=uuid4(),
                    player_id=player.id,
                    created_at_ms=2,
                    player_was_created=player_created,
                )
    finally:
        await runtime.close(drain_timeout_seconds=0.1)

    with sqlite3.connect(migrated_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM players WHERE discord_user_id = 9001"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM economy_accounts WHERE player_id = ?", (player_id.hex,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM economy_account_balances WHERE account_id = ?", (wallet_id.hex,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT violation_kind, aggregate_id FROM operations_integrity_violations"
        ).fetchall() == [("player_without_wallet", player_id.hex)]
        assert connection.execute(
            "SELECT COUNT(*) FROM operations_transport_requests"
        ).fetchone() == (0,)

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "missing_player_wallet"


@pytest.mark.parametrize(
    "trigger_name",
    [
        "trg_accounts_integrity_after_delete",
        "trg_integrity_violations_protect_active_delete",
    ],
)
async def test_startup_rejects_dropped_required_integrity_trigger(
    migrated_database: Path,
    trigger_name: str,
) -> None:
    with sqlite3.connect(migrated_database) as connection:
        connection.execute(f"DROP TRIGGER {trigger_name}")

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "integrity_schema_contract"


async def test_startup_rejects_replaced_required_integrity_trigger(
    migrated_database: Path,
) -> None:
    trigger_name = "trg_balances_integrity_after_delete"
    with sqlite3.connect(migrated_database) as connection:
        connection.execute(f"DROP TRIGGER {trigger_name}")
        connection.execute(
            f"CREATE TRIGGER {trigger_name} AFTER DELETE ON economy_account_balances "
            "BEGIN SELECT 1; END"
        )

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "integrity_schema_contract"


async def test_startup_schema_contract_is_case_sensitive_inside_sql_literals(
    migrated_database: Path,
) -> None:
    trigger_name = "trg_accounts_require_balance_after_insert"
    altered_sql = SQLITE_AGGREGATE_TRIGGER_SQL[trigger_name].replace("'wallet'", "'WALLET'")
    with sqlite3.connect(migrated_database) as connection:
        connection.execute(f"DROP TRIGGER {trigger_name}")
        connection.execute(altered_sql)

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "integrity_schema_contract"


async def test_startup_rejects_missing_sentinel_index(migrated_database: Path) -> None:
    with sqlite3.connect(migrated_database) as connection:
        connection.execute(f"DROP INDEX {INTEGRITY_SENTINEL_INDEX}")

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "integrity_schema_contract"


@pytest.mark.parametrize(
    "table_name",
    [
        "players",
        "economy_accounts",
        "economy_account_balances",
        "operations_integrity_violations",
    ],
)
async def test_startup_rejects_altered_integrity_dependency_table_definition(
    migrated_database: Path,
    table_name: str,
) -> None:
    with sqlite3.connect(migrated_database) as connection:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN hidden_state TEXT")

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "integrity_schema_contract"


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM operations_integrity_violations",
        "UPDATE operations_integrity_violations SET aggregate_id = ?",
        "UPDATE operations_integrity_violations SET violation_kind = 'account_without_balance'",
    ],
)
async def test_active_sentinel_row_cannot_be_deleted_or_updated(
    migrated_database: Path,
    statement: str,
) -> None:
    player_id, wallet_id = await _create_player_wallet(migrated_database, discord_user_id=9_002)
    _delete_wallet(migrated_database, wallet_id)

    with sqlite3.connect(migrated_database) as connection:
        parameters = (uuid4().hex,) if "?" in statement else ()
        with pytest.raises(sqlite3.IntegrityError, match="integrity violation|immutable"):
            connection.execute(statement, parameters)
        assert connection.execute(
            "SELECT violation_kind, aggregate_id FROM operations_integrity_violations"
        ).fetchall() == [("player_without_wallet", player_id.hex)]

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "missing_player_wallet"


async def test_aggregate_mutation_rollback_restores_clean_sentinel_state(
    migrated_database: Path,
) -> None:
    _, wallet_id = await _create_player_wallet(migrated_database, discord_user_id=9_003)
    connection = sqlite3.connect(migrated_database)
    try:
        connection.execute("BEGIN")
        connection.execute(
            "DELETE FROM economy_account_balances WHERE account_id = ?", (wallet_id.hex,)
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM operations_integrity_violations"
        ).fetchone() == (1,)
        connection.rollback()
        assert connection.execute(
            "SELECT COUNT(*) FROM operations_integrity_violations"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM economy_account_balances WHERE account_id = ?", (wallet_id.hex,)
        ).fetchone() == (1,)
    finally:
        connection.close()

    runtime = await create_database_runtime(migrated_database)
    await runtime.close(drain_timeout_seconds=0.1)


async def test_valid_transactional_repair_clears_violation_and_startup_succeeds(
    migrated_database: Path,
) -> None:
    player_id, wallet_id = await _create_player_wallet(migrated_database, discord_user_id=9_004)
    _delete_wallet(migrated_database, wallet_id)

    replacement_wallet_id = uuid4()
    with sqlite3.connect(migrated_database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO economy_accounts"
            "(id, player_id, account_kind, currency_key, system_key, created_at_ms) "
            "VALUES (?, ?, 'wallet', 'coin', NULL, 2)",
            (replacement_wallet_id.hex, player_id.hex),
        )
        connection.execute(
            "INSERT INTO economy_account_balances(account_id, account_kind, amount, version) "
            "VALUES (?, 'wallet', 0, 0)",
            (replacement_wallet_id.hex,),
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM operations_integrity_violations"
        ).fetchone() == (0,)

    runtime = await create_database_runtime(migrated_database)
    await runtime.close(drain_timeout_seconds=0.1)


async def test_streaming_verifier_detects_aggregate_corruption_without_sentinel(
    migrated_database: Path,
) -> None:
    _, wallet_id = await _create_player_wallet(migrated_database, discord_user_id=9_005)
    _delete_wallet(migrated_database, wallet_id)
    with sqlite3.connect(migrated_database) as connection:
        connection.execute("DROP TRIGGER trg_integrity_violations_protect_active_delete")
        connection.execute("DELETE FROM operations_integrity_violations")

    engine = create_async_engine(URL.create("sqlite+aiosqlite", database=str(migrated_database)))
    try:
        with pytest.raises(HistoricalVerificationError) as caught:
            await verify_historical_persistence(engine)
        assert caught.value.category == "invalid_persisted_state"
    finally:
        await engine.dispose()


def test_migration_trigger_manifest_covers_protection_and_maintenance() -> None:
    assert set(SQLITE_AGGREGATE_TRIGGER_SQL) == {
        "trg_players_require_wallet_after_insert",
        "trg_players_integrity_after_delete",
        "trg_accounts_require_balance_after_insert",
        "trg_accounts_integrity_after_delete",
        "trg_balances_complete_account_after_insert",
        "trg_balances_integrity_after_delete",
        "trg_integrity_violations_protect_active_delete",
        "trg_integrity_violations_protect_update",
    }
