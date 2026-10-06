import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from tests.test_correction_migration import alembic_config
from tests.test_corrections import correct, funded
from tests.test_daily import service
from tests.test_join import service as joins

from butterbot.infrastructure.persistence.database import DatabaseRuntime, create_database_runtime
from butterbot.infrastructure.persistence.schema_contract import normalize_sql_definition


def schema(path: Path) -> dict[tuple[str, str, str], str]:
    with closing(sqlite3.connect(path)) as db:
        return {
            (kind, name, table): normalize_sql_definition(sql)
            for kind, name, table, sql in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            )
        }


def test_empty_downgrade_exact_prior_manifest(tmp_path: Path) -> None:
    path = tmp_path / "prior.sqlite3"
    config = alembic_config(path)
    command.upgrade(config, "20260930_0008")
    before = schema(path)
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "20260930_0008")
    assert schema(path) == before


async def test_populated_previous_upgrade_preserves_money_and_authority(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    original = await funded(runtime)
    await correct(runtime, original, amount=4)
    await runtime.close()
    config = alembic_config(migrated_database)
    command.downgrade(config, "20260930_0008")
    with closing(sqlite3.connect(migrated_database)) as db:
        names = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
            )
        ]
        before = {name: db.execute(f'SELECT * FROM "{name}"').fetchall() for name in names}
    command.upgrade(config, "head")
    with closing(sqlite3.connect(migrated_database)) as db:
        assert {name: db.execute(f'SELECT * FROM "{name}"').fetchall() for name in names} == before
    runtime = await create_database_runtime(migrated_database)
    try:
        assert (
            await service(runtime).claim(discord_user_id=123, interaction_id=1000, claim_period=0)
        ).balance == 21
    finally:
        await runtime.close()


async def test_populated_daily_downgrade_refused(database_runtime: DatabaseRuntime) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    await service(r).claim(discord_user_id=123, interaction_id=2, claim_period=0)
    await r.close()
    before = schema(r.database_path)
    with pytest.raises(RuntimeError, match="cannot discard committed daily history"):
        command.downgrade(alembic_config(r.database_path), "20260930_0008")
    assert schema(r.database_path) == before
