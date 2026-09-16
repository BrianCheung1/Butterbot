# pyright: reportPrivateUsage=false
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.readiness import DatabaseReadinessError
from butterbot.infrastructure.persistence.verification import _verify_database


def _config(path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite:///" + path.as_posix())
    return config


def _seed(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys=ON")
    for n in (1, 2):
        db.execute("INSERT INTO players VALUES (?, ?, 1, 'active')", (f"{n:032x}", n))
        db.execute(
            "INSERT INTO economy_accounts VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
            (f"{n + 10:032x}", f"{n:032x}"),
        )
        db.execute(
            "INSERT INTO economy_account_balances VALUES (?, 'wallet', ?, 0)",
            (f"{n + 10:032x}", 25 if n == 1 else 0),
        )
    db.execute(
        "INSERT INTO economy_accounts VALUES (?, NULL, 'issuance', 'coin', 'test.issue', 1)",
        (f"{13:032x}",),
    )
    db.execute(
        "INSERT INTO economy_account_balances VALUES (?, 'issuance', -25, 0)", (f"{13:032x}",)
    )
    db.commit()


@pytest.mark.parametrize("recursive", [0, 1])
@pytest.mark.parametrize(
    "operation",
    [
        "REPLACE INTO players VALUES ('00000000000000000000000000000001', 100, 1, 'active')",
        "REPLACE INTO players VALUES ('00000000000000000000000000000003', 1, 1, 'active')",
        "REPLACE INTO economy_accounts VALUES ('0000000000000000000000000000000b', "
        "'00000000000000000000000000000002', 'wallet', 'coin', NULL, 1)",
        "REPLACE INTO economy_accounts VALUES ('0000000000000000000000000000000e', "
        "'00000000000000000000000000000001', 'wallet', 'coin', NULL, 1)",
        "REPLACE INTO economy_accounts VALUES ('0000000000000000000000000000000e', "
        "NULL, 'issuance', 'coin', 'test.issue', 1)",
        "INSERT OR REPLACE INTO economy_account_balances "
        "VALUES ('0000000000000000000000000000000b', 'wallet', 100, 0)",
        "INSERT INTO players VALUES ('00000000000000000000000000000001', 1, 1, 'active') "
        "ON CONFLICT DO NOTHING",
        "INSERT INTO players VALUES ('00000000000000000000000000000001', 1, 1, 'active') "
        "ON CONFLICT(id) DO UPDATE SET discord_user_id=100",
    ],
)
def test_every_aggregate_conflict_rejects_before_replacement(
    migrated_database: Path,
    recursive: int,
    operation: str,
) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        _seed(db)
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        before = list(db.iterdump())
        db.execute("BEGIN")
        db.execute("UPDATE economy_account_balances SET version=1")
        db.execute("SAVEPOINT review")
        with pytest.raises(sqlite3.IntegrityError, match="aggregate replacement is forbidden"):
            db.execute(operation)
        assert db.execute("SELECT sum(version) FROM economy_account_balances").fetchone() == (3,)
        db.execute("ROLLBACK TO review")
        db.execute("RELEASE review")
        db.rollback()
        assert list(db.iterdump()) == before
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


async def test_reported_replacement_hole_is_blocked_and_rollback_restores_startup(
    migrated_database: Path,
) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        _seed(db)
        before = list(db.iterdump())
        db.execute("BEGIN")
        db.execute("DELETE FROM economy_account_balances WHERE account_kind='wallet'")
        db.execute("DELETE FROM economy_accounts WHERE id=?", (f"{12:032x}",))
        with pytest.raises(sqlite3.IntegrityError, match="replacement is forbidden"):
            db.execute(
                "INSERT OR REPLACE INTO economy_accounts VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
                (f"{11:032x}", f"{2:032x}"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            db.execute("DELETE FROM operations_integrity_violations")
        db.rollback()
        assert list(db.iterdump()) == before
    runtime = await create_database_runtime(migrated_database)
    await runtime.close()
    await _verify_database(migrated_database)


def test_multirow_conflict_aborts_prior_rows_in_same_statement(migrated_database: Path) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        _seed(db)
        before = list(db.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="replacement is forbidden"):
            db.execute(
                "INSERT OR REPLACE INTO players VALUES (?, 3, 1, 'active'), (?, 1, 1, 'active')",
                (f"{3:032x}", f"{4:032x}"),
            )
        db.commit()
        assert list(db.iterdump()) == before


@pytest.mark.parametrize("kind", ["TABLE", "INDEX", "VIEW", "TRIGGER"])
@pytest.mark.parametrize("name", ["sqliteXuncontracted", "SQLiteXuncontracted", "sqlite1extra"])
async def test_legal_near_internal_prefix_objects_are_rejected(
    migrated_database: Path,
    kind: str,
    name: str,
) -> None:
    definitions = {
        "TABLE": f"CREATE TABLE {name} (id INTEGER)",
        "INDEX": f"CREATE INDEX {name} ON players(created_at_ms)",
        "VIEW": f"CREATE VIEW {name} AS SELECT id FROM players",
        "TRIGGER": (
            f"CREATE TRIGGER {name} BEFORE INSERT ON players "
            "BEGIN SELECT RAISE(ABORT, 'extra'); END"
        ),
    }
    with closing(sqlite3.connect(migrated_database)) as db:
        db.execute(definitions[kind])
        db.commit()
    for check in (create_database_runtime, _verify_database):
        with pytest.raises(DatabaseReadinessError, match="schema contract"):
            await check(migrated_database)


async def test_upgrade_records_old_replace_hole_without_recreating_money(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    config = _config(path)
    command.upgrade(config, "20260914_0002")
    with closing(sqlite3.connect(path)) as db:
        _seed(db)
        db.execute("DELETE FROM economy_account_balances WHERE account_kind='wallet'")
        db.execute("DELETE FROM economy_accounts WHERE id=?", (f"{12:032x}",))
        db.execute(
            "INSERT OR REPLACE INTO economy_accounts VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
            (f"{11:032x}", f"{2:032x}"),
        )
        db.execute(
            "INSERT INTO economy_account_balances VALUES (?, 'wallet', 25, 0)", (f"{11:032x}",)
        )
        db.execute("DELETE FROM operations_integrity_violations")
        db.commit()
        before = db.execute("SELECT * FROM economy_account_balances").fetchall()
        assert db.execute("SELECT * FROM operations_integrity_violations").fetchall() == []
        # A DDL failure must roll back reconstructed sentinels and the head update.
        db.execute(
            "CREATE TRIGGER trg_players_reject_conflicting_insert BEFORE INSERT ON players "
            "BEGIN SELECT 1; END"
        )
        db.commit()
    from sqlalchemy.exc import OperationalError

    with pytest.raises(OperationalError, match="already exists"):
        command.upgrade(config, "head")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260914_0002",
        )
        assert db.execute("SELECT * FROM operations_integrity_violations").fetchall() == []
        db.execute("DROP TRIGGER trg_players_reject_conflicting_insert")
        db.commit()
    command.upgrade(config, "head")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT * FROM economy_account_balances").fetchall() == before
        assert db.execute("SELECT * FROM operations_integrity_violations").fetchall() == [
            ("player_without_wallet", f"{1:032x}"),
        ]
    for check in (create_database_runtime, _verify_database):
        with pytest.raises(DatabaseReadinessError, match="wallet"):
            await check(path)


async def test_stale_second_revision_cannot_be_stamped_as_current(tmp_path: Path) -> None:
    path = tmp_path / "stale.db"
    command.upgrade(_config(path), "20260914_0002")
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE alembic_version SET version_num='20260914_0003'")
        db.commit()
    for check in (create_database_runtime, _verify_database):
        with pytest.raises(DatabaseReadinessError, match="schema contract"):
            await check(path)


async def test_data_bearing_downgrade_upgrade_preserves_aggregates(migrated_database: Path) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        _seed(db)
        before = list(db.iterdump())
    config = _config(migrated_database)
    command.downgrade(config, "20260914_0002")
    command.upgrade(config, "head")
    with closing(sqlite3.connect(migrated_database)) as db:
        assert list(db.iterdump()) == before
    runtime = await create_database_runtime(migrated_database)
    await runtime.close()
    await _verify_database(migrated_database)
