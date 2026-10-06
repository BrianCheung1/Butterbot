"""Permanent UTC daily claim receipts.

Revision ID: 20261005_0009
Revises: 20260930_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_0009"
down_revision: str | None = "20260930_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    constraints = [
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["economy_ledger_transactions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["economy_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("player_id", "claim_period", name="uq_daily_player_period"),
        sa.UniqueConstraint("interaction_id", name="uq_daily_interaction"),
        sa.CheckConstraint(
            "actor_id > 0 AND interaction_id > 0 AND claim_period >= 0 "
            "AND executed_at_ms >= 0 AND claim_period = executed_at_ms / 86400000 "
            "AND before_amount >= 0 AND after_amount > before_amount "
            "AND after_amount-before_amount=15",
            name="ck_daily_values",
        ),
    ]
    for name in ("transaction_id", "player_id", "account_id"):
        constraints.append(
            sa.CheckConstraint(
                f"typeof({name}) = 'text' AND length({name}) = 32 "
                f"AND {name} = lower({name}) AND {name} NOT GLOB '*[^0-9a-f]*'",
                name=f"ck_sqlite_{name}_uuid",
            ).ddl_if(dialect="sqlite")
        )
    integers = (
        "actor_id",
        "interaction_id",
        "claim_period",
        "executed_at_ms",
        "before_amount",
        "after_amount",
    )
    for name in integers:
        constraints.append(
            sa.CheckConstraint(
                f"typeof({name}) = 'integer'", name=f"ck_sqlite_{name}_integer"
            ).ddl_if(dialect="sqlite")
        )
    op.create_table(
        "economy_daily_claims",
        sa.Column("transaction_id", sa.Uuid(), primary_key=True),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        *(sa.Column(n, sa.BigInteger(), nullable=False) for n in integers),
        *constraints,
    )
    if op.get_bind().dialect.name == "sqlite":
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM economy_daily_claims")).scalar():
        raise RuntimeError("cannot discard committed daily history")
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER {name}")
    op.drop_table("economy_daily_claims")


TRIGGERS = {
    "trg_daily_update": """
        CREATE TRIGGER trg_daily_update BEFORE UPDATE ON economy_daily_claims BEGIN SELECT
        RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_delete": """
        CREATE TRIGGER trg_daily_delete BEFORE DELETE ON economy_daily_claims BEGIN SELECT
        RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_replace": """
        CREATE TRIGGER trg_daily_replace BEFORE INSERT ON economy_daily_claims WHEN EXISTS
        (SELECT 1 FROM economy_daily_claims WHERE transaction_id=NEW.transaction_id OR
        (player_id=NEW.player_id AND claim_period=NEW.claim_period) OR
        interaction_id=NEW.interaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_postings_update": """
        CREATE TRIGGER trg_daily_postings_update BEFORE UPDATE ON economy_ledger_postings
        WHEN EXISTS (SELECT 1 FROM economy_daily_claims WHERE transaction_id=OLD.transaction_id)
        OR EXISTS (SELECT 1 FROM economy_daily_claims WHERE transaction_id=NEW.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_ledger_update": """
        CREATE TRIGGER trg_daily_ledger_update BEFORE UPDATE ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_daily_claims WHERE transaction_id=OLD.id) OR EXISTS
        (SELECT 1 FROM economy_ledger_transactions l JOIN economy_daily_claims c ON
        c.transaction_id=l.id WHERE l.id=NEW.id OR l.correlation_id=NEW.correlation_id) BEGIN
        SELECT RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_postings_delete": """
        CREATE TRIGGER trg_daily_postings_delete BEFORE DELETE ON economy_ledger_postings
        WHEN EXISTS (SELECT 1 FROM economy_daily_claims WHERE transaction_id=OLD.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_ledger_delete": """
        CREATE TRIGGER trg_daily_ledger_delete BEFORE DELETE ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_daily_claims WHERE transaction_id=OLD.id) BEGIN
        SELECT
        RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_postings_insert": """
        CREATE TRIGGER trg_daily_postings_insert BEFORE INSERT ON economy_ledger_postings
        WHEN EXISTS (SELECT 1 FROM economy_daily_claims WHERE transaction_id=NEW.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_ledger_insert": """
        CREATE TRIGGER trg_daily_ledger_insert BEFORE INSERT ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_ledger_transactions l JOIN economy_daily_claims c ON
        c.transaction_id=l.id WHERE l.id=NEW.id OR l.correlation_id=NEW.correlation_id) BEGIN
        SELECT RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
    "trg_daily_validate": """
        CREATE TRIGGER trg_daily_validate BEFORE INSERT ON economy_daily_claims WHEN NOT EXISTS
        (
        SELECT 1 FROM economy_ledger_transactions l JOIN economy_accounts a ON
        a.id=NEW.account_id
        JOIN players p ON p.id=a.player_id JOIN economy_account_balances b ON b.account_id=a.id
        JOIN operations_transport_requests r ON r.id=l.transport_request_id
        WHERE l.id=NEW.transaction_id AND l.transaction_kind='daily.claim'
        AND l.reason_code='issuance.daily' AND l.actor_kind='discord_user'
        AND l.actor_reference=CAST(NEW.actor_id AS TEXT) AND
        l.committed_at_ms=NEW.executed_at_ms
        AND l.discord_interaction_id=NEW.interaction_id AND l.domain_reference=NEW.player_id ||
        ':' || CAST(NEW.claim_period AS TEXT)
        AND r.namespace='economy.daily' AND r.transport_key=CAST(NEW.interaction_id AS TEXT)
        AND a.account_kind='wallet' AND a.currency_key='coin' AND p.id=NEW.player_id
        AND p.discord_user_id=NEW.actor_id AND b.amount=NEW.after_amount
        AND (SELECT COUNT(*) FROM economy_ledger_postings WHERE transaction_id=l.id)=2
        AND EXISTS (SELECT 1 FROM economy_ledger_postings WHERE transaction_id=l.id AND
        account_id=a.id AND amount=15)
        AND EXISTS (SELECT 1 FROM economy_ledger_postings w JOIN economy_accounts s ON
        s.id=w.account_id
            WHERE w.transaction_id=l.id AND s.system_key='issuance.daily' AND
        s.account_kind='issuance'
            AND s.currency_key='coin' AND w.amount=-15))
        BEGIN SELECT RAISE(ABORT, 'sealed daily history is immutable or invalid'); END
    """,
}
