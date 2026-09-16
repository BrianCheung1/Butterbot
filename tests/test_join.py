from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from butterbot.application.exact_integer import INT64_MAX, ExactIntegerOutOfRange
from butterbot.application.operations.idempotency import (
    DISCORD_RETENTION_MS,
    FingerprintConflict,
    NullOperationsTelemetry,
    TransportIdempotencyCoordinator,
    discord_retention_registry,
)
from butterbot.application.operations.mutation_eligibility import MutationEligibilityDecision
from butterbot.application.operations.ports import StableOutcome
from butterbot.application.players.join import JOIN_NAMESPACE, InvalidJoinOutcome, JoinService
from butterbot.application.transactions import ApplicationTransactionRunner
from butterbot.infrastructure.persistence.database import DatabaseRuntime, is_sqlite_busy
from butterbot.infrastructure.persistence.repositories import (
    PersistenceInvariantError,
    SqlAlchemyAccountRepository,
    SqlAlchemyTransportIdempotencyRepository,
)


@dataclass
class Eligibility:
    allowed: bool = True
    calls: int = 0

    def evaluate(self) -> MutationEligibilityDecision:
        self.calls += 1
        return MutationEligibilityDecision(self.allowed, "test_policy")


def service(runtime: DatabaseRuntime, policy: Eligibility | None = None) -> JoinService:
    return JoinService(
        ApplicationTransactionRunner(
            runtime.unit_of_work_factory,
            is_retryable=is_sqlite_busy,
            telemetry=NullOperationsTelemetry(),
        ),
        TransportIdempotencyCoordinator(discord_retention_registry(JOIN_NAMESPACE)),
        policy if policy is not None else Eligibility(),
        clock_ms=lambda: 1_000,
        id_factory=uuid4,
    )


def counts(path: Path) -> tuple[int, ...]:
    connection = sqlite3.connect(path)
    try:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "players",
                "economy_accounts",
                "economy_account_balances",
                "operations_transport_requests",
                "economy_ledger_transactions",
                "economy_ledger_postings",
                "operations_integrity_violations",
            )
        )
    finally:
        connection.close()


async def test_join_creates_zero_wallet_and_replays_with_seven_day_retention(
    database_runtime: DatabaseRuntime,
) -> None:
    policy = Eligibility()
    joins = service(database_runtime, policy)
    first = await joins.join(discord_user_id=123, interaction_id=456)
    replay = await joins.join(discord_user_id=123, interaction_id=456)
    assert (first.status, first.replayed) == ("created", False)
    assert (replay.status, replay.replayed) == ("created", True)
    assert policy.calls == 1
    assert counts(database_runtime.database_path) == (1, 1, 1, 1, 0, 0, 0)
    connection = sqlite3.connect(database_runtime.database_path)
    try:
        assert connection.execute(
            "SELECT amount, version FROM economy_account_balances"
        ).fetchall() == [(0, 0)]
        assert connection.execute("SELECT created_at_ms FROM players").fetchone() == (1_000,)
        assert connection.execute(
            "SELECT namespace, outcome_payload, completed_at_ms, retain_until_ms "
            "FROM operations_transport_requests"
        ).fetchone() == (JOIN_NAMESPACE, "{}", 1_000, 1_000 + DISCORD_RETENTION_MS)
    finally:
        connection.close()


@pytest.mark.parametrize("same_interaction", [False, True])
async def test_concurrent_joins_converge_on_one_complete_aggregate(
    database_runtime: DatabaseRuntime,
    same_interaction: bool,
) -> None:
    joins = service(database_runtime)
    results = await asyncio.gather(
        *(
            joins.join(discord_user_id=123, interaction_id=456 if same_interaction else 456 + i)
            for i in range(8)
        )
    )
    assert sum(result.status == "created" and not result.replayed for result in results) == 1
    assert sum(result.replayed for result in results) == (7 if same_interaction else 0)
    assert sum(result.status == "already_joined" for result in results) == (
        0 if same_interaction else 7
    )
    assert counts(database_runtime.database_path) == (
        1,
        1,
        1,
        1 if same_interaction else 8,
        0,
        0,
        0,
    )


async def test_concurrent_same_interaction_different_actor_cannot_create_second_player(
    database_runtime: DatabaseRuntime,
) -> None:
    joins = service(database_runtime)
    results = await asyncio.gather(
        joins.join(discord_user_id=123, interaction_id=456),
        joins.join(discord_user_id=124, interaction_id=456),
        return_exceptions=True,
    )
    assert sum(isinstance(result, FingerprintConflict) for result in results) == 1
    assert counts(database_runtime.database_path) == (1, 1, 1, 1, 0, 0, 0)


async def test_denial_is_stable_but_new_interaction_reevaluates_policy(
    database_runtime: DatabaseRuntime,
) -> None:
    policy = Eligibility(False)
    joins = service(database_runtime, policy)
    denied = await joins.join(discord_user_id=123, interaction_id=456)
    assert denied.status == "disabled"
    assert counts(database_runtime.database_path) == (0, 0, 0, 1, 0, 0, 0)
    policy.allowed = True
    replay = await joins.join(discord_user_id=123, interaction_id=456)
    assert (replay.status, replay.replayed) == ("disabled", True)
    assert policy.calls == 1
    assert (await joins.join(discord_user_id=123, interaction_id=457)).status == "created"
    policy.allowed = False
    assert (await joins.join(discord_user_id=123, interaction_id=457)).replayed
    assert (await joins.join(discord_user_id=123, interaction_id=458)).status == "disabled"
    assert counts(database_runtime.database_path) == (1, 1, 1, 3, 0, 0, 0)


@pytest.mark.parametrize("stage", ["wallet", "outcome"])
async def test_join_failure_rolls_back_entire_aggregate_and_claim_then_can_retry(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    joins = service(database_runtime)
    if stage == "wallet":

        async def fail_wallet(
            self: SqlAlchemyAccountRepository,
            *,
            account_id: UUID,
            player_id: UUID,
            created_at_ms: int,
            player_was_created: bool,
        ) -> None:
            del self, account_id, player_id, created_at_ms, player_was_created
            raise RuntimeError("injected after player insert")

        monkeypatch.setattr(SqlAlchemyAccountRepository, "create_wallet_if_absent", fail_wallet)
    else:
        original = SqlAlchemyTransportIdempotencyRepository.complete

        async def fail_completion(
            self: SqlAlchemyTransportIdempotencyRepository,
            *,
            request_id: UUID,
            outcome: StableOutcome,
            completed_at_ms: int,
            retain_until_ms: int,
        ) -> None:
            await original(
                self,
                request_id=request_id,
                outcome=outcome,
                completed_at_ms=completed_at_ms,
                retain_until_ms=retain_until_ms,
            )
            raise RuntimeError("injected after outcome insert")

        monkeypatch.setattr(SqlAlchemyTransportIdempotencyRepository, "complete", fail_completion)
    with pytest.raises(RuntimeError, match="injected"):
        await joins.join(discord_user_id=123, interaction_id=456)
    assert counts(database_runtime.database_path) == (0, 0, 0, 0, 0, 0, 0)
    monkeypatch.undo()
    assert (await joins.join(discord_user_id=123, interaction_id=456)).status == "created"


async def test_existing_join_preserves_balance_and_survives_transport_expiry(
    database_runtime: DatabaseRuntime,
) -> None:
    joins = service(database_runtime)
    await joins.join(discord_user_id=123, interaction_id=456)
    connection = sqlite3.connect(database_runtime.database_path)
    try:
        # Seed only a test projection to prove join never resets existing amounts/versions.
        connection.execute("UPDATE economy_account_balances SET amount=27, version=4")
        connection.execute("DELETE FROM operations_transport_requests")
        connection.commit()
        assert (
            await joins.join(discord_user_id=123, interaction_id=456)
        ).status == "already_joined"
        assert connection.execute(
            "SELECT amount, version FROM economy_account_balances"
        ).fetchall() == [(27, 4)]
    finally:
        connection.close()


async def test_join_does_not_reactivate_pseudonymized_player(
    database_runtime: DatabaseRuntime,
) -> None:
    joins = service(database_runtime)
    await joins.join(discord_user_id=123, interaction_id=456)
    connection = sqlite3.connect(database_runtime.database_path)
    try:
        connection.execute("UPDATE players SET lifecycle_state='pseudonymized'")
        connection.commit()
        assert (await joins.join(discord_user_id=123, interaction_id=457)).status == "inactive"
        assert connection.execute("SELECT lifecycle_state FROM players").fetchone() == (
            "pseudonymized",
        )
    finally:
        connection.close()
    assert counts(database_runtime.database_path) == (1, 1, 1, 2, 0, 0, 0)


async def test_join_refuses_to_repair_missing_existing_wallet(
    database_runtime: DatabaseRuntime,
) -> None:
    joins = service(database_runtime)
    await joins.join(discord_user_id=123, interaction_id=456)
    connection = sqlite3.connect(database_runtime.database_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("DELETE FROM economy_account_balances")
        connection.execute("DELETE FROM economy_accounts")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(PersistenceInvariantError, match="missing"):
        await joins.join(discord_user_id=123, interaction_id=457)
    assert counts(database_runtime.database_path) == (1, 0, 0, 1, 0, 0, 1)


@pytest.mark.parametrize("field", ["discord_user_id", "interaction_id"])
@pytest.mark.parametrize("invalid", [0, -1, True, INT64_MAX + 1])
async def test_invalid_join_identity_is_rejected_before_persistence(
    database_runtime: DatabaseRuntime,
    field: str,
    invalid: int,
) -> None:
    arguments = {"discord_user_id": 123, "interaction_id": 456, field: invalid}
    with pytest.raises(ExactIntegerOutOfRange):
        await service(database_runtime).join(**arguments)
    assert counts(database_runtime.database_path) == (0, 0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    "column,value",
    [
        ("outcome_code", "unexpected.code"),
        ("outcome_kind", "typed_rejection"),
        ("outcome_payload", '{"unexpected":1}'),
    ],
)
async def test_join_replay_rejects_incompatible_fixed_outcome(
    database_runtime: DatabaseRuntime,
    column: str,
    value: str,
) -> None:
    joins = service(database_runtime)
    await joins.join(discord_user_id=123, interaction_id=456)
    connection = sqlite3.connect(database_runtime.database_path)
    try:
        connection.execute(f"UPDATE operations_transport_requests SET {column}=?", (value,))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(InvalidJoinOutcome):
        await joins.join(discord_user_id=123, interaction_id=456)
    assert counts(database_runtime.database_path) == (1, 1, 1, 1, 0, 0, 0)


async def test_join_retries_failed_transaction_without_duplicate_aggregate_or_request(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = SqlAlchemyTransportIdempotencyRepository.complete
    attempts = 0

    async def fail_once(
        self: SqlAlchemyTransportIdempotencyRepository,
        *,
        request_id: UUID,
        outcome: StableOutcome,
        completed_at_ms: int,
        retain_until_ms: int,
    ) -> None:
        nonlocal attempts
        attempts += 1
        await original(
            self,
            request_id=request_id,
            outcome=outcome,
            completed_at_ms=completed_at_ms,
            retain_until_ms=retain_until_ms,
        )
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(SqlAlchemyTransportIdempotencyRepository, "complete", fail_once)
    result = await service(database_runtime).join(discord_user_id=123, interaction_id=456)
    assert (result.status, result.replayed) == ("created", False)
    assert attempts == 2
    assert counts(database_runtime.database_path) == (1, 1, 1, 1, 0, 0, 0)


async def test_cancelled_join_rolls_back_before_commit_and_can_retry(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    async def block_wallet(
        self: SqlAlchemyAccountRepository,
        *,
        account_id: UUID,
        player_id: UUID,
        created_at_ms: int,
        player_was_created: bool,
    ) -> None:
        del self, account_id, player_id, created_at_ms, player_was_created
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(SqlAlchemyAccountRepository, "create_wallet_if_absent", block_wallet)
    joins = service(database_runtime)
    task = asyncio.create_task(joins.join(discord_user_id=123, interaction_id=456))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert counts(database_runtime.database_path) == (0, 0, 0, 0, 0, 0, 0)
    monkeypatch.undo()
    assert (await joins.join(discord_user_id=123, interaction_id=456)).status == "created"
