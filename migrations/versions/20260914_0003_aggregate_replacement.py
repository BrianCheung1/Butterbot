"""Reject aggregate replacement before SQLite conflict deletion occurs."""

from alembic import op

revision = "20260914_0003"
down_revision = "20260914_0002"
branch_labels = None
depends_on = None

TRIGGERS = {
    "trg_players_reject_conflicting_insert": """
CREATE TRIGGER trg_players_reject_conflicting_insert BEFORE INSERT ON players
WHEN EXISTS (SELECT 1 FROM players WHERE id = NEW.id)
OR EXISTS (SELECT 1 FROM players WHERE discord_user_id = NEW.discord_user_id)
BEGIN SELECT RAISE(ABORT, 'UNIQUE constraint failed: aggregate replacement is forbidden'); END
    """,
    "trg_accounts_reject_conflicting_insert": """
CREATE TRIGGER trg_accounts_reject_conflicting_insert BEFORE INSERT ON economy_accounts
WHEN EXISTS (SELECT 1 FROM economy_accounts WHERE id = NEW.id)
OR EXISTS (SELECT 1 FROM economy_accounts
    WHERE player_id = NEW.player_id AND account_kind = NEW.account_kind)
OR EXISTS (SELECT 1 FROM economy_accounts WHERE system_key = NEW.system_key)
BEGIN SELECT RAISE(ABORT, 'UNIQUE constraint failed: aggregate replacement is forbidden'); END
    """,
    "trg_balances_reject_conflicting_insert": """
CREATE TRIGGER trg_balances_reject_conflicting_insert BEFORE INSERT ON economy_account_balances
WHEN EXISTS (SELECT 1 FROM economy_account_balances WHERE account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'UNIQUE constraint failed: aggregate replacement is forbidden'); END
    """,
}


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # Older heads could hide holes through REPLACE. Record, never repair, them.
        op.execute("""
            INSERT OR IGNORE INTO operations_integrity_violations
                (violation_kind, aggregate_id)
            SELECT 'player_without_wallet', p.id FROM players p
            WHERE NOT EXISTS (SELECT 1 FROM economy_accounts a
                WHERE a.player_id = p.id AND a.account_kind = 'wallet')
        """)
        op.execute("""
            INSERT OR IGNORE INTO operations_integrity_violations
                (violation_kind, aggregate_id)
            SELECT 'account_without_balance', a.id FROM economy_accounts a
            WHERE NOT EXISTS (SELECT 1 FROM economy_account_balances b
                WHERE b.account_id = a.id)
        """)
        for sql in TRIGGERS.values():
            op.execute(sql)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGERS:
            op.execute(f"DROP TRIGGER {name}")
