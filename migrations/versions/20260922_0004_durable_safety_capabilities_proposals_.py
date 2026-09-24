"""Durable safety capabilities proposals restrictions and audit

Revision ID: 20260922_0004
Revises: 20260914_0003
Create Date: 2026-09-22 17:31:53.245849
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0004"
down_revision: str | None = "20260914_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Frozen migration SQL; do not import runtime schema definitions.
TRIGGERS = {
    "trg_safety_access_audit_no_replace": (
        "CREATE TRIGGER trg_safety_access_audit_no_replace BEFORE INSERT ON "
        "safety_access_audit WHEN EXISTS (SELECT 1 FROM safety_access_audit "
        "WHERE id = NEW.id) BEGIN SELECT RAISE(ABORT, 'safety replacement "
        "forbidden'); END"
    ),
    "trg_safety_access_audit_no_delete": (
        "CREATE TRIGGER trg_safety_access_audit_no_delete BEFORE DELETE ON "
        "safety_access_audit BEGIN SELECT RAISE(ABORT, 'safety history "
        "immutable'); END"
    ),
    "trg_safety_access_audit_no_update": (
        "CREATE TRIGGER trg_safety_access_audit_no_update BEFORE UPDATE ON "
        "safety_access_audit BEGIN SELECT RAISE(ABORT, 'safety history "
        "immutable'); END"
    ),
    "trg_safety_bootstrap_no_replace": (
        "CREATE TRIGGER trg_safety_bootstrap_no_replace BEFORE INSERT ON "
        "safety_bootstrap WHEN EXISTS (SELECT 1 FROM safety_bootstrap WHERE "
        "id = NEW.id) BEGIN SELECT RAISE(ABORT, 'safety replacement "
        "forbidden'); END"
    ),
    "trg_safety_bootstrap_no_delete": (
        "CREATE TRIGGER trg_safety_bootstrap_no_delete BEFORE DELETE ON "
        "safety_bootstrap BEGIN SELECT RAISE(ABORT, 'safety history "
        "immutable'); END"
    ),
    "trg_safety_bootstrap_no_update": (
        "CREATE TRIGGER trg_safety_bootstrap_no_update BEFORE UPDATE ON "
        "safety_bootstrap BEGIN SELECT RAISE(ABORT, 'safety history "
        "immutable'); END"
    ),
    "trg_safety_proposals_no_replace": (
        "CREATE TRIGGER trg_safety_proposals_no_replace BEFORE INSERT ON "
        "safety_proposals WHEN EXISTS (SELECT 1 FROM safety_proposals WHERE "
        "id = NEW.id) BEGIN SELECT RAISE(ABORT, 'safety replacement "
        "forbidden'); END"
    ),
    "trg_safety_proposals_no_delete": (
        "CREATE TRIGGER trg_safety_proposals_no_delete BEFORE DELETE ON "
        "safety_proposals BEGIN SELECT RAISE(ABORT, 'safety history "
        "immutable'); END"
    ),
    "trg_safety_proposal_targets_no_replace": (
        "CREATE TRIGGER trg_safety_proposal_targets_no_replace BEFORE INSERT "
        "ON safety_proposal_targets WHEN EXISTS (SELECT 1 FROM "
        "safety_proposal_targets WHERE proposal_id = NEW.proposal_id AND "
        "target_id = NEW.target_id) BEGIN SELECT RAISE(ABORT, 'safety "
        "replacement forbidden'); END"
    ),
    "trg_safety_proposal_targets_no_delete": (
        "CREATE TRIGGER trg_safety_proposal_targets_no_delete BEFORE DELETE "
        "ON safety_proposal_targets BEGIN SELECT RAISE(ABORT, 'safety history"
        " immutable'); END"
    ),
    "trg_safety_proposal_targets_no_update": (
        "CREATE TRIGGER trg_safety_proposal_targets_no_update BEFORE UPDATE "
        "ON safety_proposal_targets BEGIN SELECT RAISE(ABORT, 'safety history"
        " immutable'); END"
    ),
    "trg_safety_proposals_transition": (
        "CREATE TRIGGER trg_safety_proposals_transition BEFORE UPDATE ON "
        "safety_proposals WHEN NEW.id IS NOT OLD.id OR NEW.actor_id IS NOT "
        "OLD.actor_id OR NEW.operation IS NOT OLD.operation OR NEW.amount IS "
        "NOT OLD.amount OR NEW.reason IS NOT OLD.reason OR NEW.created_at_ms "
        "IS NOT OLD.created_at_ms OR NEW.expires_at_ms IS NOT "
        "OLD.expires_at_ms OR NEW.requires_approval IS NOT "
        "OLD.requires_approval OR OLD.status != 'pending' OR NEW.status NOT "
        "IN ('approved','applied') BEGIN SELECT RAISE(ABORT, 'invalid safety "
        "proposal transition'); END"
    ),
}


def upgrade() -> None:
    op.create_table(
        "safety_access_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            (
                "proposal_id IS NULL OR (typeof(proposal_id) = 'text' AND "
                "length(proposal_id) = 32 AND proposal_id = lower(proposal_id) AND "
                "proposal_id NOT GLOB '*[^0-9a-f]*')"
            ),
            name="ck_sqlite_proposal_id_uuid",
        ),
        sa.CheckConstraint(
            "target_id IS NULL OR typeof(target_id) = 'integer'", name="ck_sqlite_target_id_integer"
        ),
        sa.CheckConstraint("typeof(actor_id) = 'integer'", name="ck_sqlite_actor_id_integer"),
        sa.CheckConstraint(
            "typeof(created_at_ms) = 'integer'", name="ck_sqlite_created_at_ms_integer"
        ),
        sa.CheckConstraint(
            (
                "typeof(id) = 'text' AND length(id) = 32 AND id = lower(id) AND id "
                "NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_sqlite_id_uuid",
        ),
        sa.CheckConstraint(
            "actor_id > 0 AND (target_id IS NULL OR target_id >= 0)",
            name="ck_safety_audit_actor_target",
        ),
        sa.CheckConstraint("created_at_ms >= 0", name="ck_safety_audit_time"),
        sa.CheckConstraint("length(action) BETWEEN 1 AND 64", name="ck_safety_audit_action"),
        sa.CheckConstraint(
            "length(reason) BETWEEN 1 AND 256 AND instr(reason, char(0)) = 0",
            name="ck_safety_audit_reason",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_safety_audit_created", "safety_access_audit", ["created_at_ms", "id"], unique=False
    )
    op.create_table(
        "safety_bootstrap",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "typeof(created_at_ms) = 'integer'", name="ck_sqlite_created_at_ms_integer"
        ),
        sa.CheckConstraint("typeof(id) = 'integer'", name="ck_sqlite_id_integer"),
        sa.CheckConstraint("created_at_ms >= 0", name="ck_safety_bootstrap_time"),
        sa.CheckConstraint("id = 1", name="ck_safety_bootstrap_once"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "safety_capabilities",
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            (
                "capability IN "
                "('capabilities.manage','players.inspect','restrictions.manage','proposals.approve','grants.propose')"
            ),
            name="ck_safety_capability_name",
        ),
        sa.CheckConstraint("typeof(actor_id) = 'integer'", name="ck_sqlite_actor_id_integer"),
        sa.CheckConstraint("actor_id > 0", name="ck_safety_capability_actor"),
        sa.PrimaryKeyConstraint("actor_id", "capability"),
    )
    op.create_table(
        "safety_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("expires_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("requires_approval", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("approver_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "(operation = 'grant' AND amount > 0) OR (operation != 'grant' AND amount = 0)",
            name="ck_safety_proposal_amount",
        ),
        sa.CheckConstraint(
            (
                "(status = 'pending' AND approver_id IS NULL) OR (status != 'pending'"
                " AND (requires_approval = 0 OR approver_id IS NOT NULL))"
            ),
            name="ck_safety_proposal_approval",
        ),
        sa.CheckConstraint(
            "approver_id IS NULL OR typeof(approver_id) = 'integer'",
            name="ck_sqlite_approver_id_integer",
        ),
        sa.CheckConstraint(
            "operation IN ('freeze','release','grant')", name="ck_safety_proposal_operation"
        ),
        sa.CheckConstraint(
            "status != 'applied' OR operation != 'grant'", name="ck_safety_proposal_no_issuance"
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','applied')", name="ck_safety_proposal_status"
        ),
        sa.CheckConstraint("typeof(actor_id) = 'integer'", name="ck_sqlite_actor_id_integer"),
        sa.CheckConstraint("typeof(amount) = 'integer'", name="ck_sqlite_amount_integer"),
        sa.CheckConstraint(
            "typeof(created_at_ms) = 'integer'", name="ck_sqlite_created_at_ms_integer"
        ),
        sa.CheckConstraint(
            "typeof(expires_at_ms) = 'integer'", name="ck_sqlite_expires_at_ms_integer"
        ),
        sa.CheckConstraint(
            (
                "typeof(id) = 'text' AND length(id) = 32 AND id = lower(id) AND id "
                "NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_sqlite_id_uuid",
        ),
        sa.CheckConstraint(
            "typeof(requires_approval) = 'integer'", name="ck_sqlite_requires_approval_integer"
        ),
        sa.CheckConstraint(
            (
                "actor_id > 0 AND (approver_id IS NULL OR (approver_id > 0 AND "
                "approver_id != actor_id))"
            ),
            name="ck_safety_proposal_actors",
        ),
        sa.CheckConstraint(
            "created_at_ms >= 0 AND expires_at_ms > created_at_ms", name="ck_safety_proposal_time"
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 1 AND 256 AND instr(reason, char(0)) = 0",
            name="ck_safety_proposal_reason",
        ),
        sa.CheckConstraint(
            "requires_approval IN (0,1)", name="ck_safety_proposal_requires_approval"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_safety_proposals_actor_time",
        "safety_proposals",
        ["actor_id", "created_at_ms"],
        unique=False,
    )
    op.create_table(
        "safety_restrictions",
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("typeof(target_id) = 'integer'", name="ck_sqlite_target_id_integer"),
        sa.CheckConstraint("target_id >= 0", name="ck_safety_restriction_target"),
        sa.PrimaryKeyConstraint("target_id"),
    )
    op.create_table(
        "safety_proposal_targets",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            (
                "typeof(proposal_id) = 'text' AND length(proposal_id) = 32 AND "
                "proposal_id = lower(proposal_id) AND proposal_id NOT GLOB "
                "'*[^0-9a-f]*'"
            ),
            name="ck_sqlite_proposal_id_uuid",
        ),
        sa.CheckConstraint("typeof(target_id) = 'integer'", name="ck_sqlite_target_id_integer"),
        sa.CheckConstraint("target_id >= 0", name="ck_safety_proposal_target"),
        sa.ForeignKeyConstraint(["proposal_id"], ["safety_proposals.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("proposal_id", "target_id"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER {name}")
    op.drop_table("safety_proposal_targets")
    op.drop_table("safety_restrictions")
    op.drop_index("ix_safety_proposals_actor_time", table_name="safety_proposals")
    op.drop_table("safety_proposals")
    op.drop_table("safety_capabilities")
    op.drop_table("safety_bootstrap")
    op.drop_index("ix_safety_audit_created", table_name="safety_access_audit")
    op.drop_table("safety_access_audit")
