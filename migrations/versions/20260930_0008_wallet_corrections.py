"""Bounded grant correction receipts and explicit correction capabilities.

Revision ID: 20260930_0008
Revises: 20260927_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0008"
down_revision: str | None = "20260927_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CAPABILITIES = (
    "'capabilities.manage','players.inspect','restrictions.manage',"
    "'proposals.approve','grants.propose'"
)
NEW_CAPABILITIES = OLD_CAPABILITIES + ",'corrections.execute','corrections.bypass_freeze'"


def upgrade() -> None:
    # No capabilities are granted by migration or added to the historical bootstrap policy.
    _replace_capabilities(NEW_CAPABILITIES)
    columns = [
        sa.Column("transaction_id", sa.Uuid(), primary_key=True),
        sa.Column("original_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        *[
            sa.Column(n, sa.BigInteger(), nullable=False)
            for n in (
                "target_id",
                "actor_id",
                "amount",
                "before_amount",
                "after_amount",
                "executed_at_ms",
                "freeze_bypassed",
            )
        ],
        sa.Column("reason", sa.String(256), nullable=False),
    ]
    constraints = [
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["economy_ledger_transactions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["original_transaction_id"], ["economy_ledger_transactions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["economy_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "original_transaction_id", "account_id", name="uq_correction_original_target"
        ),
        sa.CheckConstraint(
            "actor_id > 0 AND target_id > 0 AND amount > 0 AND after_amount >= 0 "
            "AND before_amount > after_amount AND before_amount-after_amount=amount "
            "AND executed_at_ms >= 0 AND freeze_bypassed IN (0,1)",
            name="ck_correction_values",
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 1 AND 256 AND instr(reason, char(0)) = 0",
            name="ck_correction_reason",
        ),
    ]
    for name in ("transaction_id", "original_transaction_id", "account_id"):
        constraints.append(
            sa.CheckConstraint(
                f"typeof({name}) = 'text' AND length({name}) = 32 "
                f"AND {name} = lower({name}) AND {name} NOT GLOB '*[^0-9a-f]*'",
                name=f"ck_sqlite_{name}_uuid",
            ).ddl_if(dialect="sqlite")
        )
    for name in (
        "target_id",
        "actor_id",
        "amount",
        "before_amount",
        "after_amount",
        "executed_at_ms",
        "freeze_bypassed",
    ):
        constraints.append(
            sa.CheckConstraint(
                f"typeof({name}) = 'integer'", name=f"ck_sqlite_{name}_integer"
            ).ddl_if(dialect="sqlite")
        )
    op.create_table("economy_corrections", *columns, *constraints)
    op.create_index(
        "ix_correction_actor_time", "economy_corrections", ["actor_id", "executed_at_ms"]
    )
    if op.get_bind().dialect.name == "sqlite":
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM economy_corrections")).scalar():
        raise RuntimeError("cannot discard committed correction history")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM safety_capabilities WHERE capability LIKE 'corrections.%'"
            )
        )
        .scalar()
    ):
        raise RuntimeError("revoke correction capabilities before downgrade")
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER {name}")
    op.drop_table("economy_corrections")
    _replace_capabilities(OLD_CAPABILITIES)


def _replace_capabilities(names: str) -> None:
    if names == OLD_CAPABILITIES:
        # Restore the frozen 0004/0007 SQL form, including constraint order and the
        # unquoted original table name, so old-code exact readiness accepts rollback.
        op.rename_table("safety_capabilities", "safety_capabilities_previous")
        op.create_table(
            "safety_capabilities",
            sa.Column("actor_id", sa.BigInteger(), nullable=False),
            sa.Column("capability", sa.String(32), nullable=False),
            sa.CheckConstraint(
                f"capability IN ({OLD_CAPABILITIES})", name="ck_safety_capability_name"
            ),
            sa.CheckConstraint("typeof(actor_id) = 'integer'", name="ck_sqlite_actor_id_integer"),
            sa.CheckConstraint("actor_id > 0", name="ck_safety_capability_actor"),
            sa.PrimaryKeyConstraint("actor_id", "capability"),
        )
        op.execute(
            "INSERT INTO safety_capabilities (actor_id,capability) "
            "SELECT actor_id,capability FROM safety_capabilities_previous"
        )
        op.drop_table("safety_capabilities_previous")
        return
    # Explicit DDL order: reflected batch constraints have nondeterministic ordering,
    # which is incompatible with the exact release schema fingerprint.
    op.create_table(
        "safety_capabilities_next",
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("actor_id", "capability"),
        sa.CheckConstraint("actor_id > 0", name="ck_safety_capability_actor"),
        sa.CheckConstraint(f"capability IN ({names})", name="ck_safety_capability_name"),
        sa.CheckConstraint(
            "typeof(actor_id) = 'integer'", name="ck_sqlite_actor_id_integer"
        ).ddl_if(dialect="sqlite"),
    )
    op.execute(
        "INSERT INTO safety_capabilities_next (actor_id,capability) "
        "SELECT actor_id,capability FROM safety_capabilities"
    )
    op.drop_table("safety_capabilities")
    op.rename_table("safety_capabilities_next", "safety_capabilities")


# Frozen SQLite guards. Seal only new correction transactions; original grants stay immutable.
TRIGGERS = {
    "trg_correction_update": """
        CREATE TRIGGER trg_correction_update BEFORE UPDATE ON economy_corrections BEGIN SELECT
        RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_delete": """
        CREATE TRIGGER trg_correction_delete BEFORE DELETE ON economy_corrections BEGIN SELECT
        RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_replace": """
        CREATE TRIGGER trg_correction_replace BEFORE INSERT ON economy_corrections WHEN EXISTS
        (SELECT 1 FROM economy_corrections WHERE transaction_id=NEW.transaction_id OR
        (original_transaction_id=NEW.original_transaction_id AND account_id=NEW.account_id))
        BEGIN SELECT RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_postings_update": """
        CREATE TRIGGER trg_correction_postings_update BEFORE UPDATE ON economy_ledger_postings
        WHEN EXISTS (SELECT 1 FROM economy_corrections WHERE transaction_id=OLD.transaction_id)
        OR EXISTS (SELECT 1 FROM economy_corrections WHERE transaction_id=NEW.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_ledger_update": """
        CREATE TRIGGER trg_correction_ledger_update BEFORE UPDATE ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_corrections WHERE transaction_id=OLD.id) OR EXISTS
        (SELECT 1 FROM economy_ledger_transactions l JOIN economy_corrections c ON
        c.transaction_id=l.id WHERE l.id=NEW.id OR l.correlation_id=NEW.correlation_id) BEGIN
        SELECT RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_postings_delete": """
        CREATE TRIGGER trg_correction_postings_delete BEFORE DELETE ON economy_ledger_postings
        WHEN EXISTS (SELECT 1 FROM economy_corrections WHERE transaction_id=OLD.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_ledger_delete": """
        CREATE TRIGGER trg_correction_ledger_delete BEFORE DELETE ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_corrections WHERE transaction_id=OLD.id) BEGIN SELECT
        RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_postings_insert": """
        CREATE TRIGGER trg_correction_postings_insert BEFORE INSERT ON economy_ledger_postings
        WHEN EXISTS (SELECT 1 FROM economy_corrections WHERE transaction_id=NEW.transaction_id)
        BEGIN SELECT RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_ledger_insert": """
        CREATE TRIGGER trg_correction_ledger_insert BEFORE INSERT ON economy_ledger_transactions
        WHEN EXISTS (SELECT 1 FROM economy_ledger_transactions l JOIN economy_corrections c ON
        c.transaction_id=l.id WHERE l.id=NEW.id OR l.correlation_id=NEW.correlation_id) BEGIN
        SELECT RAISE(ABORT, 'sealed correction history is immutable or invalid'); END
    """,
    "trg_correction_validate": """
        CREATE TRIGGER trg_correction_validate BEFORE INSERT ON economy_corrections WHEN NOT
        EXISTS ( SELECT 1 FROM economy_ledger_transactions l JOIN economy_grant_executions e ON
        e.transaction_id=NEW.original_transaction_id JOIN economy_grant_targets g ON
        g.proposal_id=e.proposal_id AND g.account_id=NEW.account_id JOIN economy_accounts a ON
        a.id=g.account_id AND a.account_kind='wallet' JOIN players p ON p.id=a.player_id AND
        p.discord_user_id=NEW.target_id JOIN economy_account_balances b ON b.account_id=a.id
        WHERE l.id=NEW.transaction_id AND l.transaction_kind='admin.correction' AND
        l.reason_code='retirement.correction' AND l.actor_kind='discord_user' AND
        l.actor_reference=CAST(NEW.actor_id AS TEXT) AND l.committed_at_ms=NEW.executed_at_ms
        AND NEW.target_id=g.target_id AND NEW.amount <= g.after_amount-g.before_amount AND
        b.amount=NEW.after_amount AND l.domain_reference=
        substr(e.transaction_id,1,8) || '-' || substr(e.transaction_id,9,4) || '-' ||
        substr(e.transaction_id,13,4) || '-' || substr(e.transaction_id,17,4) || '-' ||
        substr(e.transaction_id,21,12) || ':' || CAST(NEW.target_id AS TEXT)
        AND (SELECT COUNT(*)
        FROM economy_ledger_postings WHERE transaction_id=l.id)=2 AND EXISTS (SELECT 1 FROM
        economy_ledger_postings WHERE transaction_id=l.id AND account_id=a.id AND
        amount=-NEW.amount) AND EXISTS (SELECT 1 FROM economy_ledger_postings w JOIN
        economy_accounts s ON s.id=w.account_id WHERE w.transaction_id=l.id AND
        s.system_key='retirement.correction' AND s.account_kind='retirement' AND
        w.amount=NEW.amount) ) BEGIN SELECT RAISE(ABORT, 'sealed correction history is immutable
        or invalid'); END
    """,
}
