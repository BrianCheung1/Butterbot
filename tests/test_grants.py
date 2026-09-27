import asyncio
import sqlite3
from contextlib import closing
from uuid import UUID

import pytest
from tests.test_join import Eligibility
from tests.test_join import service as joins
from tests.test_safety import rows, service

from butterbot.application.exact_integer import INT64_MAX, ExactIntegerOutOfRange
from butterbot.application.safety.service import DAY_MS, SafetyPolicy
from butterbot.infrastructure.persistence.database import DatabaseRuntime
from butterbot.infrastructure.persistence.grants import SqlAlchemyGrantRepository
from butterbot.infrastructure.persistence.safety import SqlAlchemySafetyRepository


async def prepared(
    runtime: DatabaseRuntime, *, targets: tuple[int, ...] = (123,), amount: int = 10
) -> UUID:
    admin = service(runtime, grant_eligibility=Eligibility())
    await admin.bootstrap((111, 222))
    for i, target in enumerate(targets):
        await joins(runtime).join(discord_user_id=target, interaction_id=100 + i)
    result = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=targets,
        amount=amount,
        reason="test grant",
        interaction_id=1,
    )
    assert result.proposal_id is not None
    if result.status == "pending":
        assert (
            await admin.approve(actor_id=222, proposal_id=result.proposal_id, interaction_id=2)
        ).status == "approved"
    return result.proposal_id


def reconcile(runtime: DatabaseRuntime) -> None:
    with closing(sqlite3.connect(runtime.database_path)) as db:
        balances = db.execute("SELECT account_id, amount FROM economy_account_balances").fetchall()
        for account, amount in balances:
            assert amount == sum(
                r[0]
                for r in db.execute(
                    "SELECT amount FROM economy_ledger_postings WHERE account_id=?", (account,)
                )
            )
        for (tx,) in db.execute("SELECT id FROM economy_ledger_transactions"):
            assert (
                sum(
                    r[0]
                    for r in db.execute(
                        "SELECT amount FROM economy_ledger_postings WHERE transaction_id=?", (tx,)
                    )
                )
                == 0
            )
        minted = -sum(
            r[0]
            for r in db.execute(
                "SELECT amount FROM economy_account_balances WHERE account_kind='issuance'"
            )
        )
        wallets = sum(
            r[0]
            for r in db.execute(
                "SELECT amount FROM economy_account_balances WHERE account_kind='wallet'"
            )
        )
        assert minted == wallets


@pytest.mark.parametrize("targets", [(123,), (123, 456)])
async def test_grant_once_across_concurrent_interactions_and_retention(
    database_runtime: DatabaseRuntime, targets: tuple[int, ...]
) -> None:
    pid = await prepared(database_runtime, targets=targets)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    results = await asyncio.gather(
        *(admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=i) for i in (3, 4, 5))
    )
    assert sorted(r.status for r in results) == ["already_executed", "already_executed", "executed"]
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == results[0].status
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute("DELETE FROM operations_transport_requests")
    late = service(database_runtime, now=10 * DAY_MS, grant_eligibility=Eligibility())
    assert (
        await late.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == results[0].status
    assert (
        await late.execute_grant(actor_id=111, proposal_id=pid, interaction_id=6)
    ).status == "already_executed"
    assert len(rows(database_runtime.database_path, "SELECT * FROM economy_grant_executions")) == 1
    assert rows(
        database_runtime.database_path,
        "SELECT before_amount,after_amount FROM economy_grant_targets",
    ) == [(0, 10)] * len(targets)
    reconcile(database_runtime)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("disabled", "unavailable"),
        ("other_actor", "denied"),
        ("revoked", "denied"),
        ("approver_revoked", "approval_required"),
        ("threshold", "approval_required"),
        ("expired", "expired"),
        ("frozen", "frozen"),
        ("inactive", "unavailable"),
        ("limit", "limit"),
    ],
)
async def test_execution_rechecks_current_policy_and_state(
    database_runtime: DatabaseRuntime, case: str, expected: str
) -> None:
    pid = await prepared(database_runtime, amount=101 if case == "approver_revoked" else 10)
    admin = service(
        database_runtime,
        grant_eligibility=Eligibility(case != "disabled"),
        now=DAY_MS + 1000 if case == "expired" else 1000,
        policy=SafetyPolicy(0, 1000, 10000)
        if case == "threshold"
        else SafetyPolicy(5, 5, 5)
        if case == "limit"
        else SafetyPolicy(100, 1000, 10000),
    )
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        if case == "revoked":
            db.execute(
                "DELETE FROM safety_capabilities WHERE actor_id=111 AND capability='grants.propose'"
            )
        if case == "approver_revoked":
            db.execute(
                "DELETE FROM safety_capabilities WHERE actor_id=222 AND "
                "capability='proposals.approve'"
            )
        if case == "frozen":
            db.execute("INSERT INTO safety_restrictions VALUES (0)")
        if case == "inactive":
            db.execute("UPDATE players SET lifecycle_state='pseudonymized'")
    result = await admin.execute_grant(
        actor_id=222 if case == "other_actor" else 111, proposal_id=pid, interaction_id=3
    )
    assert result.status == expected
    assert rows(database_runtime.database_path, "SELECT * FROM economy_ledger_transactions") == []
    reconcile(database_runtime)


@pytest.mark.parametrize("failure", ["seal", "audit", "overflow"])
async def test_grant_failure_rolls_back_all_money_and_receipts(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    pid = await prepared(database_runtime, targets=(123, 456))
    admin = service(database_runtime, grant_eligibility=Eligibility())
    if failure == "overflow":
        with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
            db.execute(
                "UPDATE economy_account_balances SET amount=? WHERE account_kind='wallet'",
                (INT64_MAX,),
            )
    if failure == "seal":
        with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
            db.execute(
                "CREATE TRIGGER injected BEFORE INSERT ON "
                "economy_grant_executions BEGIN SELECT RAISE(ABORT,'injected'); "
                "END"
            )
    if failure == "audit":

        async def fail(*args: object, **kwargs: object) -> None:
            raise RuntimeError("injected")

        monkeypatch.setattr(SqlAlchemySafetyRepository, "audit", fail)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(
        ExactIntegerOutOfRange
        if failure == "overflow"
        else IntegrityError
        if failure == "seal"
        else RuntimeError
    ):
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    for table in (
        "economy_ledger_transactions",
        "economy_ledger_postings",
        "economy_grant_targets",
        "economy_grant_executions",
    ):
        assert rows(database_runtime.database_path, f"SELECT * FROM {table}") == []
    assert (
        rows(
            database_runtime.database_path,
            "SELECT * FROM economy_accounts WHERE account_kind='issuance'",
        )
        == []
    )
    assert (
        rows(
            database_runtime.database_path,
            "SELECT * FROM operations_transport_requests WHERE namespace='safety.execute_grant'",
        )
        == []
    )
    if failure != "overflow":
        reconcile(database_runtime)


@pytest.mark.parametrize("recursive", [0, 1])
async def test_grant_history_rejects_mutation_and_append(
    database_runtime: DatabaseRuntime, recursive: int
) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == "executed"
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        for table in (
            "economy_grant_executions",
            "economy_grant_targets",
            "economy_ledger_transactions",
            "economy_ledger_postings",
        ):
            for sql in (
                f"DELETE FROM {table}",
                f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}",
            ):
                with pytest.raises(sqlite3.IntegrityError):
                    db.execute(sql)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE economy_grant_targets SET after_amount=11")
        tx = db.execute("SELECT id FROM economy_ledger_transactions").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO economy_ledger_postings VALUES (?, ?, 1)", (tx, UUID(int=99).hex)
            )
    reconcile(database_runtime)


@pytest.mark.parametrize("recursive", [0, 1])
@pytest.mark.parametrize("kind", ["posting", "transaction", "correlation"])
async def test_existing_row_cannot_be_moved_over_sealed_grant(
    database_runtime: DatabaseRuntime, kind: str, recursive: int
) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        target = db.execute("SELECT id FROM economy_ledger_transactions").fetchone()[0]
        source = UUID(int=99).hex
        db.execute(
            "INSERT INTO economy_ledger_transactions SELECT "
            "?,transaction_kind,committed_at_ms,actor_kind,actor_reference,"
            "reason_code,?,transport_request_id,domain_reference,"
            "discord_interaction_id,content_version "
            "FROM economy_ledger_transactions",
            (source, source),
        )
        if kind == "posting":
            db.execute(
                "INSERT INTO economy_ledger_postings SELECT ?,account_id,amount "
                "FROM economy_ledger_postings WHERE transaction_id=?",
                (source, target),
            )
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE OR REPLACE economy_ledger_postings SET "
                    "transaction_id=? WHERE transaction_id=?",
                    (target, source),
                )
        else:
            column = "correlation_id" if kind == "correlation" else "id"
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(
                    f"UPDATE OR REPLACE economy_ledger_transactions SET {column}=? WHERE id=?",
                    (target, source),
                )


async def test_rolling_limit_uses_execution_time_and_exact_cutoff(
    database_runtime: DatabaseRuntime,
) -> None:
    pid = await prepared(database_runtime)
    first = service(database_runtime, now=2000, grant_eligibility=Eligibility())
    assert (
        await first.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == "executed"
    next_admin = service(database_runtime, now=DAY_MS + 1000, grant_eligibility=Eligibility())
    proposal = await next_admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=10,
        reason="next window",
        interaction_id=4,
    )
    assert proposal.proposal_id is not None
    capped = service(
        database_runtime,
        now=DAY_MS + 1000,
        policy=SafetyPolicy(10, 10, 10),
        grant_eligibility=Eligibility(),
    )
    assert (
        await capped.execute_grant(actor_id=111, proposal_id=proposal.proposal_id, interaction_id=5)
    ).status == "limit"
    cutoff = service(
        database_runtime,
        now=DAY_MS + 2000,
        policy=SafetyPolicy(10, 10, 10),
        grant_eligibility=Eligibility(),
    )
    assert (
        await cutoff.execute_grant(actor_id=111, proposal_id=proposal.proposal_id, interaction_id=6)
    ).status == "executed"
    reconcile(database_runtime)


async def test_competing_grants_cannot_exceed_rolling_ceiling(
    database_runtime: DatabaseRuntime,
) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    second = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=10,
        reason="second",
        interaction_id=4,
    )
    assert second.proposal_id is not None
    capped = service(
        database_runtime, policy=SafetyPolicy(10, 10, 10), grant_eligibility=Eligibility()
    )
    results = await asyncio.gather(
        capped.execute_grant(actor_id=111, proposal_id=pid, interaction_id=5),
        capped.execute_grant(actor_id=111, proposal_id=second.proposal_id, interaction_id=6),
    )
    assert sorted(r.status for r in results) == ["executed", "limit"]
    reconcile(database_runtime)


async def test_expiry_is_sampled_after_transaction_admission(
    database_runtime: DatabaseRuntime,
) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    times = iter((1000, DAY_MS + 1000))
    admin._clock_ms = lambda: next(times)  # pyright: ignore[reportPrivateUsage]
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == "expired"
    reconcile(database_runtime)


@pytest.mark.parametrize("case", ["missing", "pending", "unverified"])
async def test_unexecutable_proposal_does_not_mint(
    database_runtime: DatabaseRuntime, case: str
) -> None:
    admin = service(database_runtime, grant_eligibility=Eligibility())
    await admin.bootstrap((111, 222))
    await joins(database_runtime).join(discord_user_id=123, interaction_id=100)
    result = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123, 456) if case == "missing" else (123,),
        amount=101 if case == "pending" else 10,
        reason="invalid",
        interaction_id=1,
    )
    assert result.proposal_id is not None
    if case == "missing":
        await admin.approve(actor_id=222, proposal_id=result.proposal_id, interaction_id=2)
    if case == "unverified":
        # Simulate migration's conservative legacy seal in a disposable fixture.
        with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
            db.execute("DROP TRIGGER trg_safety_scope_no_update")
            db.execute("UPDATE safety_proposal_scopes SET scope_verified=0")
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=result.proposal_id, interaction_id=3)
    ).status == {
        "missing": "unavailable",
        "pending": "approval_required",
        "unverified": "unverified_scope",
    }[case]
    assert rows(database_runtime.database_path, "SELECT * FROM economy_grant_executions") == []
    reconcile(database_runtime)


async def test_issuance_overflow_rolls_back_later_grant(database_runtime: DatabaseRuntime) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    second = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=10,
        reason="overflow",
        interaction_id=4,
    )
    assert second.proposal_id is not None
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute(
            "UPDATE economy_account_balances SET amount=? WHERE account_kind='issuance'",
            (-INT64_MAX,),
        )
    with pytest.raises(ExactIntegerOutOfRange):
        await admin.execute_grant(actor_id=111, proposal_id=second.proposal_id, interaction_id=5)
    assert len(rows(database_runtime.database_path, "SELECT * FROM economy_grant_executions")) == 1
    assert rows(
        database_runtime.database_path,
        "SELECT amount FROM economy_account_balances WHERE account_kind='wallet'",
    ) == [(10,)]


@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_after_first_credit_rolls_back_and_retries(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    pid = await prepared(database_runtime, targets=(123, 456))
    admin = service(database_runtime, grant_eligibility=Eligibility())
    original = SqlAlchemyGrantRepository._project  # pyright: ignore[reportPrivateUsage]
    calls = 0

    async def fail(
        self: SqlAlchemyGrantRepository,
        account_id: UUID,
        before: int,
        version: int,
        after: int,
        next_version: int,
    ) -> None:
        nonlocal calls
        await original(self, account_id, before, version, after, next_version)
        calls += 1
        if calls == 2:
            if cancel:
                raise asyncio.CancelledError()
            raise RuntimeError("injected after first credit")

    monkeypatch.setattr(SqlAlchemyGrantRepository, "_project", fail)
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    reconcile(database_runtime)
    assert rows(database_runtime.database_path, "SELECT * FROM economy_grant_executions") == []
    monkeypatch.setattr(SqlAlchemyGrantRepository, "_project", original)
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == "executed"
    reconcile(database_runtime)


async def test_alert_failure_does_not_undo_grant(database_runtime: DatabaseRuntime) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())

    def fail(action: str, audit: UUID) -> None:
        raise RuntimeError("injected alert failure")

    admin._alert = fail  # pyright: ignore[reportPrivateUsage]
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    ).status == "executed"
    assert (
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=4)
    ).status == "already_executed"
    reconcile(database_runtime)


@pytest.mark.parametrize("kind", ["wallet", "issuance"])
async def test_projection_version_overflow_is_atomic(
    database_runtime: DatabaseRuntime, kind: str
) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    second = await admin.propose(
        actor_id=111, operation="grant", targets=(123,), amount=10, reason="next", interaction_id=4
    )
    assert second.proposal_id is not None
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute(
            "UPDATE economy_account_balances SET version=? WHERE account_kind=?", (INT64_MAX, kind)
        )
    with pytest.raises(ExactIntegerOutOfRange):
        await admin.execute_grant(actor_id=111, proposal_id=second.proposal_id, interaction_id=5)
    assert len(rows(database_runtime.database_path, "SELECT * FROM economy_grant_executions")) == 1
    reconcile(database_runtime)


async def test_grant_data_survives_forward_guard_migration(tmp_path: object) -> None:
    from pathlib import Path
    from typing import cast

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import URL

    from butterbot.infrastructure.persistence.database import create_database_runtime

    path = cast(Path, tmp_path) / "grant-upgrade.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(path)).render_as_string(hide_password=False),
    )
    command.upgrade(config, "head")
    runtime = await create_database_runtime(path)
    try:
        pid = await prepared(runtime)
        await service(runtime, grant_eligibility=Eligibility()).execute_grant(
            actor_id=111, proposal_id=pid, interaction_id=3
        )
    finally:
        await runtime.close()
    command.downgrade(config, "20260927_0006")
    tables = (
        "safety_proposals",
        "safety_proposal_scopes",
        "economy_accounts",
        "economy_account_balances",
        "economy_ledger_transactions",
        "economy_ledger_postings",
        "economy_grant_executions",
        "economy_grant_targets",
        "safety_access_audit",
        "operations_transport_requests",
    )
    before = {table: rows(path, f"SELECT * FROM {table}") for table in tables}
    command.upgrade(config, "head")
    command.check(config)
    assert {table: rows(path, f"SELECT * FROM {table}") for table in tables} == before


@pytest.mark.parametrize("missing", ["wallet", "projection"])
async def test_corrupt_target_is_not_repaired(
    database_runtime: DatabaseRuntime, missing: str
) -> None:
    pid = await prepared(database_runtime)
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute("DELETE FROM economy_account_balances")
        if missing == "wallet":
            db.execute("DELETE FROM economy_accounts")
    admin = service(database_runtime, grant_eligibility=Eligibility())
    with pytest.raises(RuntimeError):
        await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    assert rows(database_runtime.database_path, "SELECT * FROM economy_grant_executions") == []
    assert rows(database_runtime.database_path, "SELECT * FROM economy_account_balances") == []


@pytest.mark.parametrize("recursive", [0, 1])
async def test_plain_incoming_update_cannot_append_grant_posting(
    database_runtime: DatabaseRuntime, recursive: int
) -> None:
    pid = await prepared(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    await admin.execute_grant(actor_id=111, proposal_id=pid, interaction_id=3)
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        sealed = db.execute("SELECT id FROM economy_ledger_transactions").fetchone()[0]
        source = UUID(int=88).hex
        account = UUID(int=89).hex
        db.execute(
            "INSERT INTO economy_ledger_transactions SELECT ?,transaction_kind,"
            "committed_at_ms,actor_kind,"
            "actor_reference,reason_code,?,transport_request_id,domain_reference,"
            "discord_interaction_id,content_version FROM economy_ledger_transactions",
            (source, source),
        )
        db.execute(
            "INSERT INTO economy_accounts VALUES (?,NULL,'retirement','coin','retirement.test',1)",
            (account,),
        )
        db.execute("INSERT INTO economy_account_balances VALUES (?,'retirement',0,0)", (account,))
        db.execute("INSERT INTO economy_ledger_postings VALUES (?,?,1)", (source, account))
        with pytest.raises(sqlite3.IntegrityError, match="sealed grant history"):
            db.execute(
                "UPDATE economy_ledger_postings SET transaction_id=? WHERE transaction_id=?",
                (sealed, source),
            )
