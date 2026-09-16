from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import URL, engine_from_config, pool

from butterbot.infrastructure.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configured_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url").strip()
    if configured_url:
        return configured_url
    database_path = os.getenv("BUTTERBOT_DATABASE_PATH")
    if database_path is None:
        raise RuntimeError(
            "migration target requires an explicit sqlalchemy.url or BUTTERBOT_DATABASE_PATH"
        )
    path = Path(database_path)
    if not path.is_absolute():
        raise RuntimeError("BUTTERBOT_DATABASE_PATH must be absolute")
    return URL.create("sqlite+pysqlite", database=str(path)).render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=_configured_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _configured_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("PRAGMA synchronous=FULL")
        connection.exec_driver_sql("PRAGMA busy_timeout=1000")
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()
        if str(journal_mode).lower() != "wal":
            raise RuntimeError("SQLite refused the required WAL journal mode")
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
