# pyright: reportPrivateUsage=false
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from benchmarks import native_linux_gate

from butterbot.infrastructure.persistence import schema_contract, verification
from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.readiness import DatabaseReadinessError
from butterbot.infrastructure.persistence.release_manifest import RELEASE_SCHEMA_SHA256


@pytest.mark.parametrize(("kind", "name", "table"), list(RELEASE_SCHEMA_SHA256))
async def test_every_release_object_drift_is_rejected(
    migrated_database: Path, kind: str, name: str, table: str
) -> None:
    del table
    with closing(sqlite3.connect(migrated_database)) as db:
        if kind in {"index", "trigger"}:
            db.execute(f'DROP {kind} "{name}"')
        else:
            # Real on-disk same-head schema edit: casing is semantically legal but off-contract.
            db.execute("PRAGMA writable_schema=ON")
            db.execute(
                "UPDATE sqlite_master SET sql=replace(sql, 'CREATE TABLE', 'create table') "
                "WHERE name=?",
                (name,),
            )
            db.execute("PRAGMA schema_version=999")
        db.commit()
    for check in (create_database_runtime, verification._verify_database):
        with pytest.raises(DatabaseReadinessError, match="schema contract"):
            await check(migrated_database)


@pytest.mark.parametrize(
    ("table", "assignment"),
    [
        ("players", "id='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"),
        ("players", "discord_user_id=discord_user_id+100"),
        ("economy_accounts", "id='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"),
        ("economy_accounts", "player_id='00000000000000000000000000000002'"),
        ("economy_accounts", "account_kind='issuance'"),
        ("economy_accounts", "currency_key='other'"),
        ("economy_accounts", "system_key='system.test'"),
        ("economy_account_balances", "account_id='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"),
        ("economy_account_balances", "account_kind='issuance'"),
        ("economy_accounts", "player_id=NULL, account_kind='issuance', system_key='system.test'"),
    ],
)
async def test_identity_mutation_and_rollback(
    migrated_database: Path, table: str, assignment: str
) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        for n in (1, 2):
            player, account = f"{n:032x}", f"{n + 10:032x}"
            db.execute("INSERT INTO players VALUES (?, ?, 1, 'active')", (player, n))
            db.execute(
                "INSERT INTO economy_accounts VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
                (account, player),
            )
            db.execute(
                "INSERT INTO economy_account_balances VALUES (?, 'wallet', 0, 0)", (account,)
            )
        db.commit()
        before = list(db.iterdump())
        db.execute("BEGIN")
        db.execute("UPDATE economy_account_balances SET version=1")
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            db.execute(f"UPDATE {table} SET {assignment}")
        assert db.execute("SELECT sum(version) FROM economy_account_balances").fetchone() == (2,)
        db.rollback()
        assert list(db.iterdump()) == before
        db.execute("DELETE FROM operations_integrity_violations")
        db.commit()
    runtime = await create_database_runtime(migrated_database)
    await runtime.close()
    await verification._verify_database(migrated_database)


def test_frozen_baseline_independent_of_current_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schema_contract, "SQLITE_AGGREGATE_TRIGGER_SQL", {"bad": "INVALID SQL"})
    monkeypatch.setattr(schema_contract, "INTEGRITY_SENTINEL_INDEX", "future_index")
    config = Config("alembic.ini")
    path = tmp_path / "baseline.db"
    config.set_main_option("sqlalchemy.url", "sqlite:///" + path.as_posix())
    command.upgrade(config, "20260825_0001")
    with closing(sqlite3.connect(path)) as db:
        observed = sorted(
            [
                [
                    kind,
                    name,
                    table,
                    hashlib.sha256(
                        schema_contract.normalize_sql_definition(sql).encode()
                    ).hexdigest(),
                ]
                for kind, name, table, sql in db.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%'"
                )
                if sql
            ]
        )
    assert observed == json.loads(Path("tests/baseline_schema_snapshot.json").read_text())
    command.upgrade(config, "head")
    command.downgrade(config, "20260825_0001")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone() == (
            8,
        )


@pytest.mark.parametrize(
    ("outcome", "acceptable"),
    [
        ("", True),
        ("<failure/>", False),
        ("<error/>", False),
        ("<skipped/>", False),
        ("missing", False),
    ],
)
def test_capability_must_be_collected_and_pass(
    tmp_path: Path, outcome: str, acceptable: bool
) -> None:
    path = tmp_path / "junit.xml"
    case = (
        ""
        if outcome == "missing"
        else (
            '<testcase classname="tests.test_native_linux_gate" '
            'name="test_native_unexpected_effective_capability_is_rejected">'
            + outcome
            + "</testcase>"
        )
    )
    path.write_text("<testsuite>" + case + "</testsuite>")
    assert native_linux_gate._parse_junit(path)["capability_test_passed"] is acceptable


@pytest.mark.parametrize(
    ("name", "reason", "allowed"),
    [
        (
            "test_native_separate_network_namespace_is_rejected",
            native_linux_gate.NAMESPACE_SKIP_REASON,
            True,
        ),
        ("test_native_separate_network_namespace_is_rejected", "unshare missing", False),
        (
            "test_native_unexpected_effective_capability_is_rejected",
            native_linux_gate.NAMESPACE_SKIP_REASON,
            False,
        ),
        ("unrelated", "anything", False),
        (
            "test_native_separate_network_namespace_is_rejected_extra",
            native_linux_gate.NAMESPACE_SKIP_REASON,
            False,
        ),
    ],
)
def test_only_documented_namespace_skip_allowed(name: str, reason: str, allowed: bool) -> None:
    assert (
        native_linux_gate._allowed_skip("tests.test_native_linux_gate::" + name, reason) is allowed
    )


async def test_rejected_move_cannot_clear_missing_player_sentinel(migrated_database: Path) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        for n in (1, 2):
            db.execute("INSERT INTO players VALUES (?, ?, 1, 'active')", (f"{n:032x}", n))
        db.execute(
            "INSERT INTO economy_accounts VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
            (f"{11:032x}", f"{1:032x}"),
        )
        db.execute(
            "INSERT INTO economy_account_balances VALUES (?, 'wallet', 0, 0)", (f"{11:032x}",)
        )
        db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE economy_accounts SET player_id=?", (f"{2:032x}",))
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            db.execute("DELETE FROM operations_integrity_violations")
        db.commit()
    for check in (create_database_runtime, verification._verify_database):
        with pytest.raises(DatabaseReadinessError, match="wallet"):
            await check(migrated_database)


@pytest.mark.parametrize(
    "table",
    ["operations_transport_requests", "economy_ledger_postings", "economy_ledger_transactions"],
)
async def test_weakened_constraints_rejected(migrated_database: Path, table: str) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        weakened = sql.replace("CHECK (", "CHECK (1 OR ", 1)
        assert weakened != sql
        db.execute("PRAGMA writable_schema=ON")
        db.execute("UPDATE sqlite_master SET sql=? WHERE name=?", (weakened, table))
        db.execute("PRAGMA schema_version=999")
        db.commit()
    for check in (create_database_runtime, verification._verify_database):
        with pytest.raises(DatabaseReadinessError, match="schema contract"):
            await check(migrated_database)


async def test_same_head_with_baseline_shape_rejected(tmp_path: Path) -> None:
    path = tmp_path / "stale.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite:///" + path.as_posix())
    command.upgrade(config, "20260825_0001")
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE alembic_version SET version_num=?", ("20260924_0005",))
        db.commit()
    for check in (create_database_runtime, verification._verify_database):
        with pytest.raises(DatabaseReadinessError, match="schema contract"):
            await check(path)


async def test_upgrade_records_preexisting_hidden_hole(tmp_path: Path) -> None:
    path = tmp_path / "old-corrupt.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", "sqlite:///" + path.as_posix())
    command.upgrade(config, "20260825_0001")
    with closing(sqlite3.connect(path)) as db:
        for n in (1, 2):
            db.execute("INSERT INTO players VALUES (?, ?, 1, 'active')", (f"{n:032x}", n))
        db.execute(
            "INSERT INTO economy_accounts VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
            (f"{11:032x}", f"{1:032x}"),
        )
        db.execute(
            "INSERT INTO economy_account_balances VALUES (?, 'wallet', 0, 0)", (f"{11:032x}",)
        )
        db.execute("UPDATE economy_accounts SET player_id=?", (f"{2:032x}",))
        db.execute("DELETE FROM operations_integrity_violations")
        db.commit()
        assert db.execute("SELECT count(*) FROM operations_integrity_violations").fetchone() == (0,)
    command.upgrade(config, "head")
    for check in (create_database_runtime, verification._verify_database):
        with pytest.raises(DatabaseReadinessError, match="wallet"):
            await check(path)
