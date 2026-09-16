from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from butterbot.application.economy.audit_identity import (
    LedgerAuditIdentity,
    validate_system_account_key,
)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transaction_kind", ""),
        ("transaction_kind", "Bad Kind"),
        ("actor_kind", ""),
        ("actor_reference", ""),
        ("actor_reference", "   "),
        ("actor_reference", "\t"),
        ("actor_reference", " leading"),
        ("actor_reference", "trailing "),
        ("actor_reference", "bad\0reference"),
        ("reason_code", "unnamespaced"),
        ("reason_code", "Bad.Reason"),
        ("domain_reference", ""),
        ("domain_reference", "   "),
        ("domain_reference", "domain\nreference"),
        ("domain_reference", " domain-reference"),
        ("domain_reference", "domain-reference "),
        ("domain_reference", "bad\0reference"),
        ("content_version", ""),
        ("content_version", "   "),
        ("content_version", "version\treference"),
        ("content_version", " version-1"),
        ("content_version", "version-1 "),
        ("content_version", "bad\0reference"),
    ],
)
def test_application_rejects_malformed_permanent_audit_identity(field: str, value: str) -> None:
    values: dict[str, str | None] = {
        "transaction_kind": "grant",
        "actor_kind": "system",
        "actor_reference": "butterbot",
        "reason_code": "economy.test",
        "domain_reference": None,
        "content_version": None,
    }
    values[field] = value
    with pytest.raises(ValueError):
        LedgerAuditIdentity(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("key", ["", "unnamespaced", "Bad.Key", "bad..key"])
def test_application_rejects_malformed_system_account_key(key: str) -> None:
    with pytest.raises(ValueError):
        validate_system_account_key(key)


def test_application_accepts_visible_ascii_permanent_references() -> None:
    identity = LedgerAuditIdentity(
        transaction_kind="grant",
        actor_kind="system",
        actor_reference="service:butterbot",
        reason_code="economy.test",
        domain_reference="player/123@v1",
        content_version="catalog-2026.09.01",
    )
    assert identity.actor_reference == "service:butterbot"


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("transaction_kind", ""),
        ("transaction_kind", "Bad Kind"),
        ("actor_kind", ""),
        ("actor_reference", ""),
        ("actor_reference", "   "),
        ("actor_reference", "\t"),
        ("actor_reference", " leading"),
        ("actor_reference", "trailing "),
        ("actor_reference", "bad\0reference"),
        ("reason_code", "unnamespaced"),
        ("reason_code", "bad..reason"),
        ("domain_reference", ""),
        ("domain_reference", "   "),
        ("domain_reference", "domain\nreference"),
        ("domain_reference", " domain-reference"),
        ("domain_reference", "domain-reference "),
        ("domain_reference", "bad\0reference"),
        ("content_version", ""),
        ("content_version", "   "),
        ("content_version", "version\treference"),
        ("content_version", " version-1"),
        ("content_version", "version-1 "),
        ("content_version", "bad\0reference"),
    ],
)
def test_schema_rejects_malformed_permanent_audit_identity(
    migrated_database: Path, column: str, value: str
) -> None:
    values: dict[str, str | None] = {
        "transaction_kind": "grant",
        "actor_kind": "system",
        "actor_reference": "butterbot",
        "reason_code": "economy.test",
        "domain_reference": None,
        "content_version": None,
    }
    values[column] = value
    with (
        sqlite3.connect(migrated_database) as connection,
        pytest.raises(sqlite3.IntegrityError, match="CHECK"),
    ):
        connection.execute(
            "INSERT INTO economy_ledger_transactions "
            "(id, transaction_kind, committed_at_ms, actor_kind, actor_reference, "
            "reason_code, correlation_id, domain_reference, content_version) "
            "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex,
                values["transaction_kind"],
                values["actor_kind"],
                values["actor_reference"],
                values["reason_code"],
                uuid4().hex,
                values["domain_reference"],
                values["content_version"],
            ),
        )


@pytest.mark.parametrize("system_key", ["", "unnamespaced", "Bad.Key", "bad..key"])
def test_schema_rejects_malformed_system_account_key(
    migrated_database: Path, system_key: str
) -> None:
    with (
        sqlite3.connect(migrated_database) as connection,
        pytest.raises(sqlite3.IntegrityError, match="CHECK"),
    ):
        connection.execute(
            "INSERT INTO economy_accounts "
            "(id, player_id, account_kind, currency_key, system_key, created_at_ms) "
            "VALUES (?, NULL, 'issuance', 'coin', ?, 1)",
            (uuid4().hex, system_key),
        )
