import asyncio
import sqlite3
from contextlib import closing
from uuid import UUID, uuid4

import pytest
from tests.test_grants import prepared
from tests.test_join import Eligibility
from tests.test_safety import rows, service

from butterbot.application.economy.balance import BalanceService
from butterbot.application.exact_integer import INT64_MAX
from butterbot.application.operations.idempotency import FingerprintConflict
from butterbot.application.safety.service import SafetyPolicy
from butterbot.infrastructure.persistence.corrections import SqlAlchemyCorrectionRepository
from butterbot.infrastructure.persistence.database import DatabaseRuntime
from butterbot.infrastructure.persistence.grants import SqlAlchemyGrantRepository
from butterbot.infrastructure.persistence.safety import SqlAlchemySafetyRepository


async def funded(runtime: DatabaseRuntime, *, amount: int = 10) -> UUID:
    pid = await prepared(runtime, amount=amount)
    admin = service(runtime, grant_eligibility=Eligibility())
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == "executed"
    assert (
        await admin.change_capability(
            actor_id=111,
            target_id=111,
            capability="corrections.execute",
            enabled=True,
            reason="test authority",
            interaction_id=4,
        )
    ).status == "applied"
    return UUID(
        str(
            rows(runtime.database_path, "SELECT transaction_id FROM economy_grant_executions")[0][0]
        )
    )


async def correct(
    runtime: DatabaseRuntime,
    original: UUID,
    *,
    interaction: int = 10,
    amount: int = 10,
    bypass: bool = False,
) -> str:
    result = await service(runtime, grant_eligibility=Eligibility()).correct_grant(
        actor_id=111,
        target_id=123,
        original_transaction_id=original,
        amount=amount,
        reason="private operator incident reason",
        bypass_freeze=bypass,
        interaction_id=interaction,
    )
    return result.status


def reconcile(runtime: DatabaseRuntime) -> None:
    with closing(sqlite3.connect(runtime.database_path)) as db:
        for account, amount in db.execute("SELECT account_id,amount FROM economy_account_balances"):
            assert amount == sum(
                r[0]
                for r in db.execute(
                    "SELECT amount FROM economy_ledger_postings WHERE account_id=?", (account,)
                )
            )
        assert not db.execute(
            "SELECT transaction_id FROM economy_ledger_postings "
            "GROUP BY transaction_id HAVING SUM(amount)!=0"
        ).fetchall()
        balances = dict(
            db.execute(
                "SELECT account_kind,SUM(amount) FROM economy_account_balances "
                "GROUP BY account_kind"
            )
        )
        assert -balances.get("issuance", 0) - balances.get("retirement", 0) == balances.get(
            "wallet", 0
        )
        assert balances.get("issuance", 0) <= 0 <= balances.get("retirement", 0)


async def test_correction_once_concurrent_replay_and_retention(
    database_runtime: DatabaseRuntime,
) -> None:
    original = await funded(database_runtime)
    results = await asyncio.gather(
        *(correct(database_runtime, original, interaction=i) for i in (10, 11))
    )
    assert sorted(results) == ["already_corrected", "corrected"]
    assert await correct(database_runtime, original, interaction=10) == results[0]
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute("DELETE FROM operations_transport_requests")
    assert await correct(database_runtime, original, interaction=10) == results[0]
    assert await correct(database_runtime, original, interaction=12) == "already_corrected"
    assert rows(
        database_runtime.database_path, "SELECT before_amount,after_amount FROM economy_corrections"
    ) == [(10, 0)]
    reconcile(database_runtime)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("denied", "denied"),
        ("disabled", "unavailable"),
        ("frozen", "frozen"),
        ("bypass_denied", "denied"),
        ("limit", "limit"),
        ("exceeds_original", "limit"),
        ("insufficient", "insufficient_funds"),
        ("inactive", "unavailable"),
        ("unknown", "unavailable"),
        ("policy_missing", "unconfigured"),
    ],
)
async def test_correction_rechecks_policy_and_state(
    database_runtime: DatabaseRuntime, case: str, expected: str
) -> None:
    original = await funded(database_runtime)
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        if case == "denied":
            db.execute("DELETE FROM safety_capabilities WHERE capability='corrections.execute'")
        if case in {"frozen", "bypass_denied"}:
            db.execute("INSERT INTO safety_restrictions VALUES (0)")
        if case == "insufficient":
            db.execute("UPDATE economy_account_balances SET amount=0 WHERE account_kind='wallet'")
        if case == "inactive":
            db.execute("UPDATE players SET lifecycle_state='pseudonymized'")
    policy = (
        None
        if case == "policy_missing"
        else SafetyPolicy(5, 1000, 10000)
        if case == "limit"
        else SafetyPolicy(100, 1000, 10000)
    )
    result = await service(
        database_runtime, policy=policy, grant_eligibility=Eligibility(case != "disabled")
    ).correct_grant(
        actor_id=111,
        target_id=123,
        original_transaction_id=uuid4() if case == "unknown" else original,
        amount=11 if case == "exceeds_original" else 10,
        reason="test correction",
        bypass_freeze=case == "bypass_denied",
        interaction_id=10,
    )
    assert result.status == expected
    assert rows(database_runtime.database_path, "SELECT * FROM economy_corrections") == []
    assert (
        len(rows(database_runtime.database_path, "SELECT * FROM economy_ledger_transactions")) == 1
    )


async def test_explicit_freeze_bypass_audited_and_readable(
    database_runtime: DatabaseRuntime,
) -> None:
    original = await funded(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    await admin.change_capability(
        actor_id=111,
        target_id=111,
        capability="corrections.bypass_freeze",
        enabled=True,
        reason="test bypass authority",
        interaction_id=5,
    )
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute("INSERT INTO safety_restrictions VALUES (0)")
    assert await correct(database_runtime, original, amount=4, bypass=True) == "corrected"
    assert rows(
        database_runtime.database_path, "SELECT freeze_bypassed FROM economy_corrections"
    ) == [(1,)]
    assert rows(
        database_runtime.database_path,
        "SELECT target_id,reason FROM safety_access_audit WHERE action='correction.freeze_bypass'",
    ) == [(123, "private operator incident reason")]
    balance = BalanceService(database_runtime.unit_of_work_factory.read_snapshot)
    assert (await balance.balance(discord_user_id=123)).amount == 6
    page = await balance.history(discord_user_id=123)
    assert sorted((e.amount, e.resulting_balance) for e in page.entries) == [(-4, 6), (10, 10)]
    assert "private operator" not in repr(page)
    reconcile(database_runtime)


@pytest.mark.parametrize("phase", ["projection", "receipt", "audit", "cancel"])
async def test_correction_atomic_rollback(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    original = await funded(database_runtime)
    if phase == "projection":
        project = SqlAlchemyGrantRepository.project

        async def fail(self: SqlAlchemyGrantRepository, *args: object) -> None:
            await project(self, *args)  # pyright: ignore[reportArgumentType]
            raise RuntimeError("injected after wallet projection")

        monkeypatch.setattr(SqlAlchemyGrantRepository, "project", fail)
    elif phase == "audit":

        async def fail_audit(*args: object, **kwargs: object) -> None:
            raise RuntimeError("injected audit failure")

        monkeypatch.setattr(SqlAlchemySafetyRepository, "audit", fail_audit)
    else:
        debit = SqlAlchemyCorrectionRepository.debit

        async def fail_debit(self: SqlAlchemyCorrectionRepository, *args: object) -> None:
            await debit(self, *args)  # pyright: ignore[reportArgumentType]
            if phase == "cancel":
                raise asyncio.CancelledError()
            raise RuntimeError("injected after receipt")

        monkeypatch.setattr(SqlAlchemyCorrectionRepository, "debit", fail_debit)
    with pytest.raises(asyncio.CancelledError if phase == "cancel" else RuntimeError):
        await correct(database_runtime, original)
    assert rows(database_runtime.database_path, "SELECT * FROM economy_corrections") == []
    assert rows(
        database_runtime.database_path, "SELECT account_kind,amount FROM economy_account_balances"
    ) == [("wallet", 10), ("issuance", -10)]
    reconcile(database_runtime)


async def test_correction_transport_conflict_and_revocation(
    database_runtime: DatabaseRuntime,
) -> None:
    original = await funded(database_runtime)
    assert await correct(database_runtime, original, amount=3) == "corrected"
    with pytest.raises(FingerprintConflict):
        await correct(database_runtime, original, amount=4)
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute("DELETE FROM safety_capabilities WHERE capability='corrections.execute'")
    assert await correct(database_runtime, original, amount=3) == "denied"
    reconcile(database_runtime)


@pytest.mark.parametrize("field", ["amount", "version"])
async def test_correction_retirement_overflow_rolls_back(
    database_runtime: DatabaseRuntime, field: str
) -> None:
    original = await funded(database_runtime)
    # Create a valid retirement account through the first correction, then corrupt its bound.
    assert await correct(database_runtime, original, amount=1) == "corrected"
    admin = service(database_runtime, grant_eligibility=Eligibility())
    proposal = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=10,
        reason="second grant",
        interaction_id=20,
    )
    assert proposal.proposal_id is not None
    await admin.execute_grant(actor_id=111, proposal_id=proposal.proposal_id, interaction_id=21)
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute(
            f"UPDATE economy_account_balances SET {field}=? WHERE account_kind='retirement'",
            (INT64_MAX,),
        )
        second = UUID(
            db.execute(
                "SELECT transaction_id FROM economy_grant_executions WHERE proposal_id=?",
                (proposal.proposal_id.hex,),
            ).fetchone()[0]
        )
    with pytest.raises(ValueError):
        await correct(database_runtime, second, interaction=22)
    assert len(rows(database_runtime.database_path, "SELECT * FROM economy_corrections")) == 1


@pytest.mark.parametrize("recursive", [0, 1])
@pytest.mark.parametrize(
    "attack",
    [
        "receipt_update",
        "receipt_delete",
        "receipt_replace",
        "posting_update",
        "posting_delete",
        "posting_replace",
        "ledger_update",
        "ledger_delete",
        "ledger_replace",
    ],
)
async def test_correction_history_is_sealed(
    database_runtime: DatabaseRuntime, recursive: int, attack: str
) -> None:
    original = await funded(database_runtime)
    assert await correct(database_runtime, original) == "corrected"
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        tx = db.execute("SELECT transaction_id FROM economy_corrections").fetchone()[0]
        statements = {
            "receipt_update": "UPDATE economy_corrections SET reason='changed' "
            "WHERE transaction_id=?",
            "receipt_delete": "DELETE FROM economy_corrections WHERE transaction_id=?",
            "receipt_replace": "INSERT OR REPLACE INTO economy_corrections "
            "SELECT * FROM economy_corrections WHERE transaction_id=?",
            "posting_update": "UPDATE economy_ledger_postings SET amount=amount+1 "
            "WHERE transaction_id=?",
            "posting_delete": "DELETE FROM economy_ledger_postings WHERE transaction_id=?",
            "posting_replace": "INSERT OR REPLACE INTO economy_ledger_postings "
            "SELECT * FROM economy_ledger_postings WHERE transaction_id=?",
            "ledger_update": "UPDATE economy_ledger_transactions "
            "SET reason_code='wrong.reason' WHERE id=?",
            "ledger_delete": "DELETE FROM economy_ledger_transactions WHERE id=?",
            "ledger_replace": "INSERT OR REPLACE INTO economy_ledger_transactions "
            "SELECT * FROM economy_ledger_transactions WHERE id=?",
        }
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statements[attack], (tx,))
    reconcile(database_runtime)


async def test_no_correction_permission_is_implicitly_bootstrapped(
    database_runtime: DatabaseRuntime,
) -> None:
    await service(database_runtime).bootstrap((111,))
    assert (
        rows(
            database_runtime.database_path,
            "SELECT * FROM safety_capabilities WHERE capability LIKE 'corrections.%'",
        )
        == []
    )


async def test_correction_post_commit_alert_loss_does_not_repeat(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = await funded(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())

    def fail_alert(*args: object) -> None:
        raise RuntimeError("alert lost")

    monkeypatch.setattr(admin, "_alert", fail_alert)
    result = await admin.correct_grant(
        actor_id=111,
        target_id=123,
        original_transaction_id=original,
        amount=10,
        reason="mistake",
        bypass_freeze=False,
        interaction_id=10,
    )
    assert result.status == "corrected"
    assert await correct(database_runtime, original, interaction=11) == "already_corrected"
    reconcile(database_runtime)
