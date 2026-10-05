import asyncio
import sqlite3
from contextlib import closing
from uuid import UUID

import pytest
from tests.test_corrections import correct, funded, reconcile
from tests.test_join import Eligibility
from tests.test_safety import service

from butterbot.application.safety.service import DAY_MS, SafetyPolicy, SafetyResult
from butterbot.infrastructure.persistence.database import DatabaseRuntime


@pytest.mark.parametrize("recursive", [0, 1])
@pytest.mark.parametrize(
    "attack", ["posting_upsert", "id_replace", "correlation_replace", "receipt_replace"]
)
async def test_incoming_correction_attacks(
    database_runtime: DatabaseRuntime, recursive: int, attack: str
) -> None:
    original = await funded(database_runtime)
    assert await correct(database_runtime, original, amount=3) == "corrected"
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        target = db.execute("SELECT transaction_id FROM economy_corrections").fetchone()[0]
        source = UUID(int=991).hex
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
            with pytest.raises(sqlite3.IntegrityError, match="sealed correction history"):
                db.execute(
                    "INSERT INTO economy_ledger_postings VALUES (?,?,2) "
                    "ON CONFLICT(transaction_id,account_id) DO UPDATE SET transaction_id=?",
                    (source, account, target),
                )
        elif attack == "receipt_replace":
            with pytest.raises(sqlite3.IntegrityError, match="sealed correction history"):
                db.execute(
                    "INSERT OR REPLACE INTO economy_corrections SELECT * FROM economy_corrections"
                )
        else:
            col = "id" if attack == "id_replace" else "correlation_id"
            with pytest.raises(sqlite3.IntegrityError, match="sealed correction history"):
                db.execute(
                    f"UPDATE OR REPLACE economy_ledger_transactions SET {col}=? WHERE id=?",
                    (target, source),
                )
    reconcile(database_runtime)


async def test_competing_independent_corrections_and_exact_cutoff(
    database_runtime: DatabaseRuntime,
) -> None:
    first = await funded(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    proposal = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=10,
        reason="second",
        interaction_id=20,
    )
    assert proposal.proposal_id is not None
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=proposal.proposal_id, interaction_id=21)
    ).status == "executed"
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        second = UUID(
            db.execute(
                "SELECT transaction_id FROM economy_grant_executions WHERE proposal_id=?",
                (proposal.proposal_id.hex,),
            ).fetchone()[0]
        )

    async def run(original: UUID, interaction: int, now: int) -> SafetyResult:
        return await service(
            database_runtime,
            now=now,
            policy=SafetyPolicy(10, 10, 10),
            grant_eligibility=Eligibility(),
        ).correct_grant(
            actor_id=111,
            target_id=123,
            original_transaction_id=original,
            amount=6,
            reason="bounded",
            bypass_freeze=False,
            interaction_id=interaction,
        )

    results = await asyncio.gather(run(first, 30, 1000), run(second, 31, 1000))
    assert sorted(r.status for r in results) == ["corrected", "limit"]
    remaining = (first, second)[next(i for i, r in enumerate(results) if r.status == "limit")]
    assert (await run(remaining, 32, 1000 + DAY_MS - 1)).status == "limit"
    assert (await run(remaining, 33, 1000 + DAY_MS)).status == "corrected"
    reconcile(database_runtime)
