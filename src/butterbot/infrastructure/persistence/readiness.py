from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from butterbot.infrastructure.persistence.release_manifest import RELEASE_SCHEMA_SHA256
from butterbot.infrastructure.persistence.schema_contract import normalize_sql_definition
from butterbot.infrastructure.persistence.storage import (
    DatabaseStorageContract,
    UnsafeDatabaseStorage,
    ValidatedDatabaseStorage,
    validate_database_storage,
)

EXPECTED_SCHEMA_REVISION = "20260924_0005"


class DatabaseReadinessError(RuntimeError):
    def __init__(
        self,
        category: str,
        message: str,
        *,
        expected_revision: str = EXPECTED_SCHEMA_REVISION,
        observed_revision: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.expected_revision = expected_revision
        self.observed_revision = observed_revision


@dataclass(frozen=True, slots=True)
class RevisionContract:
    expected: str = EXPECTED_SCHEMA_REVISION
    known_behind: frozenset[str] = frozenset()
    known_ahead: frozenset[str] = frozenset()
    known_incompatible: frozenset[str] = frozenset()


DEFAULT_REVISION_CONTRACT = RevisionContract()


@dataclass(frozen=True, slots=True)
class SchemaReadinessReport:
    database_path: Path
    expected_revision: str
    observed_revision: str
    foreign_keys: int
    journal_mode: str
    synchronous: int
    busy_timeout_ms: int
    quick_check: str
    foreign_key_violations: int | None
    free_bytes: int
    free_percent: float
    filesystem: str | None
    volume_id: str


def validate_database_file(
    database_path: Path,
    storage_contract: DatabaseStorageContract | None = None,
) -> ValidatedDatabaseStorage:
    contract = storage_contract or DatabaseStorageContract(database_path.parent)
    try:
        return validate_database_storage(database_path, contract)
    except UnsafeDatabaseStorage as error:
        raise DatabaseReadinessError(error.category, str(error)) from error


async def check_schema_readiness(
    engine: AsyncEngine,
    database_path: Path,
    *,
    storage: ValidatedDatabaseStorage | None = None,
    storage_contract: DatabaseStorageContract | None = None,
    revision_contract: RevisionContract = DEFAULT_REVISION_CONTRACT,
) -> SchemaReadinessReport:
    validated_storage = storage or validate_database_file(database_path, storage_contract)
    try:
        async with engine.connect() as connection:
            quick_check = "deferred_offline"

            foreign_keys = int((await connection.execute(text("PRAGMA foreign_keys"))).scalar_one())
            journal_mode = str(
                (await connection.execute(text("PRAGMA journal_mode"))).scalar_one()
            ).lower()
            synchronous = int((await connection.execute(text("PRAGMA synchronous"))).scalar_one())
            busy_timeout_ms = int(
                (await connection.execute(text("PRAGMA busy_timeout"))).scalar_one()
            )
            if foreign_keys != 1 or journal_mode != "wal" or synchronous != 2:
                raise DatabaseReadinessError(
                    "unsafe_pragmas",
                    "required SQLite durability pragmas are not effective",
                    expected_revision=revision_contract.expected,
                )
            if busy_timeout_ms != 1_000:
                raise DatabaseReadinessError(
                    "unsafe_pragmas",
                    "SQLite busy_timeout must be exactly 1000 ms",
                    expected_revision=revision_contract.expected,
                )

            alembic_table = await connection.scalar(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
                )
            )
            if alembic_table is None:
                raise DatabaseReadinessError(
                    "missing_schema",
                    "database has no Alembic version table",
                    expected_revision=revision_contract.expected,
                )
            revision_rows = (
                (await connection.execute(text("SELECT version_num FROM alembic_version")))
                .scalars()
                .all()
            )
            if len(revision_rows) != 1:
                raise DatabaseReadinessError(
                    "multiple_or_missing_heads",
                    "database must contain exactly one Alembic revision",
                    expected_revision=revision_contract.expected,
                )
            observed = str(revision_rows[0])
            _verify_revision(observed, revision_contract)
            await _verify_integrity_schema_contract(connection, revision_contract)
            incomplete_request = await connection.scalar(
                text(
                    "SELECT id FROM operations_transport_requests "
                    "WHERE retain_until_ms IS NULL LIMIT 1"
                )
            )
            if incomplete_request is not None:
                raise DatabaseReadinessError(
                    "incomplete_transport_request",
                    "database contains a committed transport request without an outcome",
                    expected_revision=revision_contract.expected,
                )
            aggregate_violation = (
                await connection.execute(
                    text(
                        "SELECT violation_kind, aggregate_id "
                        "FROM operations_integrity_violations LIMIT 1"
                    )
                )
            ).one_or_none()
            if (
                aggregate_violation is not None
                and aggregate_violation[0] == "account_without_balance"
            ):
                raise DatabaseReadinessError(
                    "missing_balance_projection",
                    "a persisted economy account has no required balance projection",
                    expected_revision=revision_contract.expected,
                )
            if aggregate_violation is not None:
                raise DatabaseReadinessError(
                    "missing_player_wallet",
                    "a persisted player has no required wallet account",
                    expected_revision=revision_contract.expected,
                )
    except DatabaseReadinessError:
        raise
    except (DBAPIError, SQLAlchemyError, OSError, ValueError) as error:
        raise DatabaseReadinessError(
            "corrupt_or_unreadable",
            "database readiness checks could not complete safely",
            expected_revision=revision_contract.expected,
        ) from error

    return SchemaReadinessReport(
        database_path=database_path,
        expected_revision=revision_contract.expected,
        observed_revision=observed,
        foreign_keys=foreign_keys,
        journal_mode=journal_mode,
        synchronous=synchronous,
        busy_timeout_ms=busy_timeout_ms,
        quick_check=quick_check,
        foreign_key_violations=None,
        free_bytes=validated_storage.free_bytes,
        free_percent=validated_storage.free_percent,
        filesystem=validated_storage.filesystem,
        volume_id=validated_storage.volume_id,
    )


def _verify_revision(observed: str, contract: RevisionContract) -> None:
    if observed == contract.expected:
        return
    if observed in contract.known_behind:
        category = "schema_behind"
    elif observed in contract.known_ahead:
        category = "schema_ahead"
    elif observed in contract.known_incompatible:
        category = "schema_incompatible"
    else:
        category = "schema_unknown"
    raise DatabaseReadinessError(
        category,
        f"database revision {observed!r} is not compatible with this release",
        expected_revision=contract.expected,
        observed_revision=observed,
    )


async def _verify_integrity_schema_contract(
    connection: AsyncConnection,
    revision_contract: RevisionContract,
) -> None:
    """Compare the release contract in work bounded solely by schema object count."""
    rows = (
        await connection.execute(
            text(
                "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            )
        )
    ).all()
    observed = {
        (str(row[0]), str(row[1]), str(row[2])): hashlib.sha256(
            normalize_sql_definition(str(row[3])).encode("utf-8")
        ).hexdigest()
        for row in rows
        if row[3] is not None
    }
    if observed != RELEASE_SCHEMA_SHA256:
        _raise_integrity_schema_contract(
            "release schema contract is missing or altered", revision_contract
        )


def _raise_integrity_schema_contract(
    message: str,
    revision_contract: RevisionContract,
) -> NoReturn:
    raise DatabaseReadinessError(
        "integrity_schema_contract",
        message,
        expected_revision=revision_contract.expected,
        observed_revision=revision_contract.expected,
    )
