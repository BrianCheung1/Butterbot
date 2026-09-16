from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from butterbot.infrastructure.persistence.database import DatabaseRuntime, create_database_runtime

REPOSITORY_ROOT = Path(__file__).parents[1]


def upgrade_database(database_path: Path) -> None:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(database_path)).render_as_string(
            hide_password=False
        ),
    )
    command.upgrade(config, "head")


@pytest.fixture
def migrated_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "butterbot.sqlite3"
    upgrade_database(database_path)
    return database_path


@pytest.fixture
async def database_runtime(migrated_database: Path) -> AsyncIterator[DatabaseRuntime]:
    runtime = await create_database_runtime(migrated_database)
    try:
        yield runtime
    finally:
        await runtime.close(drain_timeout_seconds=0.1)
