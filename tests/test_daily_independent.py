import sqlite3
from contextlib import closing
from uuid import UUID

import pytest
from tests.test_daily import service
from tests.test_grants import reconcile
from tests.test_join import service as joins

from butterbot.application.economy.balance import BalanceService
from butterbot.application.economy.daily import DAY_MS
from butterbot.infrastructure.persistence.database import DatabaseRuntime


@pytest.mark.parametrize("recursive", [0, 1])
@pytest.mark.parametrize("attack", ["posting_upsert", "id_replace", "correlation_replace"])
async def test_incoming_daily_history_is_sealed(
    database_runtime: DatabaseRuntime, recursive: int, attack: str
) -> None:
    await joins(database_runtime).join(discord_user_id=123, interaction_id=1)
    result = await service(database_runtime).claim(
        discord_user_id=123, interaction_id=2, claim_period=0
    )
    assert result.status == "claimed" and result.transaction_id is not None
    target = result.transaction_id.hex
    source = UUID(int=991).hex
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        db.execute(
            "INSERT INTO economy_ledger_transactions SELECT ?,transaction_kind,committed_at_ms,"
            "actor_kind,actor_reference,reason_code,?,transport_request_id,domain_reference,"
            "discord_interaction_id,content_version FROM economy_ledger_transactions WHERE id=?",
            (source, source, target),
        )
        if attack == "posting_upsert":
            account = db.execute(
                "SELECT account_id FROM economy_ledger_postings WHERE transaction_id=? LIMIT 1",
                (target,),
            ).fetchone()[0]
            db.execute("INSERT INTO economy_ledger_postings VALUES (?,?,1)", (source, account))
            with pytest.raises(sqlite3.IntegrityError, match="sealed daily history"):
                db.execute(
                    "INSERT INTO economy_ledger_postings VALUES (?,?,2) "
                    "ON CONFLICT(transaction_id,account_id) DO UPDATE SET transaction_id=?",
                    (source, account, target),
                )
        else:
            column = "id" if attack == "id_replace" else "correlation_id"
            with pytest.raises(sqlite3.IntegrityError, match="sealed daily history"):
                db.execute(
                    f"UPDATE OR REPLACE economy_ledger_transactions SET {column}=? WHERE id=?",
                    (target, source),
                )
    reconcile(database_runtime)


async def test_clock_regression_cannot_reclaim_past_day_or_expose_other_wallet(
    database_runtime: DatabaseRuntime,
) -> None:
    for user in (123, 456):
        await joins(database_runtime).join(discord_user_id=user, interaction_id=user)
    now = DAY_MS - 1
    daily = service(database_runtime, clock=lambda: now)
    assert (await daily.claim(discord_user_id=123, interaction_id=1, claim_period=0)).balance == 15
    now = DAY_MS
    assert (await daily.claim(discord_user_id=123, interaction_id=2, claim_period=1)).balance == 30
    now = 0
    assert (
        await daily.claim(discord_user_id=123, interaction_id=3, claim_period=0)
    ).status == "already_claimed"
    assert (await daily.claim(discord_user_id=456, interaction_id=4, claim_period=0)).balance == 15
    query = BalanceService(database_runtime.unit_of_work_factory.read_snapshot)
    first = await query.history(discord_user_id=123)
    second = await query.history(discord_user_id=456)
    assert len(first.entries) == 2
    assert len(second.entries) == 1
    assert not {e.transaction_id for e in first.entries} & {
        e.transaction_id for e in second.entries
    }
    reconcile(database_runtime)
