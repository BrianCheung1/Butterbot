"""Freeze aggregate ownership at the SQLite boundary."""

from alembic import op

revision = "20260914_0002"
down_revision = "20260825_0001"
branch_labels = None
depends_on = None

TRIGGERS = {
    "trg_players_immutable_identity": """
CREATE TRIGGER trg_players_immutable_identity BEFORE UPDATE OF id, discord_user_id ON
players WHEN NEW.id IS NOT OLD.id OR NEW.discord_user_id IS NOT OLD.discord_user_id BEGIN
SELECT RAISE(ABORT, 'aggregate identity is immutable'); END
    """,
    "trg_economy_accounts_immutable_identity": """
CREATE TRIGGER trg_economy_accounts_immutable_identity BEFORE UPDATE OF id, player_id,
account_kind, currency_key, system_key ON economy_accounts WHEN NEW.id IS NOT OLD.id OR
NEW.player_id IS NOT OLD.player_id OR NEW.account_kind IS NOT OLD.account_kind OR
NEW.currency_key IS NOT OLD.currency_key OR NEW.system_key IS NOT OLD.system_key BEGIN
SELECT RAISE(ABORT, 'aggregate identity is immutable'); END
    """,
    "trg_economy_account_balances_immutable_identity": """
CREATE TRIGGER trg_economy_account_balances_immutable_identity BEFORE UPDATE OF
account_id, account_kind ON economy_account_balances WHEN NEW.account_id IS NOT
OLD.account_id OR NEW.account_kind IS NOT OLD.account_kind BEGIN SELECT RAISE(ABORT,
'aggregate identity is immutable'); END
    """,
}


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # Reconcile pre-upgrade holes once, while stopped. Startup stays bounded.
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
