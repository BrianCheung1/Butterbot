from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from butterbot.application.operations.idempotency import (
    DISCORD_RETENTION_MS,
    FingerprintConflict,
    InvalidTransportRequest,
    NullOperationsTelemetry,
    TransportIdempotencyCoordinator,
    TransportIdempotencyMaintenance,
    TransportRequest,
    discord_retention_registry,
    request_fingerprint,
)
from butterbot.application.operations.ports import StableOutcome, TransportActor
from butterbot.application.transactions import ApplicationTransactionRunner, UnitOfWork
from butterbot.infrastructure.persistence.database import (
    DatabaseRuntime,
    is_sqlite_busy,
)
from butterbot.infrastructure.persistence.repositories import (
    IncompleteTransportRequest,
    SqlAlchemyTransportIdempotencyRepository,
)

NAMESPACE = "operations.test_mutation"


def _request(
    *,
    key: str = "interaction-1",
    amount: int = 1,
    actor_reference: str = "1234",
) -> TransportRequest:
    return TransportRequest(
        namespace=NAMESPACE,
        transport_key=key,
        actor=TransportActor(kind="discord_user", reference=actor_reference),
        semantic_input={"amount": amount},
    )


def _coordinator(
    telemetry: NullOperationsTelemetry | None = None,
) -> TransportIdempotencyCoordinator:
    return TransportIdempotencyCoordinator(
        discord_retention_registry(NAMESPACE),
        telemetry=telemetry or NullOperationsTelemetry(),
    )


@pytest.mark.parametrize(
    "transport_request",
    [
        _request(key="key\x00hidden"),
        _request(actor_reference="actor\x00hidden"),
    ],
)
def test_transport_identity_rejects_embedded_nul(
    transport_request: TransportRequest,
) -> None:
    with pytest.raises(InvalidTransportRequest, match="NUL"):
        request_fingerprint(transport_request)


@pytest.mark.parametrize(
    "actor_reference",
    ["", "   ", "\t", "\n", " leading", "trailing ", "internal whitespace"],
)
def test_transport_actor_reference_rejects_whitespace_and_empty_values(
    actor_reference: str,
) -> None:
    with pytest.raises(InvalidTransportRequest, match="actor reference"):
        request_fingerprint(_request(actor_reference=actor_reference))


async def _execute(
    database_runtime: DatabaseRuntime,
    request: TransportRequest,
    operation: Callable[[], Awaitable[StableOutcome]],
    *,
    now_ms: int = 1_000,
) -> tuple[StableOutcome, bool, UUID]:
    coordinator = _coordinator()
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        result = await coordinator.execute(
            unit_of_work,
            request,
            completed_at_ms=now_ms,
            operation=operation,
        )
        return result.outcome, result.replayed, result.request_id


async def test_successful_outcome_replays_without_reexecuting_use_case(
    database_runtime: DatabaseRuntime,
) -> None:
    executions = 0

    async def apply() -> StableOutcome:
        nonlocal executions
        executions += 1
        return StableOutcome.success("test.applied", {"value": 7})

    first = await _execute(database_runtime, _request(), apply)
    replay = await _execute(database_runtime, _request(), apply)

    assert first[0] == replay[0]
    assert first[1] is False
    assert replay[1] is True
    assert first[2] == replay[2]
    assert executions == 1


async def test_same_transport_key_with_different_fingerprint_conflicts(
    database_runtime: DatabaseRuntime,
) -> None:
    async def apply() -> StableOutcome:
        return StableOutcome.success("test.applied")

    await _execute(database_runtime, _request(amount=1), apply)

    with pytest.raises(FingerprintConflict):
        await _execute(database_runtime, _request(amount=2), apply)


async def test_typed_rejection_is_committed_and_replayed(
    database_runtime: DatabaseRuntime,
) -> None:
    executions = 0

    async def reject() -> StableOutcome:
        nonlocal executions
        executions += 1
        return StableOutcome.typed_rejection("test.not_allowed", {"reason": "disabled"})

    first = await _execute(database_runtime, _request(), reject)
    replay = await _execute(database_runtime, _request(), reject)

    assert first[0].kind == "typed_rejection"
    assert replay[0] == first[0]
    assert replay[1] is True
    assert executions == 1


async def test_unexpected_failure_rolls_back_unfinished_claim(
    database_runtime: DatabaseRuntime,
    migrated_database: Path,
) -> None:
    async def fail() -> StableOutcome:
        raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        await _execute(database_runtime, _request(), fail)

    connection = sqlite3.connect(migrated_database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM operations_transport_requests"
        ).fetchone() == (0,)
    finally:
        connection.close()


async def test_outcome_and_owning_state_roll_back_atomically(
    database_runtime: DatabaseRuntime,
    migrated_database: Path,
) -> None:
    coordinator = _coordinator()
    with pytest.raises(RuntimeError, match="after outcome"):
        async with database_runtime.unit_of_work_factory() as unit_of_work:

            async def apply() -> StableOutcome:
                await unit_of_work.players.create_if_absent(
                    player_id=uuid4(), discord_user_id=900, created_at_ms=1
                )
                return StableOutcome.success("test.applied")

            await coordinator.execute(
                unit_of_work,
                _request(),
                completed_at_ms=1_000,
                operation=apply,
            )
            raise RuntimeError("after outcome")

    connection = sqlite3.connect(migrated_database)
    try:
        counts = (
            connection.execute("SELECT COUNT(*) FROM players").fetchone(),
            connection.execute("SELECT COUNT(*) FROM operations_transport_requests").fetchone(),
        )
    finally:
        connection.close()
    assert counts == ((0,), (0,))


async def test_unit_of_work_refuses_to_commit_pending_transport_claim(
    database_runtime: DatabaseRuntime,
) -> None:
    with pytest.raises(IncompleteTransportRequest):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await unit_of_work.transport_requests.claim(
                request_id=uuid4(),
                namespace=NAMESPACE,
                transport_key="unfinished",
                actor=TransportActor(kind="discord_user", reference="1"),
                request_fingerprint="a" * 64,
            )


async def test_concurrent_same_key_executes_once_and_replays_one_outcome(
    database_runtime: DatabaseRuntime,
) -> None:
    executions = 0
    coordinator = _coordinator()
    runner = ApplicationTransactionRunner(
        database_runtime.unit_of_work_factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
    )

    async def use_case(unit_of_work: UnitOfWork) -> tuple[UUID, bool]:
        async def apply() -> StableOutcome:
            nonlocal executions
            executions += 1
            await asyncio.sleep(0)
            return StableOutcome.success("test.applied", {"execution": executions})

        result = await coordinator.execute(
            unit_of_work,
            _request(),
            completed_at_ms=1_000,
            operation=apply,
        )
        return result.request_id, result.replayed

    results = await asyncio.gather(*(runner.run(NAMESPACE, use_case) for _ in range(8)))

    assert executions == 1
    assert len({request_id for request_id, _ in results}) == 1
    assert sum(not replayed for _, replayed in results) == 1


async def test_discord_retention_is_seven_days_and_cleanup_is_incremental(
    database_runtime: DatabaseRuntime,
    migrated_database: Path,
) -> None:
    async def apply() -> StableOutcome:
        return StableOutcome.success("test.applied")

    await _execute(database_runtime, _request(), apply, now_ms=1_000)
    connection = sqlite3.connect(migrated_database)
    try:
        stored = connection.execute(
            "SELECT completed_at_ms, retain_until_ms FROM operations_transport_requests"
        ).fetchone()
    finally:
        connection.close()
    assert stored == (1_000, 1_000 + DISCORD_RETENTION_MS)

    maintenance = TransportIdempotencyMaintenance(NullOperationsTelemetry())
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        deleted = await maintenance.cleanup(
            unit_of_work,
            now_ms=1_000 + DISCORD_RETENTION_MS,
            limit=1,
        )
    assert deleted == 1


class _RecordingTelemetry(NullOperationsTelemetry):
    def __init__(self) -> None:
        self.idempotency_events: list[tuple[str, str]] = []
        self.storage_events: list[tuple[str, int]] = []

    def transport_idempotency(self, *, namespace: str, outcome: str) -> None:
        self.idempotency_events.append((namespace, outcome))

    def transport_storage(
        self,
        *,
        stats: object,
        deleted: int,
        duration_ms: float,
        outcome: str,
    ) -> None:
        del stats, duration_ms
        self.storage_events.append((outcome, deleted))


class _ExplodingTelemetry(NullOperationsTelemetry):
    def transport_idempotency(self, *, namespace: str, outcome: str) -> None:
        del namespace, outcome
        raise RuntimeError("idempotency telemetry failed")

    def transport_storage(
        self,
        *,
        stats: object,
        deleted: int,
        duration_ms: float,
        outcome: str,
    ) -> None:
        del stats, deleted, duration_ms, outcome
        raise RuntimeError("storage telemetry failed")


async def test_telemetry_failure_does_not_replace_successful_replay(
    database_runtime: DatabaseRuntime,
) -> None:
    expected = StableOutcome.success("test.applied", {"value": 7})
    await _execute(
        database_runtime,
        _request(),
        lambda: asyncio.sleep(0, result=expected),
    )
    coordinator = _coordinator(_ExplodingTelemetry())
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        replay = await coordinator.execute(
            unit_of_work,
            _request(),
            completed_at_ms=1_000,
            operation=lambda: asyncio.sleep(0, result=StableOutcome.success("wrong")),
        )
    assert replay.replayed is True
    assert replay.outcome == expected


async def test_telemetry_failure_does_not_replace_typed_rejection_replay(
    database_runtime: DatabaseRuntime,
) -> None:
    expected = StableOutcome.typed_rejection("test.not_allowed", {"reason": "disabled"})
    await _execute(
        database_runtime,
        _request(),
        lambda: asyncio.sleep(0, result=expected),
    )
    coordinator = _coordinator(_ExplodingTelemetry())
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        replay = await coordinator.execute(
            unit_of_work,
            _request(),
            completed_at_ms=1_000,
            operation=lambda: asyncio.sleep(0, result=StableOutcome.success("wrong")),
        )
    assert replay.replayed is True
    assert replay.outcome == expected


async def test_telemetry_failure_does_not_replace_fingerprint_conflict(
    database_runtime: DatabaseRuntime,
) -> None:
    await _execute(
        database_runtime,
        _request(amount=1),
        lambda: asyncio.sleep(0, result=StableOutcome.success("test.applied")),
    )
    coordinator = _coordinator(_ExplodingTelemetry())
    with pytest.raises(FingerprintConflict):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await coordinator.execute(
                unit_of_work,
                _request(amount=2),
                completed_at_ms=1_000,
                operation=lambda: asyncio.sleep(0, result=StableOutcome.success("wrong")),
            )


@pytest.mark.parametrize(
    "outcome",
    [
        StableOutcome.success("test.applied"),
        StableOutcome.typed_rejection("test.not_allowed"),
    ],
)
async def test_post_commit_telemetry_failure_preserves_confirmed_outcome(
    database_runtime: DatabaseRuntime,
    outcome: StableOutcome,
) -> None:
    coordinator = _coordinator(_ExplodingTelemetry())
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        result = await coordinator.execute(
            unit_of_work,
            _request(),
            completed_at_ms=1_000,
            operation=lambda: asyncio.sleep(0, result=outcome),
        )
    assert result.outcome == outcome


async def test_cleanup_telemetry_failure_does_not_replace_committed_deletion(
    database_runtime: DatabaseRuntime,
) -> None:
    await _execute(
        database_runtime,
        _request(),
        lambda: asyncio.sleep(0, result=StableOutcome.success("test.applied")),
        now_ms=1_000,
    )
    maintenance = TransportIdempotencyMaintenance(_ExplodingTelemetry())
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        deleted = await maintenance.cleanup(
            unit_of_work,
            now_ms=1_000 + DISCORD_RETENTION_MS,
            limit=1,
        )
    assert deleted == 1


async def test_cleanup_failure_telemetry_does_not_replace_cleanup_error(
    database_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CleanupFailure(RuntimeError):
        pass

    async def fail_cleanup(
        repository: SqlAlchemyTransportIdempotencyRepository,
        *,
        now_ms: int,
        limit: int,
    ) -> int:
        del repository, now_ms, limit
        raise CleanupFailure("delete failed")

    monkeypatch.setattr(SqlAlchemyTransportIdempotencyRepository, "delete_expired", fail_cleanup)
    maintenance = TransportIdempotencyMaintenance(_ExplodingTelemetry())
    with pytest.raises(CleanupFailure, match="delete failed"):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await maintenance.cleanup(unit_of_work, now_ms=1_000, limit=1)


async def test_applied_telemetry_is_emitted_only_after_commit(
    database_runtime: DatabaseRuntime,
) -> None:
    telemetry = _RecordingTelemetry()
    coordinator = _coordinator(telemetry)
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        await coordinator.execute(
            unit_of_work,
            _request(),
            completed_at_ms=1_000,
            operation=lambda: asyncio.sleep(0, result=StableOutcome.success("test.applied")),
        )
        assert telemetry.idempotency_events == []

    assert telemetry.idempotency_events == [(NAMESPACE, "applied")]


async def test_rollback_does_not_emit_committed_success_telemetry(
    database_runtime: DatabaseRuntime,
) -> None:
    telemetry = _RecordingTelemetry()
    coordinator = _coordinator(telemetry)
    with pytest.raises(RuntimeError, match="rollback"):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await coordinator.execute(
                unit_of_work,
                _request(),
                completed_at_ms=1_000,
                operation=lambda: asyncio.sleep(0, result=StableOutcome.success("test.applied")),
            )
            raise RuntimeError("rollback")

    assert telemetry.idempotency_events == []


async def test_cleanup_telemetry_is_emitted_only_after_commit(
    database_runtime: DatabaseRuntime,
) -> None:
    async def apply() -> StableOutcome:
        return StableOutcome.success("test.applied")

    await _execute(database_runtime, _request(), apply, now_ms=1_000)
    telemetry = _RecordingTelemetry()
    maintenance = TransportIdempotencyMaintenance(telemetry)
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        deleted = await maintenance.cleanup(
            unit_of_work,
            now_ms=1_000 + DISCORD_RETENTION_MS,
            limit=1,
        )
        assert deleted == 1
        assert telemetry.storage_events == []

    assert telemetry.storage_events == [("completed", 1)]


async def test_cleanup_rollback_does_not_emit_committed_deletion_telemetry(
    database_runtime: DatabaseRuntime,
) -> None:
    async def apply() -> StableOutcome:
        return StableOutcome.success("test.applied")

    await _execute(database_runtime, _request(), apply, now_ms=1_000)
    telemetry = _RecordingTelemetry()
    maintenance = TransportIdempotencyMaintenance(telemetry)
    with pytest.raises(RuntimeError, match="rollback"):
        async with database_runtime.unit_of_work_factory() as unit_of_work:
            await maintenance.cleanup(
                unit_of_work,
                now_ms=1_000 + DISCORD_RETENTION_MS,
                limit=1,
            )
            raise RuntimeError("rollback")

    assert telemetry.storage_events == []


async def test_typed_rejection_does_not_change_owning_state(
    database_runtime: DatabaseRuntime,
    migrated_database: Path,
) -> None:
    async def reject() -> StableOutcome:
        return StableOutcome.typed_rejection("test.not_allowed")

    outcome, _, _ = await _execute(database_runtime, _request(), reject)
    assert outcome.kind == "typed_rejection"
    connection = sqlite3.connect(migrated_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM players").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM operations_transport_requests "
            "WHERE outcome_kind = 'typed_rejection'"
        ).fetchone() == (1,)
    finally:
        connection.close()


async def test_typed_rejection_telemetry_is_emitted_only_after_commit(
    database_runtime: DatabaseRuntime,
) -> None:
    telemetry = _RecordingTelemetry()
    coordinator = _coordinator(telemetry)
    async with database_runtime.unit_of_work_factory() as unit_of_work:
        await coordinator.execute(
            unit_of_work,
            _request(),
            completed_at_ms=1_000,
            operation=lambda: asyncio.sleep(
                0, result=StableOutcome.typed_rejection("test.not_allowed")
            ),
        )
        assert telemetry.idempotency_events == []

    assert telemetry.idempotency_events == [(NAMESPACE, "typed_rejection")]


async def test_concurrent_same_key_different_actor_conflicts(
    database_runtime: DatabaseRuntime,
) -> None:
    coordinator = _coordinator()
    runner = ApplicationTransactionRunner(
        database_runtime.unit_of_work_factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
    )

    async def execute_for(actor_reference: str, unit_of_work: UnitOfWork) -> bool:
        result = await coordinator.execute(
            unit_of_work,
            _request(actor_reference=actor_reference),
            completed_at_ms=1_000,
            operation=lambda: asyncio.sleep(0, result=StableOutcome.success("test.applied")),
        )
        return result.replayed

    results = await asyncio.gather(
        runner.run(NAMESPACE, lambda unit_of_work: execute_for("actor-1", unit_of_work)),
        runner.run(NAMESPACE, lambda unit_of_work: execute_for("actor-2", unit_of_work)),
        return_exceptions=True,
    )

    assert sum(isinstance(result, FingerprintConflict) for result in results) == 1
    assert sum(result is False for result in results) == 1


async def test_concurrent_same_key_different_semantic_input_conflicts(
    database_runtime: DatabaseRuntime,
) -> None:
    coordinator = _coordinator()
    runner = ApplicationTransactionRunner(
        database_runtime.unit_of_work_factory,
        is_retryable=is_sqlite_busy,
        telemetry=NullOperationsTelemetry(),
    )

    async def execute_for(amount: int, unit_of_work: UnitOfWork) -> bool:
        result = await coordinator.execute(
            unit_of_work,
            _request(amount=amount),
            completed_at_ms=1_000,
            operation=lambda: asyncio.sleep(0, result=StableOutcome.success("test.applied")),
        )
        return result.replayed

    results = await asyncio.gather(
        runner.run(NAMESPACE, lambda unit_of_work: execute_for(1, unit_of_work)),
        runner.run(NAMESPACE, lambda unit_of_work: execute_for(2, unit_of_work)),
        return_exceptions=True,
    )

    assert sum(isinstance(result, FingerprintConflict) for result in results) == 1
    assert sum(result is False for result in results) == 1
