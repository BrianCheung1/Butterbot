import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from tests.test_join import service as join_service

from butterbot.application.economy.balance import BalanceResult, BalanceService
from butterbot.bootstrap import compose_application
from butterbot.discord_app.config import Settings
from butterbot.infrastructure.persistence.database import DatabaseRuntime
from butterbot.infrastructure.persistence.repositories import (
    PersistenceInvariantError,
    SqlAlchemyPlayerRepository,
)


def dump(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


@pytest.mark.parametrize("amount", [0, 27, 2**63 - 1])
async def test_balance_is_exact_self_only_and_never_writes(
    database_runtime: DatabaseRuntime, amount: int
) -> None:
    await join_service(database_runtime).join(discord_user_id=123, interaction_id=456)
    with sqlite3.connect(database_runtime.database_path) as connection:
        connection.execute("UPDATE economy_account_balances SET amount=?, version=4", (amount,))
    before = dump(database_runtime.database_path)
    query = BalanceService(database_runtime.unit_of_work_factory.read_snapshot)
    assert await query.balance(discord_user_id=123) == BalanceResult("available", amount)
    assert await query.balance(discord_user_id=789) == BalanceResult("unjoined")
    assert await query.balance(discord_user_id=123) == BalanceResult("available", amount)
    assert dump(database_runtime.database_path) == before


@pytest.mark.parametrize("state", ["inactive", "missing_wallet", "missing_projection", "deleted"])
async def test_balance_does_not_repair_or_reactivate(
    database_runtime: DatabaseRuntime, state: str
) -> None:
    await join_service(database_runtime).join(discord_user_id=123, interaction_id=456)
    with sqlite3.connect(database_runtime.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        if state == "inactive":
            connection.execute("UPDATE players SET lifecycle_state='pseudonymized'")
        else:
            connection.execute("DELETE FROM economy_account_balances")
            if state != "missing_projection":
                connection.execute("DELETE FROM economy_accounts")
            if state == "deleted":
                connection.execute("DELETE FROM players")
    before = dump(database_runtime.database_path)
    query = BalanceService(database_runtime.unit_of_work_factory.read_snapshot)
    if state == "missing_projection":
        with pytest.raises(PersistenceInvariantError):
            await query.balance(discord_user_id=123)
    else:
        status = {"inactive": "inactive", "missing_wallet": "unavailable", "deleted": "unjoined"}[
            state
        ]
        result = await query.balance(discord_user_id=123)
        assert result.status == status and result.amount is None
    assert dump(database_runtime.database_path) == before


@pytest.mark.parametrize("invalid", [0, -1, True, 2**63])
async def test_invalid_balance_identity_never_opens_database(invalid: int) -> None:
    factory = AsyncMock()
    with pytest.raises((ValueError, TypeError)):
        await BalanceService(factory).balance(discord_user_id=invalid)
    factory.assert_not_called()


async def test_balance_reads_while_another_writer_is_active(
    database_runtime: DatabaseRuntime,
) -> None:
    await join_service(database_runtime).join(discord_user_id=123, interaction_id=456)
    connection = sqlite3.connect(database_runtime.database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE economy_account_balances SET amount=99")
        result = await asyncio.wait_for(
            BalanceService(database_runtime.unit_of_work_factory.read_snapshot).balance(
                discord_user_id=123
            ),
            timeout=2,
        )
        assert result == BalanceResult("available", 0)
    finally:
        connection.rollback()
        connection.close()


async def test_balance_uses_one_snapshot_during_competing_commit(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await join_service(database_runtime).join(discord_user_id=123, interaction_id=456)
    original = SqlAlchemyPlayerRepository.get_by_discord_user_id

    async def lookup(self: SqlAlchemyPlayerRepository, discord_user_id: int):
        player = await original(self, discord_user_id)
        with sqlite3.connect(database_runtime.database_path) as connection:
            connection.execute("UPDATE economy_account_balances SET amount=99")
        return player

    monkeypatch.setattr(SqlAlchemyPlayerRepository, "get_by_discord_user_id", lookup)
    query = BalanceService(database_runtime.unit_of_work_factory.read_snapshot)
    assert await query.balance(discord_user_id=123) == BalanceResult("available", 0)
    monkeypatch.undo()
    assert await query.balance(discord_user_id=123) == BalanceResult("available", 99)


async def test_balance_is_available_when_normal_composition_disables_mutations(
    migrated_database: Path,
) -> None:
    application = await compose_application(
        Settings(
            discord_token="not-used",
            release_id="test",
            database_path=migrated_database,
            database_root=migrated_database.parent,
            database_volume_id=None,
            economy_mutations_enabled=False,
        )
    )
    try:
        await join_service(application.database).join(discord_user_id=123, interaction_id=456)
        assert not application.mutation_eligibility.evaluate().allowed
        assert await application.balance_service.balance(discord_user_id=123) == BalanceResult(
            "available", 0
        )
    finally:
        await application.close()
    with pytest.raises(RuntimeError, match="draining"):
        await application.balance_service.balance(discord_user_id=123)
