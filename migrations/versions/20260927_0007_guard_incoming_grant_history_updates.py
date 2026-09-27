"""Reject incoming updates that would replace or extend sealed grant history.

Revision ID: 20260927_0007
Revises: 20260927_0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260927_0007"
down_revision: str | None = "20260927_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = {
    "trg_grant_postings_incoming_update": """
        CREATE TRIGGER trg_grant_postings_incoming_update
        BEFORE UPDATE ON economy_ledger_postings
        WHEN EXISTS (SELECT 1 FROM economy_grant_executions
                     WHERE transaction_id=NEW.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable'); END
    """,
    "trg_grant_ledger_incoming_update": """
        CREATE TRIGGER trg_grant_ledger_incoming_update
        BEFORE UPDATE ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_ledger_transactions AS l
            JOIN economy_grant_executions AS e ON e.transaction_id=l.id
            WHERE l.id=NEW.id OR l.correlation_id=NEW.correlation_id)
        BEGIN SELECT RAISE(ABORT, 'sealed grant history is immutable'); END
    """,
}


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER {name}")
