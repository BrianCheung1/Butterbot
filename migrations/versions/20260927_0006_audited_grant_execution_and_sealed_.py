"""Audited grant execution and sealed ledger

Revision ID: 20260927_0006
Revises: 20260924_0005
Create Date: 2026-09-27 13:48:10.627983
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0006"
down_revision: str | None = "20260924_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "economy_grant_executions",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("executed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "typeof(actor_id) = 'integer'", name="ck_sqlite_actor_id_integer"
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(executed_at_ms) = 'integer'", name="ck_sqlite_executed_at_ms_integer"
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(proposal_id) = 'text' AND length(proposal_id) = 32 "
            "AND proposal_id = lower(proposal_id) AND proposal_id NOT GLOB '*[^0-9a-f]*'",
            name="ck_sqlite_proposal_id_uuid",
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint("typeof(total) = 'integer'", name="ck_sqlite_total_integer").ddl_if(
            dialect="sqlite"
        ),
        sa.CheckConstraint(
            "typeof(transaction_id) = 'text' AND length(transaction_id) = 32 "
            "AND transaction_id = lower(transaction_id) AND transaction_id NOT GLOB '*[^0-9a-f]*'",
            name="ck_sqlite_transaction_id_uuid",
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "actor_id > 0 AND executed_at_ms >= 0 AND total > 0", name="ck_grant_execution_values"
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["safety_proposals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["economy_ledger_transactions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint("transaction_id", name="uq_grant_execution_transaction"),
    )
    op.create_index(
        "ix_grant_execution_actor_time",
        "economy_grant_executions",
        ["actor_id", "executed_at_ms"],
        unique=False,
    )
    op.create_table(
        "economy_grant_targets",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("before_amount", sa.BigInteger(), nullable=False),
        sa.Column("after_amount", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "typeof(account_id) = 'text' AND length(account_id) = 32 "
            "AND account_id = lower(account_id) AND account_id NOT GLOB '*[^0-9a-f]*'",
            name="ck_sqlite_account_id_uuid",
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(after_amount) = 'integer'", name="ck_sqlite_after_amount_integer"
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(before_amount) = 'integer'", name="ck_sqlite_before_amount_integer"
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(proposal_id) = 'text' AND length(proposal_id) = 32 "
            "AND proposal_id = lower(proposal_id) AND proposal_id NOT GLOB '*[^0-9a-f]*'",
            name="ck_sqlite_proposal_id_uuid",
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(target_id) = 'integer'", name="ck_sqlite_target_id_integer"
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "target_id > 0 AND before_amount >= 0 AND after_amount > before_amount",
            name="ck_grant_target_values",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["economy_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposal_id"], ["safety_proposals.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("proposal_id", "account_id"),
        sa.UniqueConstraint("proposal_id", "target_id", name="uq_grant_target_identity"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER {name}")
    op.drop_table("economy_grant_targets")
    op.drop_index("ix_grant_execution_actor_time", table_name="economy_grant_executions")
    op.drop_table("economy_grant_executions")


# Frozen SQLite guards; no runtime imports.
TRIGGERS = {
    "trg_economy_grant_executions_update": """
        CREATE TRIGGER trg_economy_grant_executions_update BEFORE UPDATE ON
        economy_grant_executions  BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable
        or invalid'); END
    """,
    "trg_economy_grant_executions_delete": """
        CREATE TRIGGER trg_economy_grant_executions_delete BEFORE DELETE ON
        economy_grant_executions  BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable
        or invalid'); END
    """,
    "trg_economy_grant_executions_replace": """
        CREATE TRIGGER trg_economy_grant_executions_replace BEFORE INSERT ON
        economy_grant_executions WHEN EXISTS (SELECT 1 FROM economy_grant_executions WHERE
        proposal_id=NEW.proposal_id OR transaction_id=NEW.transaction_id) BEGIN SELECT
        RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_economy_grant_targets_update": """
        CREATE TRIGGER trg_economy_grant_targets_update BEFORE UPDATE ON economy_grant_targets
        BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_economy_grant_targets_delete": """
        CREATE TRIGGER trg_economy_grant_targets_delete BEFORE DELETE ON economy_grant_targets
        BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_economy_grant_targets_replace": """
        CREATE TRIGGER trg_economy_grant_targets_replace BEFORE INSERT ON economy_grant_targets
        WHEN EXISTS (SELECT 1 FROM economy_grant_targets WHERE proposal_id=NEW.proposal_id AND
        (account_id=NEW.account_id OR target_id=NEW.target_id)) BEGIN SELECT RAISE(ABORT,
        'sealed grant history is immutable or invalid'); END
    """,
    "trg_grant_targets_sealed": """
        CREATE TRIGGER trg_grant_targets_sealed BEFORE INSERT ON economy_grant_targets WHEN
        EXISTS (SELECT 1 FROM economy_grant_executions WHERE proposal_id=NEW.proposal_id) BEGIN
        SELECT RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_grant_ledger_update": """
        CREATE TRIGGER trg_grant_ledger_update BEFORE UPDATE ON economy_ledger_transactions WHEN
        EXISTS (SELECT 1 FROM economy_grant_executions WHERE transaction_id=OLD.id) BEGIN SELECT
        RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_grant_postings_update": """
        CREATE TRIGGER trg_grant_postings_update BEFORE UPDATE ON economy_ledger_postings WHEN
        EXISTS (SELECT 1 FROM economy_grant_executions WHERE transaction_id=OLD.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_grant_ledger_delete": """
        CREATE TRIGGER trg_grant_ledger_delete BEFORE DELETE ON economy_ledger_transactions WHEN
        EXISTS (SELECT 1 FROM economy_grant_executions WHERE transaction_id=OLD.id) BEGIN SELECT
        RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_grant_postings_delete": """
        CREATE TRIGGER trg_grant_postings_delete BEFORE DELETE ON economy_ledger_postings WHEN
        EXISTS (SELECT 1 FROM economy_grant_executions WHERE transaction_id=OLD.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_grant_ledger_replace": """
        CREATE TRIGGER trg_grant_ledger_replace BEFORE INSERT ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_ledger_transactions AS l JOIN
        economy_grant_executions AS e ON e.transaction_id=l.id WHERE l.id=NEW.id OR
        l.correlation_id=NEW.correlation_id) BEGIN SELECT RAISE(ABORT, 'sealed grant history is
        immutable or invalid'); END
    """,
    "trg_grant_postings_sealed": """
        CREATE TRIGGER trg_grant_postings_sealed BEFORE INSERT ON economy_ledger_postings WHEN
        EXISTS (SELECT 1 FROM economy_grant_executions WHERE transaction_id=NEW.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable or invalid'); END
    """,
    "trg_grant_execution_validate": """
        CREATE TRIGGER trg_grant_execution_validate BEFORE INSERT ON economy_grant_executions
        WHEN NOT EXISTS (  SELECT 1 FROM safety_proposals AS p JOIN safety_proposal_scopes AS s
        ON s.proposal_id=p.id  JOIN economy_ledger_transactions AS l ON l.id=NEW.transaction_id
        WHERE p.id=NEW.proposal_id AND p.operation='grant' AND p.status='approved'  AND
        p.actor_id=NEW.actor_id AND s.scope_verified=1  AND NEW.executed_at_ms >=
        p.created_at_ms AND NEW.executed_at_ms < p.expires_at_ms  AND
        NEW.total=p.amount*s.target_count AND l.domain_reference=
        substr(p.id,1,8)||'-'||substr(p.id,9,4)||'-'||substr(p.id,13,4)||'-'||substr(p.id,17,4)||'-'||substr(p.id,21,12)
        AND l.transaction_kind='admin.grant' AND l.reason_code='issuance.admin'  AND
        l.actor_kind='discord_user' AND l.actor_reference=CAST(NEW.actor_id AS TEXT)  AND
        l.committed_at_ms=NEW.executed_at_ms  AND s.target_count=(SELECT COUNT(*) FROM
        economy_grant_targets WHERE proposal_id=p.id)  AND s.target_count=(SELECT COUNT(*) FROM
        safety_proposal_targets WHERE proposal_id=p.id)  AND s.target_count+1=(SELECT COUNT(*)
        FROM economy_ledger_postings WHERE transaction_id=l.id)  AND NOT EXISTS (SELECT 1 FROM
        economy_grant_targets AS g    WHERE g.proposal_id=p.id AND NOT EXISTS (      SELECT 1
        FROM safety_proposal_targets AS t JOIN players AS u ON u.discord_user_id=t.target_id
        JOIN economy_accounts AS a ON a.player_id=u.id AND a.account_kind='wallet'      JOIN
        economy_account_balances AS b ON b.account_id=a.id      JOIN economy_ledger_postings AS
        w ON w.account_id=a.id AND w.transaction_id=l.id      WHERE t.proposal_id=p.id AND
        t.target_id=g.target_id AND a.id=g.account_id        AND
        g.after_amount-g.before_amount=p.amount AND w.amount=p.amount        AND
        b.amount=g.after_amount))  AND EXISTS (SELECT 1 FROM economy_ledger_postings AS w JOIN
        economy_accounts AS a ON a.id=w.account_id    WHERE w.transaction_id=l.id AND
        a.system_key='issuance.admin' AND a.account_kind='issuance'      AND
        w.amount=-NEW.total) ) BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable or
        invalid'); END
    """,
}
