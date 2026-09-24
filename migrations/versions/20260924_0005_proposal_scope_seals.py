"""Seal proposal membership; never retroactively certify legacy approvals.

Revision ID: 20260924_0005
Revises: 20260922_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0005"
down_revision: str | None = "20260922_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen migration SQL, independent of runtime models.
TRIGGERS = {
    "trg_safety_scope_no_replace": """
        CREATE TRIGGER trg_safety_scope_no_replace BEFORE INSERT ON safety_proposal_scopes
        WHEN EXISTS (SELECT 1 FROM safety_proposal_scopes WHERE proposal_id=NEW.proposal_id)
        BEGIN SELECT RAISE(ABORT, 'proposal scope is sealed'); END
    """,
    "trg_safety_scope_no_update": """
        CREATE TRIGGER trg_safety_scope_no_update BEFORE UPDATE ON safety_proposal_scopes
        BEGIN SELECT RAISE(ABORT, 'proposal scope is sealed'); END
    """,
    "trg_safety_scope_no_delete": """
        CREATE TRIGGER trg_safety_scope_no_delete BEFORE DELETE ON safety_proposal_scopes
        BEGIN SELECT RAISE(ABORT, 'proposal scope is sealed'); END
    """,
    "trg_safety_targets_sealed": """
        CREATE TRIGGER trg_safety_targets_sealed BEFORE INSERT ON safety_proposal_targets
        WHEN EXISTS (SELECT 1 FROM safety_proposal_scopes WHERE proposal_id=NEW.proposal_id)
        BEGIN SELECT RAISE(ABORT, 'proposal scope is sealed'); END
    """,
    "trg_safety_scope_validate": """
        CREATE TRIGGER trg_safety_scope_validate BEFORE INSERT ON safety_proposal_scopes
        WHEN NOT EXISTS (SELECT 1 FROM safety_proposals WHERE id=NEW.proposal_id)
        OR NEW.target_count != (
            SELECT COUNT(*) FROM safety_proposal_targets WHERE proposal_id=NEW.proposal_id)
        OR (NEW.scope_verified=1 AND (
            NOT EXISTS (SELECT 1 FROM safety_proposals WHERE id=NEW.proposal_id
                        AND status='pending' AND approver_id IS NULL)
            OR (NEW.target_count>1 AND EXISTS (
                SELECT 1 FROM safety_proposal_targets
                WHERE proposal_id=NEW.proposal_id AND target_id=0))
            OR EXISTS (SELECT 1 FROM safety_proposals AS p
                JOIN safety_proposal_targets AS t ON t.proposal_id=p.id
                WHERE p.id=NEW.proposal_id AND p.operation='grant' AND t.target_id=0)
        ))
        BEGIN SELECT RAISE(ABORT, 'invalid proposal scope seal'); END
    """,
    "trg_safety_proposal_initial_state": """
        CREATE TRIGGER trg_safety_proposal_initial_state BEFORE INSERT ON safety_proposals
        WHEN NEW.status != 'pending' OR NEW.approver_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'new proposal must start pending'); END
    """,
    "trg_safety_proposal_require_scope": """
        CREATE TRIGGER trg_safety_proposal_require_scope BEFORE UPDATE ON safety_proposals
        WHEN NOT EXISTS (SELECT 1 FROM safety_proposal_scopes AS s
            WHERE s.proposal_id=OLD.id AND s.scope_verified=1
              AND s.target_count=(SELECT COUNT(*) FROM safety_proposal_targets AS t
                                  WHERE t.proposal_id=OLD.id))
        BEGIN SELECT RAISE(ABORT, 'proposal requires verified sealed scope'); END
    """,
}


def upgrade() -> None:
    op.create_table(
        "safety_proposal_scopes",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("target_count", sa.BigInteger(), nullable=False),
        sa.Column("scope_verified", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.ForeignKeyConstraint(["proposal_id"], ["safety_proposals.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("scope_verified IN (0,1)", name="ck_safety_scope_verified"),
        sa.CheckConstraint(
            "target_count >= 0 AND (scope_verified=0 OR target_count BETWEEN 1 AND 25)",
            name="ck_safety_scope_count",
        ),
        sa.CheckConstraint(
            "typeof(target_count) = 'integer'", name="ck_sqlite_target_count_integer"
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(scope_verified) = 'integer'", name="ck_sqlite_scope_verified_integer"
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "typeof(proposal_id) = 'text' AND length(proposal_id) = 32 "
            "AND proposal_id = lower(proposal_id) AND proposal_id NOT GLOB '*[^0-9a-f]*'",
            name="ck_sqlite_proposal_id_uuid",
        ).ddl_if(dialect="sqlite"),
    )
    # Freeze existing membership as observed, without asserting what was originally approved.
    op.execute("""
        INSERT INTO safety_proposal_scopes(proposal_id, target_count, scope_verified)
        SELECT p.id, COUNT(t.target_id), 0 FROM safety_proposals AS p
        LEFT JOIN safety_proposal_targets AS t ON t.proposal_id=p.id GROUP BY p.id
    """)
    if op.get_bind().dialect.name == "sqlite":
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER {name}")
    op.drop_table("safety_proposal_scopes")
