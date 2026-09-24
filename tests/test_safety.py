import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from tests.test_join import service as joins

from butterbot.application.economy.balance import BalanceResult, BalanceService
from butterbot.application.operations.idempotency import (
    FingerprintConflict,
    NullOperationsTelemetry,
    TransportIdempotencyCoordinator,
    discord_retention_registry,
)
from butterbot.application.safety.ports import Capability, Operation
from butterbot.application.safety.service import (
    DAY_MS,
    SAFETY_NAMESPACES,
    SafetyPolicy,
    SafetyService,
)
from butterbot.application.transactions import ApplicationTransactionRunner
from butterbot.infrastructure.persistence.database import DatabaseRuntime, is_sqlite_busy
from butterbot.infrastructure.persistence.safety import SqlAlchemySafetyRepository

TEST_POLICY = SafetyPolicy(100, 1000, 10000)


def service(
    runtime: DatabaseRuntime,
    *,
    now: int = 1000,
    policy: SafetyPolicy | None = TEST_POLICY,
) -> SafetyService:
    telemetry = NullOperationsTelemetry()
    return SafetyService(
        ApplicationTransactionRunner(
            runtime.unit_of_work_factory, is_retryable=is_sqlite_busy, telemetry=telemetry
        ),
        TransportIdempotencyCoordinator(
            discord_retention_registry(*SAFETY_NAMESPACES), telemetry=telemetry
        ),
        policy=policy,
        clock_ms=lambda: now,
        id_factory=uuid4,
        alert=lambda action, audit: None,
    )


def rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql).fetchall()


async def test_bootstrap_once_and_revocation_survives_rebootstrap(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime)
    assert await admin.bootstrap((111, 222))
    assert len(rows(database_runtime.database_path, "SELECT * FROM safety_capabilities")) == 10
    result = await admin.change_capability(
        actor_id=111,
        target_id=222,
        capability="players.inspect",
        enabled=False,
        reason="revoked",
        interaction_id=1,
    )
    assert result.status == "applied"
    assert not await admin.bootstrap((222, 333))
    assert (await admin.inspect(actor_id=222, target_id=999, reason="support")).status == "denied"
    assert (await admin.inspect(actor_id=333, target_id=999, reason="support")).status == "denied"


async def test_unauthorized_changes_and_inspection_do_not_trust_discord_roles(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime)
    assert (
        await admin.change_capability(
            actor_id=999,
            target_id=999,
            capability="capabilities.manage",
            enabled=True,
            reason="I am a guild administrator",
            interaction_id=1,
        )
    ).status == "denied"
    assert (
        await admin.inspect(actor_id=999, target_id=123, reason="guild administrator")
    ).status == "denied"
    assert rows(database_runtime.database_path, "SELECT * FROM safety_capabilities") == []
    assert len(rows(database_runtime.database_path, "SELECT * FROM safety_access_audit")) == 2


async def test_single_freeze_blocks_join_and_preserves_private_balance_and_safe_release(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111,))
    await joins(database_runtime).join(discord_user_id=123, interaction_id=10)
    result = await admin.propose(
        actor_id=111,
        operation="freeze",
        targets=(123,),
        amount=0,
        reason="incident",
        interaction_id=1,
    )
    assert result.status == "applied"
    assert (
        await joins(database_runtime).join(discord_user_id=123, interaction_id=11)
    ).status == "disabled"
    assert await BalanceService(database_runtime.unit_of_work_factory.read_snapshot).balance(
        discord_user_id=123
    ) == BalanceResult("available", 0)
    inspection = await admin.inspect(actor_id=111, target_id=123, reason="support")
    assert inspection.frozen and inspection.amount == 0
    assert (
        await admin.propose(
            actor_id=111,
            operation="release",
            targets=(123,),
            amount=0,
            reason="resolved",
            interaction_id=2,
        )
    ).status == "applied"
    assert (
        await joins(database_runtime).join(discord_user_id=123, interaction_id=12)
    ).status == "already_joined"
    assert rows(database_runtime.database_path, "SELECT * FROM economy_ledger_transactions") == []


@pytest.mark.parametrize(
    "operation,targets,amount",
    [
        ("freeze", (123, 456), 0),
        ("release", (123, 456), 0),
        ("freeze", (0,), 0),
        ("grant", (123,), 101),
        ("grant", (123, 456), 1),
    ],
)
async def test_bulk_global_and_above_threshold_require_distinct_approver(
    database_runtime: DatabaseRuntime, operation: Operation, targets: tuple[int, ...], amount: int
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    proposal = await admin.propose(
        actor_id=111,
        operation=operation,
        targets=targets,
        amount=amount,
        reason="reviewed",
        interaction_id=1,
    )  # pyright: ignore[reportArgumentType]
    assert proposal.status == "pending" and proposal.proposal_id is not None
    assert (
        await admin.approve(actor_id=111, proposal_id=proposal.proposal_id, interaction_id=2)
    ).status == "self_approval"
    assert (
        await admin.approve(actor_id=333, proposal_id=proposal.proposal_id, interaction_id=3)
    ).status == "denied"
    results = await asyncio.gather(
        *(
            admin.approve(actor_id=222, proposal_id=proposal.proposal_id, interaction_id=4 + i)
            for i in range(3)
        )
    )
    expected = "approved" if operation == "grant" else "applied"
    assert [r.status for r in results].count(expected) == 1
    assert [r.status for r in results].count("already_finished") == 2
    assert rows(database_runtime.database_path, "SELECT * FROM economy_ledger_transactions") == []
    if targets == (0,):
        assert (
            await joins(database_runtime).join(discord_user_id=999, interaction_id=99)
        ).status == "disabled"


async def test_ceiling_and_threshold_boundaries_and_expiry(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime, policy=SafetyPolicy(100, 200, 300))
    await admin.bootstrap((111, 222))
    assert (
        await admin.propose(
            actor_id=111,
            operation="grant",
            targets=(123,),
            amount=100,
            reason="boundary",
            interaction_id=1,
        )
    ).status == "approved"
    pending = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=200,
        reason="boundary",
        interaction_id=2,
    )
    assert pending.status == "pending" and pending.proposal_id is not None
    assert (
        await admin.propose(
            actor_id=111,
            operation="grant",
            targets=(123,),
            amount=1,
            reason="rolling overflow",
            interaction_id=3,
        )
    ).status == "limit"
    assert (
        await admin.propose(
            actor_id=222,
            operation="grant",
            targets=(123,),
            amount=201,
            reason="operation overflow",
            interaction_id=4,
        )
    ).status == "limit"
    assert (
        await service(database_runtime, now=1000 + DAY_MS).approve(
            actor_id=222, proposal_id=pending.proposal_id, interaction_id=5
        )
    ).status == "expired"


@pytest.mark.parametrize(
    "revoked_actor,capability", [(111, "grants.propose"), (222, "proposals.approve")]
)
async def test_revocation_is_rechecked_at_approval(
    database_runtime: DatabaseRuntime, revoked_actor: int, capability: Capability
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    proposal = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=101,
        reason="pending",
        interaction_id=1,
    )
    assert proposal.proposal_id is not None
    await admin.change_capability(
        actor_id=111,
        target_id=revoked_actor,
        capability=capability,
        enabled=False,
        reason="revoked",
        interaction_id=2,
    )  # pyright: ignore[reportArgumentType]
    assert (
        await admin.approve(actor_id=222, proposal_id=proposal.proposal_id, interaction_id=3)
    ).status == "denied"


async def test_freeze_and_policy_are_rechecked_at_grant_approval(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    proposal = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=101,
        reason="pending",
        interaction_id=1,
    )
    assert proposal.proposal_id is not None
    assert (
        await service(database_runtime, policy=SafetyPolicy(10, 100, 100)).approve(
            actor_id=222, proposal_id=proposal.proposal_id, interaction_id=2
        )
    ).status == "limit"
    await admin.propose(
        actor_id=111,
        operation="freeze",
        targets=(123,),
        amount=0,
        reason="incident",
        interaction_id=3,
    )
    assert (
        await admin.approve(actor_id=222, proposal_id=proposal.proposal_id, interaction_id=4)
    ).status == "frozen"
    assert (
        await admin.propose(
            actor_id=111,
            operation="grant",
            targets=(123,),
            amount=1,
            reason="frozen",
            interaction_id=5,
        )
    ).status == "frozen"


async def test_permanent_receipt_prevents_expired_replay_from_regranting(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111,))
    kwargs = dict(
        actor_id=111,
        target_id=222,
        capability="players.inspect",
        enabled=True,
        reason="support",
        interaction_id=1,
    )
    assert (await admin.change_capability(**kwargs)).status == "applied"  # pyright: ignore[reportArgumentType]
    await admin.change_capability(
        actor_id=111,
        target_id=222,
        capability="players.inspect",
        enabled=False,
        reason="revoked",
        interaction_id=2,
    )
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        db.execute("DELETE FROM operations_transport_requests")
    assert (await admin.change_capability(**kwargs)).status == "applied"  # pyright: ignore[reportArgumentType]
    assert (await admin.inspect(actor_id=222, target_id=123, reason="support")).status == "denied"
    with pytest.raises(FingerprintConflict):
        await admin.change_capability(
            actor_id=111,
            target_id=333,
            capability="players.inspect",
            enabled=True,
            reason="support",
            interaction_id=1,
        )


async def test_audit_failure_rolls_back_capabilities_and_transport(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111,))

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(SqlAlchemySafetyRepository, "audit", fail)
    with pytest.raises(RuntimeError, match="injected"):
        await admin.change_capability(
            actor_id=111,
            target_id=222,
            capability="players.inspect",
            enabled=True,
            reason="support",
            interaction_id=1,
        )
    assert (
        rows(database_runtime.database_path, "SELECT * FROM safety_capabilities WHERE actor_id=222")
        == []
    )
    assert rows(database_runtime.database_path, "SELECT * FROM operations_transport_requests") == []


@pytest.mark.parametrize("table", ["safety_access_audit", "safety_bootstrap"])
@pytest.mark.parametrize("attack", ["update", "delete", "replace"])
async def test_audit_and_bootstrap_immutable_even_without_recursive_triggers(
    database_runtime: DatabaseRuntime, table: str, attack: str
) -> None:
    await service(database_runtime).bootstrap((111,))
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        db.execute("PRAGMA recursive_triggers=OFF")
        with pytest.raises(sqlite3.IntegrityError):
            if attack == "update":
                db.execute(f"UPDATE {table} SET created_at_ms=2")
            elif attack == "delete":
                db.execute(f"DELETE FROM {table}")
            else:
                db.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")


async def test_unconfigured_policy_does_not_create_proposals(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime, policy=None)
    await admin.bootstrap((111,))
    assert (
        await admin.propose(
            actor_id=111,
            operation="freeze",
            targets=(123,),
            amount=0,
            reason="incident",
            interaction_id=1,
        )
    ).status == "unconfigured"
    assert rows(database_runtime.database_path, "SELECT * FROM safety_proposals") == []


async def test_proposal_preview_requires_durable_authority_and_audits(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    proposed = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123, 456),
        amount=2,
        reason="review these targets",
        interaction_id=1,
    )
    assert proposed.proposal_id is not None
    denied = await admin.view_proposal(actor_id=333, proposal_id=proposed.proposal_id)
    assert denied.status == "denied" and denied.proposal is None
    allowed = await admin.view_proposal(actor_id=222, proposal_id=proposed.proposal_id)
    assert allowed.proposal is not None
    assert (allowed.proposal.targets, allowed.proposal.amount, allowed.proposal.reason) == (
        (123, 456),
        2,
        "review these targets",
    )
    await admin.change_capability(
        actor_id=111,
        target_id=222,
        capability="proposals.approve",
        enabled=False,
        reason="revoked",
        interaction_id=2,
    )
    denied = await admin.view_proposal(actor_id=222, proposal_id=proposed.proposal_id)
    assert denied.status == "denied" and denied.proposal is None
    assert (
        len(
            rows(
                database_runtime.database_path,
                "SELECT * FROM safety_access_audit WHERE action='proposal.inspect'",
            )
        )
        == 1
    )


async def test_bootstrap_rollback_and_concurrent_once(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = service(database_runtime)
    original = SqlAlchemySafetyRepository.audit

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected bootstrap audit failure")

    monkeypatch.setattr(SqlAlchemySafetyRepository, "audit", fail)
    with pytest.raises(RuntimeError, match="injected"):
        await admin.bootstrap((111,))
    assert rows(database_runtime.database_path, "SELECT * FROM safety_bootstrap") == []
    assert rows(database_runtime.database_path, "SELECT * FROM safety_capabilities") == []
    monkeypatch.setattr(SqlAlchemySafetyRepository, "audit", original)
    results = await asyncio.gather(*(admin.bootstrap((actor,)) for actor in (111, 222, 333)))
    assert results.count(True) == 1
    assert len(rows(database_runtime.database_path, "SELECT * FROM safety_capabilities")) == 5


async def test_safety_alert_failure_does_not_undo_committed_action(
    database_runtime: DatabaseRuntime,
) -> None:
    def fail(action: str, audit_id: object) -> None:
        raise RuntimeError("injected sink failure")

    admin = service(database_runtime)
    admin._alert = fail  # pyright: ignore[reportPrivateUsage]
    assert await admin.bootstrap((111,))
    assert len(rows(database_runtime.database_path, "SELECT * FROM safety_access_audit")) == 1


async def test_concurrent_rolling_ceiling_reserves_each_proposal_once(
    database_runtime: DatabaseRuntime,
) -> None:
    admin = service(database_runtime, policy=SafetyPolicy(100, 100, 100))
    await admin.bootstrap((111,))
    results = await asyncio.gather(
        *(
            admin.propose(
                actor_id=111,
                operation="grant",
                targets=(123,),
                amount=60,
                reason="race",
                interaction_id=i,
            )
            for i in (1, 2)
        )
    )
    assert sorted(result.status for result in results) == ["approved", "limit"]
    assert len(rows(database_runtime.database_path, "SELECT * FROM safety_proposals")) == 1


async def test_proposal_transition_failure_rolls_back_restrictions(
    database_runtime: DatabaseRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    proposed = await admin.propose(
        actor_id=111,
        operation="freeze",
        targets=(123, 456),
        amount=0,
        reason="incident",
        interaction_id=1,
    )
    assert proposed.proposal_id is not None

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected transition failure")

    monkeypatch.setattr(SqlAlchemySafetyRepository, "finish_proposal", fail)
    with pytest.raises(RuntimeError, match="injected"):
        await admin.approve(actor_id=222, proposal_id=proposed.proposal_id, interaction_id=2)
    assert rows(database_runtime.database_path, "SELECT * FROM safety_restrictions") == []
    assert rows(database_runtime.database_path, "SELECT status FROM safety_proposals") == [
        ("pending",)
    ]
