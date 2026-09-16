from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from butterbot.application.operations.outcome_codec import (
    InvalidStableOutcome,
    decode_canonical_stable_outcome,
)


class HistoricalVerificationError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True, slots=True)
class HistoricalVerificationReport:
    transport_outcomes_checked: int
    invalid_shape_rows: int


async def verify_historical_persistence(engine: AsyncEngine) -> HistoricalVerificationReport:
    """Exhaustively verify retained/permanent history without materializing it in memory."""
    checked = 0
    async with engine.connect() as connection:
        quick_check = await connection.stream(text("PRAGMA quick_check"))
        async for (result,) in quick_check:
            if str(result) != "ok":
                raise HistoricalVerificationError(
                    "corrupt_database", "SQLite quick_check reported database corruption"
                )
        foreign_keys = await connection.stream(text("PRAGMA foreign_key_check"))
        async for _violation in foreign_keys:
            raise HistoricalVerificationError(
                "foreign_key_violation", "SQLite foreign_key_check reported a violation"
            )
        invalid_shape_rows = int(await connection.scalar(text(_INVALID_HISTORICAL_ROWS_SQL)) or 0)
        if invalid_shape_rows:
            raise HistoricalVerificationError(
                "invalid_persisted_state",
                "historical persistence contains invalid identifier, integer, or outcome shapes",
            )
        outcomes = await connection.stream(
            text(
                "SELECT outcome_kind, outcome_code, outcome_payload "
                "FROM operations_transport_requests WHERE outcome_kind IS NOT NULL "
                "ORDER BY retain_until_ms, id"
            )
        )
        async for outcome_kind, outcome_code, outcome_payload in outcomes:
            checked += 1
            try:
                decode_canonical_stable_outcome(
                    kind=str(outcome_kind),
                    code=str(outcome_code),
                    payload_text=str(outcome_payload),
                )
            except InvalidStableOutcome as error:
                raise HistoricalVerificationError(
                    "invalid_transport_request",
                    "historical persistence contains a non-canonical transport outcome",
                ) from error
    return HistoricalVerificationReport(checked, invalid_shape_rows)


async def _verify_database(database_path: Path) -> HistoricalVerificationReport:
    from butterbot.infrastructure.persistence.database import create_database_runtime

    runtime = await create_database_runtime(database_path)
    try:
        return await verify_historical_persistence(runtime.engine)
    finally:
        await runtime.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exhaustively verify Butterbot SQLite history while the service is stopped."
    )
    parser.add_argument("database", type=Path)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(_verify_database(args.database))
    except Exception as error:
        print(f"historical verification failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "outcome": "passed",
                "transport_outcomes_checked": report.transport_outcomes_checked,
                "invalid_shape_rows": report.invalid_shape_rows,
            },
            sort_keys=True,
        )
    )
    return 0


_UUID_ID = (
    "typeof({column}) != 'text' OR length({column}) != 32 OR {column} != lower({column}) "
    "OR {column} GLOB '*[^0-9a-f]*'"
)
_PERMANENT_REFERENCE = (
    "length({column}) NOT BETWEEN 1 AND {maximum} OR instr({column}, char(0)) != 0 "
    "OR {column} GLOB '*[^!-~]*'"
)

_INVALID_HISTORICAL_ROWS_SQL = f"""
SELECT
    (SELECT COUNT(*) FROM operations_integrity_violations)
  + (SELECT COUNT(*) FROM players
     WHERE ({_UUID_ID.format(column="id")})
        OR typeof(discord_user_id) != 'integer'
        OR typeof(created_at_ms) != 'integer')
  + (SELECT COUNT(*) FROM economy_accounts
     WHERE ({_UUID_ID.format(column="id")})
        OR (player_id IS NOT NULL AND ({_UUID_ID.format(column="player_id")}))
        OR typeof(created_at_ms) != 'integer')
  + (SELECT COUNT(*) FROM economy_account_balances
     WHERE ({_UUID_ID.format(column="account_id")})
        OR typeof(amount) != 'integer' OR typeof(version) != 'integer')
  + (SELECT COUNT(*) FROM economy_accounts AS account
     LEFT JOIN economy_account_balances AS balance ON balance.account_id = account.id
     WHERE balance.account_id IS NULL)
  + (SELECT COUNT(*) FROM players AS player
     LEFT JOIN economy_accounts AS wallet
       ON wallet.player_id = player.id AND wallet.account_kind = 'wallet'
     WHERE wallet.id IS NULL)
  + (SELECT COUNT(*) FROM operations_transport_requests
     WHERE ({_UUID_ID.format(column="id")})
        OR ({_PERMANENT_REFERENCE.format(column="actor_reference", maximum=255)})
        OR outcome_kind NOT IN ('success', 'typed_rejection')
        OR outcome_code IS NULL OR outcome_payload IS NULL
        OR completed_at_ms IS NULL OR retain_until_ms IS NULL
        OR typeof(completed_at_ms) != 'integer'
        OR typeof(retain_until_ms) != 'integer'
        OR retain_until_ms <= completed_at_ms
        OR CASE WHEN json_valid(outcome_payload)
                THEN json_type(outcome_payload) != 'object' ELSE 1 END)
  + (SELECT COUNT(*) FROM economy_ledger_transactions
     WHERE ({_UUID_ID.format(column="id")})
        OR ({_UUID_ID.format(column="correlation_id")})
        OR (transport_request_id IS NOT NULL AND
            ({_UUID_ID.format(column="transport_request_id")}))
         OR typeof(committed_at_ms) != 'integer'
        OR ({_PERMANENT_REFERENCE.format(column="actor_reference", maximum=255)})
        OR (domain_reference IS NOT NULL AND
            ({_PERMANENT_REFERENCE.format(column="domain_reference", maximum=255)}))
        OR (content_version IS NOT NULL AND
            ({_PERMANENT_REFERENCE.format(column="content_version", maximum=100)}))
        OR (discord_interaction_id IS NOT NULL AND
            typeof(discord_interaction_id) != 'integer'))
  + (SELECT COUNT(*) FROM economy_ledger_postings
     WHERE ({_UUID_ID.format(column="transaction_id")})
        OR ({_UUID_ID.format(column="account_id")})
        OR typeof(amount) != 'integer')
"""


if __name__ == "__main__":
    raise SystemExit(main())
