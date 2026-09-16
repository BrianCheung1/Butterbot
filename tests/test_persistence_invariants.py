from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.readiness import (
    DatabaseReadinessError,
    check_schema_readiness,
)
from butterbot.infrastructure.persistence.repositories import PersistenceInvariantError
from butterbot.infrastructure.persistence.verification import main as verification_main


def _insert_player_wallet(database: Path) -> tuple[UUID, UUID]:
    player_id = uuid4()
    account_id = uuid4()
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO players VALUES (?, 1, 1, 'active')", (player_id.hex,))
        connection.execute(
            "INSERT INTO economy_accounts VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
            (account_id.hex, player_id.hex),
        )
        connection.execute(
            "INSERT INTO economy_account_balances VALUES (?, 'wallet', 7, 0)",
            (account_id.hex,),
        )
    return player_id, account_id


async def test_startup_detects_missing_balance_projection(migrated_database: Path) -> None:
    _, account_id = _insert_player_wallet(migrated_database)
    with sqlite3.connect(migrated_database) as connection:
        connection.execute(
            "DELETE FROM economy_account_balances WHERE account_id = ?", (account_id.hex,)
        )

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "missing_balance_projection"


async def test_startup_detects_player_without_wallet(migrated_database: Path) -> None:
    with sqlite3.connect(migrated_database) as connection:
        connection.execute("INSERT INTO players VALUES (?, 1, 1, 'active')", (uuid4().hex,))

    with pytest.raises(DatabaseReadinessError) as caught:
        await create_database_runtime(migrated_database)
    assert caught.value.category == "missing_player_wallet"


async def test_wallet_creation_cannot_repair_missing_projection_to_zero(
    migrated_database: Path,
) -> None:
    player_id, account_id = _insert_player_wallet(migrated_database)
    runtime = await create_database_runtime(migrated_database)
    with sqlite3.connect(migrated_database) as connection:
        connection.execute(
            "DELETE FROM economy_account_balances WHERE account_id = ?", (account_id.hex,)
        )
    try:
        with pytest.raises(PersistenceInvariantError, match="missing"):
            async with runtime.unit_of_work_factory() as unit_of_work:
                await unit_of_work.accounts.create_wallet_if_absent(
                    account_id=uuid4(),
                    player_id=player_id,
                    created_at_ms=2,
                    player_was_created=False,
                )
    finally:
        await runtime.close(drain_timeout_seconds=0.1)

    with sqlite3.connect(migrated_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM economy_account_balances WHERE account_id = ?",
            (account_id.hex,),
        ).fetchone() == (0,)


async def test_transaction_cannot_commit_player_without_wallet(migrated_database: Path) -> None:
    runtime = await create_database_runtime(migrated_database)
    try:
        with pytest.raises(PersistenceInvariantError, match="player"):
            async with runtime.unit_of_work_factory() as unit_of_work:
                await unit_of_work.players.create_if_absent(
                    player_id=uuid4(), discord_user_id=44, created_at_ms=1
                )
    finally:
        await runtime.close(drain_timeout_seconds=0.1)
    with sqlite3.connect(migrated_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM players").fetchone() == (0,)


async def test_startup_contract_does_not_query_permanent_history(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement.lower())

    event.listen(runtime.engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        await check_schema_readiness(runtime.engine, migrated_database)
    finally:
        event.remove(runtime.engine.sync_engine, "before_cursor_execute", record_statement)
        await runtime.close(drain_timeout_seconds=0.1)

    assert not any("economy_ledger_transactions" in statement for statement in statements)
    assert not any("economy_ledger_postings" in statement for statement in statements)
    transport_queries = [
        statement for statement in statements if "operations_transport_requests" in statement
    ]
    assert transport_queries
    assert all("limit 1" in statement for statement in transport_queries)


def test_offline_verifier_cli_reports_clean_database(
    migrated_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert verification_main([str(migrated_database)]) == 0
    assert '"outcome": "passed"' in capsys.readouterr().out
