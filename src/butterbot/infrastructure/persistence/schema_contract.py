from __future__ import annotations

from collections.abc import Mapping

INTEGRITY_SENTINEL_TABLE = "operations_integrity_violations"
INTEGRITY_SENTINEL_INDEX = "ix_operations_integrity_violations_aggregate_id"
INTEGRITY_DEPENDENCY_TABLE_SHA256: Mapping[str, str] = {
    "players": "9a0c44ee98b8a39607cc845d61d5bc47bc84413d1f015179f1f84d0900d5982a",
    "economy_accounts": "63a7dd949164e9cd47df9991cda3f43c69fe1cd38f8b1105beacc211b1585b11",
    "economy_account_balances": (
        "6ee87d7de6f16c825228338935a4f377dcb6db2d77671a73486e3a2db37b4020"
    ),
    INTEGRITY_SENTINEL_TABLE: ("d02700327ca1933c329d4551090d14029a916aaa9760991ebdc38b7237372553"),
}
INTEGRITY_SENTINEL_INDEX_SQL = (
    "CREATE INDEX ix_operations_integrity_violations_aggregate_id "
    "ON operations_integrity_violations (aggregate_id)"
)

SQLITE_AGGREGATE_TRIGGER_SQL: Mapping[str, str] = {
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

INTEGRITY_TRIGGER_TABLES = frozenset(
    {
        "players",
        "economy_accounts",
        "economy_account_balances",
        INTEGRITY_SENTINEL_TABLE,
    }
)


def normalize_sql_definition(sql: str) -> str:
    """Return a deterministic representation of SQLite-owned schema SQL."""
    return " ".join(sql.strip().rstrip(";").split())


NORMALIZED_SQLITE_AGGREGATE_TRIGGERS = {
    name: normalize_sql_definition(sql) for name, sql in SQLITE_AGGREGATE_TRIGGER_SQL.items()
}


__all__ = [
    "INTEGRITY_SENTINEL_INDEX",
    "INTEGRITY_SENTINEL_INDEX_SQL",
    "INTEGRITY_SENTINEL_TABLE",
    "INTEGRITY_DEPENDENCY_TABLE_SHA256",
    "INTEGRITY_TRIGGER_TABLES",
    "NORMALIZED_SQLITE_AGGREGATE_TRIGGERS",
    "SQLITE_AGGREGATE_TRIGGER_SQL",
    "normalize_sql_definition",
]
