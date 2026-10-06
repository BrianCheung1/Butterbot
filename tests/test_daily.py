import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import closing

import pytest
from tests.test_grants import reconcile
from tests.test_join import Eligibility
from tests.test_join import service as joins
from tests.test_safety import rows

from butterbot.application.economy.balance import BalanceService
from butterbot.application.economy.daily import DAILY_NAMESPACE, DAY_MS, DailyService
from butterbot.application.exact_integer import INT64_MAX, INT64_MIN, ExactIntegerOutOfRange
from butterbot.application.operations.idempotency import (
    FingerprintConflict,
    NullOperationsTelemetry,
    TransportIdempotencyCoordinator,
    discord_retention_registry,
)
from butterbot.application.transactions import ApplicationTransactionRunner
from butterbot.infrastructure.persistence.daily import SqlAlchemyDailyRepository
from butterbot.infrastructure.persistence.database import DatabaseRuntime, is_sqlite_busy
from butterbot.infrastructure.persistence.grants import SqlAlchemyGrantRepository


def service(
    runtime: DatabaseRuntime,
    *,
    clock: Callable[[], int] = lambda: 1000,
    eligibility: Eligibility | None = None,
) -> DailyService:
    return DailyService(
        ApplicationTransactionRunner(
            runtime.unit_of_work_factory,
            is_retryable=is_sqlite_busy,
            telemetry=NullOperationsTelemetry(),
        ),
        runtime.unit_of_work_factory.read_snapshot,
        TransportIdempotencyCoordinator(discord_retention_registry(DAILY_NAMESPACE)),
        eligibility if eligibility is not None else Eligibility(),
        clock_ms=clock,
    )


async def test_concurrent_claims_business_uniqueness_and_permanent_replay(
    database_runtime: DatabaseRuntime,
) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    daily = service(r)
    results = await asyncio.gather(
        *(daily.claim(discord_user_id=123, interaction_id=i, claim_period=0) for i in (2, 3, 4))
    )
    assert sorted(x.status for x in results) == ["already_claimed", "already_claimed", "claimed"]
    winner = next(
        i for i, result in zip((2, 3, 4), results, strict=True) if result.status == "claimed"
    )
    original = results[winner - 2]
    assert original.balance == 15
    replay = await daily.claim(discord_user_id=123, interaction_id=winner, claim_period=0)
    assert replay.replayed and replay.transaction_id == original.transaction_id
    with closing(sqlite3.connect(r.database_path)) as db, db:
        db.execute("DELETE FROM operations_transport_requests")
        db.execute("INSERT INTO safety_restrictions VALUES (0)")
    late = service(r, clock=lambda: DAY_MS * 10, eligibility=Eligibility(False))
    replay = await late.claim(discord_user_id=123, interaction_id=winner, claim_period=0)
    assert replay.replayed and replay.balance == 15
    for user, period in [(456, 0), (123, 10)]:
        with pytest.raises(FingerprintConflict):
            await late.claim(discord_user_id=user, interaction_id=winner, claim_period=period)
    reconcile(r)
    history = await BalanceService(r.unit_of_work_factory.read_snapshot).history(
        discord_user_id=123
    )
    assert [(e.kind, e.amount, e.resulting_balance) for e in history.entries] == [
        ("Daily reward", 15, 15)
    ]


async def test_midnight_and_no_catchup(database_runtime: DatabaseRuntime) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    now = DAY_MS - 1
    daily = service(r, clock=lambda: now)
    assert (await daily.inspect(discord_user_id=123)).status == "available"
    first = await daily.claim(discord_user_id=123, interaction_id=2, claim_period=0)
    assert first.balance == 15
    assert (await daily.inspect(discord_user_id=123)).status == "already_claimed"
    now = DAY_MS
    assert (await daily.inspect(discord_user_id=123)).status == "available"
    assert (
        await daily.claim(discord_user_id=123, interaction_id=3, claim_period=0)
    ).status == "expired"
    assert (await daily.claim(discord_user_id=123, interaction_id=4, claim_period=1)).balance == 30
    now = DAY_MS * 20
    assert (await daily.claim(discord_user_id=123, interaction_id=5, claim_period=20)).balance == 45
    assert (await daily.claim(discord_user_id=123, interaction_id=2, claim_period=0)).balance == 15
    reconcile(r)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("unjoined", "unjoined"),
        ("inactive", "inactive"),
        ("wallet", "unavailable"),
        ("disabled", "disabled"),
        ("frozen", "disabled"),
        ("global", "disabled"),
    ],
)
async def test_denials_do_not_repair_or_mint(
    database_runtime: DatabaseRuntime, case: str, expected: str
) -> None:
    r = database_runtime
    if case != "unjoined":
        await joins(r).join(discord_user_id=123, interaction_id=1)
    with closing(sqlite3.connect(r.database_path)) as db, db:
        if case == "inactive":
            db.execute("UPDATE players SET lifecycle_state='pseudonymized'")
        elif case == "wallet":
            db.execute("DELETE FROM economy_account_balances")
            db.execute("DELETE FROM economy_accounts")
        elif case == "projection":
            db.execute("DELETE FROM economy_account_balances")
        elif case in {"frozen", "global"}:
            db.execute(
                "INSERT INTO safety_restrictions VALUES (?)", (123 if case == "frozen" else 0,)
            )
        before = tuple(db.iterdump())
    daily = service(r, eligibility=Eligibility(case != "disabled"))
    assert (await daily.inspect(discord_user_id=123)).status == expected
    with closing(sqlite3.connect(r.database_path)) as db:
        assert tuple(db.iterdump()) == before
    assert (
        await daily.claim(discord_user_id=123, interaction_id=2, claim_period=0)
    ).status == expected
    assert rows(r.database_path, "SELECT * FROM economy_daily_claims") == []
    assert rows(r.database_path, "SELECT * FROM economy_ledger_transactions") == []


@pytest.mark.parametrize("phase", ["projection", "receipt", "cancel"])
async def test_atomic_rollback(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    if phase == "projection":
        project = SqlAlchemyGrantRepository.project

        async def fail(self: SqlAlchemyGrantRepository, *args: object) -> None:
            await project(self, *args)  # pyright: ignore[reportArgumentType]
            raise RuntimeError("injected projection failure")

        monkeypatch.setattr(SqlAlchemyGrantRepository, "project", fail)
    else:
        issue = SqlAlchemyDailyRepository.issue

        async def fail_issue(self: SqlAlchemyDailyRepository, *args: object) -> None:
            await issue(self, *args)  # pyright: ignore[reportArgumentType]
            if phase == "cancel":
                raise asyncio.CancelledError()
            raise RuntimeError("injected receipt failure")

        monkeypatch.setattr(SqlAlchemyDailyRepository, "issue", fail_issue)
    with pytest.raises(asyncio.CancelledError if phase == "cancel" else RuntimeError):
        await service(r).claim(discord_user_id=123, interaction_id=2, claim_period=0)
    assert rows(r.database_path, "SELECT * FROM economy_daily_claims") == []
    assert rows(r.database_path, "SELECT * FROM economy_ledger_transactions") == []
    assert rows(r.database_path, "SELECT account_kind,amount FROM economy_account_balances") == [
        ("wallet", 0)
    ]
    assert rows(r.database_path, "SELECT namespace FROM operations_transport_requests") == [
        ("players.join",)
    ]
    reconcile(r)


@pytest.mark.parametrize(
    "case", ["wallet_amount", "wallet_version", "issuance_amount", "issuance_version"]
)
async def test_overflow_rolls_back(database_runtime: DatabaseRuntime, case: str) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    await service(r).claim(discord_user_id=123, interaction_id=2, claim_period=0)
    with closing(sqlite3.connect(r.database_path)) as db, db:
        kind, column = case.split("_")
        db.execute(
            f"UPDATE economy_account_balances SET {column}=? WHERE account_kind=?",
            (INT64_MIN if case == "issuance_amount" else INT64_MAX, kind),
        )
        before = tuple(db.iterdump())
    with pytest.raises(ExactIntegerOutOfRange):
        await service(r, clock=lambda: DAY_MS).claim(
            discord_user_id=123, interaction_id=3, claim_period=1
        )
    with closing(sqlite3.connect(r.database_path)) as db:
        assert tuple(db.iterdump()) == before


async def test_current_freeze_and_time_after_writer_admission(
    database_runtime: DatabaseRuntime,
) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    now = DAY_MS - 1
    daily = service(r, clock=lambda: now)
    async with r.unit_of_work_factory():
        task = asyncio.create_task(
            daily.claim(discord_user_id=123, interaction_id=2, claim_period=0)
        )
        await asyncio.sleep(0.02)
        assert not task.done()
        now = DAY_MS
    assert (await task).status == "expired"
    assert rows(r.database_path, "SELECT * FROM economy_daily_claims") == []


@pytest.mark.parametrize("recursive", [0, 1])
async def test_sealed_daily_receipt_and_ledger(
    database_runtime: DatabaseRuntime, recursive: int
) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    await service(r).claim(discord_user_id=123, interaction_id=2, claim_period=0)
    statements = [
        "UPDATE economy_daily_claims SET after_amount=16",
        "DELETE FROM economy_daily_claims",
        "INSERT OR REPLACE INTO economy_daily_claims SELECT * FROM economy_daily_claims",
        "UPDATE economy_ledger_transactions SET reason_code='changed'",
        "DELETE FROM economy_ledger_transactions",
        "INSERT OR REPLACE INTO economy_ledger_transactions "
        "SELECT * FROM economy_ledger_transactions",
        "UPDATE economy_ledger_postings SET amount=1",
        "DELETE FROM economy_ledger_postings",
        "INSERT OR REPLACE INTO economy_ledger_postings SELECT * FROM economy_ledger_postings",
    ]
    with closing(sqlite3.connect(r.database_path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        for sql in statements:
            with pytest.raises(sqlite3.IntegrityError), db:
                db.execute(sql)
    reconcile(r)
