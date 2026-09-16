"""Slice 1.0 persistence and composition baseline.

Revision ID: 20260825_0001
Revises:
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Frozen historical DDL: never import the current runtime contract.
INTEGRITY_SENTINEL_INDEX = "ix_operations_integrity_violations_aggregate_id"
SQLITE_AGGREGATE_TRIGGER_SQL = {
    "trg_players_require_wallet_after_insert": """
CREATE TRIGGER trg_players_require_wallet_after_insert
        AFTER INSERT ON players BEGIN
          INSERT OR IGNORE INTO operations_integrity_violations(violation_kind, aggregate_id)
          VALUES ('player_without_wallet', NEW.id);
        END
    """,
    "trg_players_integrity_after_delete": """
CREATE TRIGGER trg_players_integrity_after_delete
        AFTER DELETE ON players BEGIN
          DELETE FROM operations_integrity_violations
          WHERE violation_kind = 'player_without_wallet' AND aggregate_id = OLD.id;
        END
    """,
    "trg_accounts_require_balance_after_insert": """
CREATE TRIGGER trg_accounts_require_balance_after_insert
        AFTER INSERT ON economy_accounts BEGIN
          INSERT OR IGNORE INTO operations_integrity_violations(violation_kind, aggregate_id)
          VALUES ('account_without_balance', NEW.id);
          DELETE FROM operations_integrity_violations
          WHERE violation_kind = 'player_without_wallet'
            AND aggregate_id = NEW.player_id AND NEW.account_kind = 'wallet';
        END
    """,
    "trg_accounts_integrity_after_delete": """
CREATE TRIGGER trg_accounts_integrity_after_delete
        AFTER DELETE ON economy_accounts BEGIN
          DELETE FROM operations_integrity_violations
          WHERE violation_kind = 'account_without_balance' AND aggregate_id = OLD.id;
          INSERT OR IGNORE INTO operations_integrity_violations(violation_kind, aggregate_id)
          SELECT 'player_without_wallet', OLD.player_id
          WHERE OLD.account_kind = 'wallet' AND OLD.player_id IS NOT NULL
            AND EXISTS (SELECT 1 FROM players WHERE id = OLD.player_id);
        END
    """,
    "trg_balances_complete_account_after_insert": """
CREATE TRIGGER trg_balances_complete_account_after_insert
        AFTER INSERT ON economy_account_balances BEGIN
          DELETE FROM operations_integrity_violations
          WHERE violation_kind = 'account_without_balance' AND aggregate_id = NEW.account_id;
        END
    """,
    "trg_balances_integrity_after_delete": """
CREATE TRIGGER trg_balances_integrity_after_delete
        AFTER DELETE ON economy_account_balances BEGIN
          INSERT OR IGNORE INTO operations_integrity_violations(violation_kind, aggregate_id)
          SELECT 'account_without_balance', OLD.account_id
          WHERE EXISTS (SELECT 1 FROM economy_accounts WHERE id = OLD.account_id);
        END
    """,
    "trg_integrity_violations_protect_active_delete": """
CREATE TRIGGER trg_integrity_violations_protect_active_delete
        BEFORE DELETE ON operations_integrity_violations
        WHEN (
          OLD.violation_kind = 'player_without_wallet'
          AND EXISTS (SELECT 1 FROM players WHERE id = OLD.aggregate_id)
          AND NOT EXISTS (
            SELECT 1 FROM economy_accounts
            WHERE player_id = OLD.aggregate_id AND account_kind = 'wallet'
          )
        ) OR (
          OLD.violation_kind = 'account_without_balance'
          AND EXISTS (SELECT 1 FROM economy_accounts WHERE id = OLD.aggregate_id)
          AND NOT EXISTS (
            SELECT 1 FROM economy_account_balances WHERE account_id = OLD.aggregate_id
          )
        ) BEGIN
          SELECT RAISE(ABORT, 'active aggregate integrity violation cannot be deleted');
        END
    """,
    "trg_integrity_violations_protect_update": """
CREATE TRIGGER trg_integrity_violations_protect_update
        BEFORE UPDATE ON operations_integrity_violations BEGIN
          SELECT RAISE(ABORT, 'aggregate integrity violation rows are immutable');
        END
    """,
}

revision: str = "20260825_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sqlite_check(expression: str, name: str) -> list[sa.CheckConstraint]:
    if op.get_bind().dialect.name != "sqlite":
        return []
    return [sa.CheckConstraint(expression, name=name)]


def _sqlite_uuid(column: str, *, nullable: bool = False) -> list[sa.CheckConstraint]:
    valid = (
        f"typeof({column}) = 'text' AND length({column}) = 32 "
        f"AND {column} = lower({column}) AND {column} NOT GLOB '*[^0-9a-f]*'"
    )
    if nullable:
        valid = f"{column} IS NULL OR ({valid})"
    return _sqlite_check(valid, f"ck_sqlite_{column}_uuid")


def _sqlite_integer(column: str, *, nullable: bool = False) -> list[sa.CheckConstraint]:
    valid = f"typeof({column}) = 'integer'"
    if nullable:
        valid = f"{column} IS NULL OR {valid}"
    return _sqlite_check(valid, f"ck_sqlite_{column}_integer")


def _sqlite_reference(
    column: str,
    *,
    maximum: int = 255,
    nullable: bool = False,
) -> str:
    valid = (
        f"length({column}) BETWEEN 1 AND {maximum} "
        f"AND instr({column}, char(0)) = 0 "
        f"AND {column} NOT GLOB '*[^!-~]*'"
    )
    if nullable:
        return f"{column} IS NULL OR ({valid})"
    return valid


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=24), nullable=False),
        sa.CheckConstraint("discord_user_id >= 0", name="ck_players_discord_user_id_nonnegative"),
        sa.CheckConstraint(
            "lifecycle_state IN ('active', 'pseudonymized')",
            name="ck_players_lifecycle_state",
        ),
        *_sqlite_uuid("id"),
        *_sqlite_integer("discord_user_id"),
        *_sqlite_integer("created_at_ms"),
        sa.PrimaryKeyConstraint("id", name="pk_players"),
        sa.UniqueConstraint("discord_user_id", name="uq_players_discord_user_id"),
    )
    op.create_table(
        "operations_transport_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=100), nullable=False),
        sa.Column("transport_key", sa.String(length=255), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_reference", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("outcome_kind", sa.String(length=24), nullable=True),
        sa.Column("outcome_code", sa.String(length=100), nullable=True),
        sa.Column("outcome_payload", sa.Text(), nullable=True),
        sa.Column("completed_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("retain_until_ms", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "length(namespace) BETWEEN 3 AND 100 "
            "AND instr(namespace, char(0)) = 0 "
            "AND namespace = lower(namespace) "
            "AND namespace GLOB '[a-z]*.[a-z]*' "
            "AND namespace NOT GLOB '*[^a-z0-9_.]*' "
            "AND namespace NOT GLOB '*.[^a-z]*' "
            "AND namespace NOT LIKE '%..%' "
            "AND namespace NOT LIKE '%.'",
            name="ck_operations_transport_requests_namespace_length",
        ),
        sa.CheckConstraint(
            "length(transport_key) BETWEEN 1 AND 255 AND instr(transport_key, char(0)) = 0",
            name="ck_operations_transport_requests_key_length",
        ),
        sa.CheckConstraint(
            "length(actor_kind) BETWEEN 1 AND 32 "
            "AND instr(actor_kind, char(0)) = 0 "
            "AND actor_kind = lower(actor_kind) "
            "AND actor_kind GLOB '[a-z]*' "
            "AND actor_kind NOT GLOB '*[^a-z0-9_.]*' "
            "AND actor_kind NOT GLOB '*.[^a-z]*' "
            "AND actor_kind NOT LIKE '%..%' "
            "AND actor_kind NOT LIKE '%.'",
            name="ck_operations_transport_requests_actor_kind_length",
        ),
        sa.CheckConstraint(
            _sqlite_reference("actor_reference"),
            name="ck_operations_transport_requests_actor_reference_length",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64 "
            "AND instr(request_fingerprint, char(0)) = 0 "
            "AND request_fingerprint = lower(request_fingerprint) "
            "AND request_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_operations_transport_requests_fingerprint_length",
        ),
        sa.CheckConstraint(
            "outcome_code IS NULL OR ("
            "length(outcome_code) BETWEEN 1 AND 100 "
            "AND instr(outcome_code, char(0)) = 0 "
            "AND outcome_code = lower(outcome_code) "
            "AND outcome_code GLOB '[a-z]*' "
            "AND outcome_code NOT GLOB '*[^a-z0-9_.]*' "
            "AND outcome_code NOT GLOB '*.[^a-z]*' "
            "AND outcome_code NOT LIKE '%..%' "
            "AND outcome_code NOT LIKE '%.')",
            name="ck_operations_transport_requests_outcome_code_length",
        ),
        sa.CheckConstraint(
            "(outcome_kind IS NULL AND outcome_code IS NULL AND outcome_payload IS NULL "
            "AND completed_at_ms IS NULL AND retain_until_ms IS NULL) OR "
            "(outcome_kind IN ('success', 'typed_rejection') AND outcome_code IS NOT NULL "
            "AND outcome_payload IS NOT NULL AND completed_at_ms IS NOT NULL "
            "AND retain_until_ms > completed_at_ms)",
            name="ck_operations_transport_requests_completion",
        ),
        *_sqlite_check(
            "outcome_payload IS NULL OR CASE WHEN json_valid(outcome_payload) "
            "THEN json_type(outcome_payload) = 'object' ELSE 0 END",
            "ck_operations_transport_requests_outcome_payload_json_object",
        ),
        *_sqlite_uuid("id"),
        *_sqlite_integer("completed_at_ms", nullable=True),
        *_sqlite_integer("retain_until_ms", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_operations_transport_requests"),
        sa.UniqueConstraint(
            "namespace",
            "transport_key",
            name="uq_operations_transport_requests_namespace_key",
        ),
    )
    op.create_index(
        "ix_operations_transport_requests_retain_until",
        "operations_transport_requests",
        ["retain_until_ms"],
    )
    op.create_table(
        "economy_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=True),
        sa.Column("account_kind", sa.String(length=24), nullable=False),
        sa.Column("currency_key", sa.String(length=32), nullable=False),
        sa.Column("system_key", sa.String(length=100), nullable=True),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("currency_key = 'coin'", name="ck_economy_accounts_currency"),
        sa.CheckConstraint(
            "(account_kind = 'wallet' AND player_id IS NOT NULL AND system_key IS NULL) OR "
            "(account_kind IN ('issuance', 'retirement') AND player_id IS NULL "
            "AND system_key IS NOT NULL)",
            name="ck_economy_accounts_owner_kind",
        ),
        *_sqlite_check(
            "system_key IS NULL OR (length(system_key) BETWEEN 3 AND 100 "
            "AND instr(system_key, char(0)) = 0 AND system_key = lower(system_key) "
            "AND system_key GLOB '[a-z]*.[a-z]*' "
            "AND system_key NOT GLOB '*[^a-z0-9_.]*' "
            "AND system_key NOT GLOB '*.[^a-z]*' "
            "AND system_key NOT LIKE '%..%' AND system_key NOT LIKE '%.')",
            "ck_economy_accounts_system_key",
        ),
        *_sqlite_uuid("id"),
        *_sqlite_uuid("player_id", nullable=True),
        *_sqlite_integer("created_at_ms"),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name="fk_economy_accounts_player_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_economy_accounts"),
        sa.UniqueConstraint("id", "account_kind", name="uq_economy_accounts_id_kind"),
        sa.UniqueConstraint("player_id", "account_kind", name="uq_economy_accounts_player_kind"),
        sa.UniqueConstraint("system_key", name="uq_economy_accounts_system_key"),
    )
    op.create_table(
        "economy_account_balances",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("account_kind", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("version >= 0", name="ck_economy_account_balances_version"),
        sa.CheckConstraint(
            "(account_kind = 'wallet' AND amount >= 0) OR "
            "(account_kind = 'issuance' AND amount <= 0) OR "
            "(account_kind = 'retirement' AND amount >= 0)",
            name="ck_economy_account_balances_polarity",
        ),
        *_sqlite_uuid("account_id"),
        *_sqlite_integer("amount"),
        *_sqlite_integer("version"),
        sa.ForeignKeyConstraint(
            ["account_id", "account_kind"],
            ["economy_accounts.id", "economy_accounts.account_kind"],
            name="fk_economy_account_balances_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("account_id", name="pk_economy_account_balances"),
    )
    op.create_table(
        "operations_integrity_violations",
        sa.Column("violation_kind", sa.String(length=32), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "violation_kind IN ('account_without_balance', 'player_without_wallet')",
            name="ck_operations_integrity_violations_kind",
        ),
        *_sqlite_uuid("aggregate_id"),
        sa.PrimaryKeyConstraint(
            "violation_kind", "aggregate_id", name="pk_operations_integrity_violations"
        ),
    )
    op.create_index(
        INTEGRITY_SENTINEL_INDEX,
        "operations_integrity_violations",
        ["aggregate_id"],
    )
    if op.get_bind().dialect.name == "sqlite":
        for statement in SQLITE_AGGREGATE_TRIGGER_SQL.values():
            op.execute(statement)
    op.create_table(
        "economy_ledger_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_kind", sa.String(length=64), nullable=False),
        sa.Column("committed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_reference", sa.String(length=255), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("transport_request_id", sa.Uuid(), nullable=True),
        sa.Column("domain_reference", sa.String(length=255), nullable=True),
        sa.Column("discord_interaction_id", sa.BigInteger(), nullable=True),
        sa.Column("content_version", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "discord_interaction_id IS NULL OR discord_interaction_id >= 0",
            name="ck_economy_ledger_transactions_interaction_nonnegative",
        ),
        *_sqlite_check(
            "length(transaction_kind) BETWEEN 1 AND 64 "
            "AND instr(transaction_kind, char(0)) = 0 "
            "AND transaction_kind = lower(transaction_kind) "
            "AND transaction_kind GLOB '[a-z]*' "
            "AND transaction_kind NOT GLOB '*[^a-z0-9_.]*' "
            "AND transaction_kind NOT GLOB '*.[^a-z]*' "
            "AND transaction_kind NOT LIKE '%..%' AND transaction_kind NOT LIKE '%.'",
            "ck_economy_ledger_transactions_kind",
        ),
        *_sqlite_check(
            "length(actor_kind) BETWEEN 1 AND 32 AND instr(actor_kind, char(0)) = 0 "
            "AND actor_kind = lower(actor_kind) AND actor_kind GLOB '[a-z]*' "
            "AND actor_kind NOT GLOB '*[^a-z0-9_.]*' "
            "AND actor_kind NOT GLOB '*.[^a-z]*' "
            "AND actor_kind NOT LIKE '%..%' AND actor_kind NOT LIKE '%.'",
            "ck_economy_ledger_transactions_actor_kind",
        ),
        *_sqlite_check(
            _sqlite_reference("actor_reference"),
            "ck_economy_ledger_transactions_actor_reference",
        ),
        *_sqlite_check(
            "length(reason_code) BETWEEN 3 AND 100 AND instr(reason_code, char(0)) = 0 "
            "AND reason_code = lower(reason_code) AND reason_code GLOB '[a-z]*.[a-z]*' "
            "AND reason_code NOT GLOB '*[^a-z0-9_.]*' "
            "AND reason_code NOT GLOB '*.[^a-z]*' "
            "AND reason_code NOT LIKE '%..%' AND reason_code NOT LIKE '%.'",
            "ck_economy_ledger_transactions_reason_code",
        ),
        *_sqlite_check(
            _sqlite_reference("domain_reference", nullable=True),
            "ck_economy_ledger_transactions_domain_reference",
        ),
        *_sqlite_check(
            _sqlite_reference("content_version", maximum=100, nullable=True),
            "ck_economy_ledger_transactions_content_version",
        ),
        *_sqlite_uuid("id"),
        *_sqlite_integer("committed_at_ms"),
        *_sqlite_uuid("correlation_id"),
        *_sqlite_uuid("transport_request_id", nullable=True),
        *_sqlite_integer("discord_interaction_id", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_economy_ledger_transactions"),
        sa.UniqueConstraint("correlation_id", name="uq_economy_ledger_transactions_correlation"),
    )
    op.create_index(
        "ix_economy_ledger_transactions_committed_order",
        "economy_ledger_transactions",
        ["committed_at_ms", "id"],
    )
    op.create_table(
        "economy_ledger_postings",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("amount != 0", name="ck_economy_ledger_postings_nonzero"),
        *_sqlite_uuid("transaction_id"),
        *_sqlite_uuid("account_id"),
        *_sqlite_integer("amount"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["economy_accounts.id"],
            name="fk_economy_ledger_postings_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["economy_ledger_transactions.id"],
            name="fk_economy_ledger_postings_transaction_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transaction_id", "account_id", name="pk_economy_ledger_postings"),
    )


def downgrade() -> None:
    op.drop_table("economy_ledger_postings")
    op.drop_index(
        "ix_economy_ledger_transactions_committed_order",
        table_name="economy_ledger_transactions",
    )
    op.drop_table("economy_ledger_transactions")
    op.drop_index(
        INTEGRITY_SENTINEL_INDEX,
        table_name="operations_integrity_violations",
    )
    op.drop_table("operations_integrity_violations")
    op.drop_table("economy_account_balances")
    op.drop_table("economy_accounts")
    op.drop_index(
        "ix_operations_transport_requests_retain_until",
        table_name="operations_transport_requests",
    )
    op.drop_table("operations_transport_requests")
    op.drop_table("players")
