import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.readiness import EXPECTED_SCHEMA_REVISION


@pytest.mark.parametrize("prior", ["20260825_0001", "20260914_0002", "20260914_0003"])
async def test_safety_upgrade_preserves_existing_aggregate_and_transport(
    prior: str, tmp_path: Path
) -> None:
    path = tmp_path / "upgrade.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(path)).render_as_string(hide_password=False),
    )
    command.upgrade(config, prior)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO players VALUES (?,123,1,'active')", (f"{1:032x}",))
        db.execute(
            "INSERT INTO economy_accounts VALUES (?,?,'wallet','coin',NULL,1)",
            (f"{2:032x}", f"{1:032x}"),
        )
        db.execute("INSERT INTO economy_account_balances VALUES (?,'wallet',37,4)", (f"{2:032x}",))
        tables = (
            "players",
            "economy_accounts",
            "economy_account_balances",
            "operations_transport_requests",
        )
        before = {name: db.execute(f"SELECT * FROM {name}").fetchall() for name in tables}
    command.upgrade(config, "head")
    command.check(config)
    with closing(sqlite3.connect(path)) as db:
        assert {name: db.execute(f"SELECT * FROM {name}").fetchall() for name in tables} == before
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            EXPECTED_SCHEMA_REVISION,
        )
        assert db.execute("SELECT COUNT(*) FROM safety_bootstrap").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM safety_capabilities").fetchone() == (0,)
    runtime = await create_database_runtime(path)
    await runtime.close()
