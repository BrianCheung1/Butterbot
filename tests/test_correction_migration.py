import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL
from tests.test_corrections import correct, funded

from butterbot.infrastructure.persistence.database import DatabaseRuntime, create_database_runtime
from butterbot.infrastructure.persistence.readiness import normalize_sql_definition


async def test_data_bearing_0007_upgrade_preserves_grants_and_authority(
    migrated_database: Path,
) -> None:
    runtime = await create_database_runtime(migrated_database)
    await funded(runtime)
    await runtime.close()
    with closing(sqlite3.connect(migrated_database)) as db, db:
        db.execute("DELETE FROM safety_capabilities WHERE capability LIKE 'corrections.%'")
    config = alembic_config(migrated_database)
    command.downgrade(config, "20260927_0007")
    with closing(sqlite3.connect(migrated_database)) as db:
        names = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
            )
        ]
        before = {n: db.execute(f'SELECT * FROM "{n}"').fetchall() for n in names}
    command.upgrade(config, "head")
    command.check(config)
    with closing(sqlite3.connect(migrated_database)) as db:
        assert {n: db.execute(f'SELECT * FROM "{n}"').fetchall() for n in names} == before
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM economy_corrections").fetchone() == (0,)
    runtime = await create_database_runtime(migrated_database)
    await runtime.close()


async def test_downgrade_refuses_loss_of_committed_corrections(
    database_runtime: DatabaseRuntime,
) -> None:
    original = await funded(database_runtime)
    assert await correct(database_runtime, original) == "corrected"
    await database_runtime.close()
    with pytest.raises(RuntimeError, match="committed correction"):
        command.downgrade(alembic_config(database_runtime.database_path), "20260927_0007")
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM economy_corrections").fetchone() == (1,)


def alembic_config(path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(path)).render_as_string(hide_password=False),
    )
    return config


async def test_downgrade_restores_exact_previous_schema_contract(tmp_path: Path) -> None:
    path = tmp_path / "exact-downgrade.sqlite3"
    config = alembic_config(path)
    command.upgrade(config, "20260927_0007")

    def schema() -> dict[tuple[str, str, str], str]:
        with closing(sqlite3.connect(path)) as db:
            return {
                (kind, name, table): normalize_sql_definition(sql)
                for kind, name, table, sql in db.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master "
                    "WHERE name NOT GLOB 'sqlite_*'"
                )
                if sql is not None
            }

    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO safety_capabilities VALUES (111,'grants.propose')")
    previous = schema()
    command.upgrade(config, "head")
    command.downgrade(config, "20260927_0007")
    assert schema() == previous
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT * FROM safety_capabilities").fetchall() == [
            (111, "grants.propose")
        ]
    command.upgrade(config, "head")
    runtime = await create_database_runtime(path)
    await runtime.close()
