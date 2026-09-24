from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL

from butterbot.infrastructure.persistence.readiness import EXPECTED_SCHEMA_REVISION
from butterbot.infrastructure.persistence.schema_contract import SQLITE_AGGREGATE_TRIGGER_SQL

EXPECTED_TABLES = {
    "alembic_version",
    "players",
    "economy_accounts",
    "economy_account_balances",
    "economy_ledger_transactions",
    "economy_ledger_postings",
    "operations_transport_requests",
    "operations_integrity_violations",
    "safety_bootstrap",
    "safety_capabilities",
    "safety_restrictions",
    "safety_proposals",
    "safety_proposal_targets",
    "safety_access_audit",
}
REPOSITORY_ROOT = Path(__file__).parents[1]


def _alembic_config(database_path: Path) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(database_path)).render_as_string(
            hide_password=False
        ),
    )
    return config


def test_clean_upgrade_creates_expected_release_tables(
    migrated_database: Path,
) -> None:
    connection = sqlite3.connect(migrated_database)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            if not str(row[0]).startswith("sqlite_")
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
    finally:
        connection.close()

    assert tables == EXPECTED_TABLES
    assert revision == (EXPECTED_SCHEMA_REVISION,)
    assert journal_mode == ("wal",)


def test_baseline_installs_aggregate_completeness_triggers(migrated_database: Path) -> None:
    with sqlite3.connect(migrated_database) as connection:
        triggers = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
    from butterbot.infrastructure.persistence.release_manifest import RELEASE_SCHEMA_SHA256

    assert triggers == {name for kind, name, _ in RELEASE_SCHEMA_SHA256 if kind == "trigger"}
    assert (
        set(SQLITE_AGGREGATE_TRIGGER_SQL)
        | {
            "trg_players_reject_conflicting_insert",
            "trg_accounts_reject_conflicting_insert",
            "trg_balances_reject_conflicting_insert",
            "trg_players_immutable_identity",
            "trg_economy_accounts_immutable_identity",
            "trg_economy_account_balances_immutable_identity",
        }
        <= triggers
    )


def test_baseline_constraints_cover_identity_wallet_and_ledger_integrity(
    migrated_database: Path,
) -> None:
    connection = sqlite3.connect(migrated_database)
    connection.execute("PRAGMA foreign_keys=ON")
    player_id = uuid4().hex
    wallet_id = uuid4().hex
    transaction_id = uuid4().hex
    try:
        connection.execute(
            "INSERT INTO players(id, discord_user_id, created_at_ms, lifecycle_state) "
            "VALUES (?, 10, 1, 'active')",
            (player_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO players(id, discord_user_id, created_at_ms, lifecycle_state) "
                "VALUES (?, 10, 1, 'active')",
                (uuid4().hex,),
            )
        connection.execute(
            "INSERT INTO economy_accounts"
            "(id, player_id, account_kind, currency_key, system_key, created_at_ms) "
            "VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
            (wallet_id, player_id),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO economy_accounts"
                "(id, player_id, account_kind, currency_key, system_key, created_at_ms) "
                "VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
                (uuid4().hex, player_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO economy_account_balances"
                "(account_id, account_kind, amount, version) VALUES (?, 'wallet', -1, 0)",
                (wallet_id,),
            )
        connection.execute(
            "INSERT INTO economy_account_balances"
            "(account_id, account_kind, amount, version) VALUES (?, 'wallet', 0, 0)",
            (wallet_id,),
        )
        connection.execute(
            "INSERT INTO economy_ledger_transactions"
            "(id, transaction_kind, committed_at_ms, actor_kind, actor_reference, reason_code, "
            "correlation_id) VALUES (?, 'test', 1, 'system', 'test', 'test.reason', ?)",
            (transaction_id, uuid4().hex),
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO economy_ledger_postings(transaction_id, account_id, amount) "
                "VALUES (?, ?, 0)",
                (transaction_id, wallet_id),
            )
    finally:
        connection.close()


def test_foreign_keys_reject_orphaned_wallet(migrated_database: Path) -> None:
    connection = sqlite3.connect(migrated_database)
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                "INSERT INTO economy_accounts"
                "(id, player_id, account_kind, currency_key, system_key, created_at_ms) "
                "VALUES (?, ?, 'wallet', 'coin', NULL, 1)",
                (uuid4().hex, uuid4().hex),
            )
    finally:
        connection.close()


def test_baseline_downgrades_and_reupgrades_cleanly(migrated_database: Path) -> None:
    config = _alembic_config(migrated_database)
    command.downgrade(config, "base")
    connection = sqlite3.connect(migrated_database)
    try:
        assert {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            if not str(row[0]).startswith("sqlite_")
        } == {"alembic_version"}
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() is None
    finally:
        connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(migrated_database)
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            EXPECTED_SCHEMA_REVISION,
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("namespace", ""),
        ("namespace", "n" * 101),
        ("namespace", "operations"),
        ("namespace", "Operations.test"),
        ("namespace", "operations..test"),
        ("namespace", "operations.1test"),
        ("namespace", "operations.test-key"),
        ("namespace", "operations.test\x00hidden"),
        ("transport_key", ""),
        ("transport_key", "k" * 256),
        ("transport_key", "key\x00hidden"),
        ("actor_kind", ""),
        ("actor_kind", "a" * 33),
        ("actor_kind", "Discord_user"),
        ("actor_kind", "1discord_user"),
        ("actor_kind", "discord..user"),
        ("actor_kind", "discord.1user"),
        ("actor_kind", "discord-user"),
        ("actor_kind", "discord\x00user"),
        ("actor_reference", ""),
        ("actor_reference", "   "),
        ("actor_reference", "\t"),
        ("actor_reference", " leading"),
        ("actor_reference", "trailing "),
        ("actor_reference", "a" * 256),
        ("actor_reference", "123\x00hidden"),
        ("request_fingerprint", "f" * 63),
        ("request_fingerprint", "f" * 65),
        ("request_fingerprint", "F" * 64),
        ("request_fingerprint", "g" * 64),
        ("request_fingerprint", "f" * 63 + "\x00"),
    ],
)
def test_transport_identity_length_constraints(
    migrated_database: Path,
    column: str,
    value: str,
) -> None:
    values = {
        "namespace": "operations.test",
        "transport_key": "key",
        "actor_kind": "discord_user",
        "actor_reference": "123",
        "request_fingerprint": "f" * 64,
    }
    values[column] = value
    connection = sqlite3.connect(migrated_database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO operations_transport_requests"
                "(id, namespace, transport_key, actor_kind, actor_reference, "
                "request_fingerprint) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid4().hex,
                    values["namespace"],
                    values["transport_key"],
                    values["actor_kind"],
                    values["actor_reference"],
                    values["request_fingerprint"],
                ),
            )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "outcome_code",
    [
        "",
        "x" * 101,
        "Test.applied",
        "1test.applied",
        "test..applied",
        "test.1applied",
        "test-applied",
        "test.applied\x00hidden",
    ],
)
def test_transport_outcome_code_length_constraint(
    migrated_database: Path,
    outcome_code: str,
) -> None:
    connection = sqlite3.connect(migrated_database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO operations_transport_requests"
                "(id, namespace, transport_key, actor_kind, actor_reference, "
                "request_fingerprint, outcome_kind, outcome_code, outcome_payload, "
                "completed_at_ms, retain_until_ms) "
                "VALUES (?, 'operations.test', 'key', 'discord_user', '123', ?, "
                "'success', ?, '{}', 1, 2)",
                (uuid4().hex, "f" * 64, outcome_code),
            )
    finally:
        connection.close()


def test_programmatic_migration_url_wins_over_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intended = tmp_path / "intended.sqlite3"
    ambient = tmp_path / "ambient.sqlite3"
    sqlite3.connect(ambient).close()
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(ambient))

    command.upgrade(_alembic_config(intended), "head")

    intended_connection = sqlite3.connect(intended)
    ambient_connection = sqlite3.connect(ambient)
    try:
        assert intended_connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (EXPECTED_SCHEMA_REVISION,)
        assert (
            ambient_connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'alembic_version'"
            ).fetchone()
            is None
        )
    finally:
        intended_connection.close()
        ambient_connection.close()
