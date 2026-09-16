from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from butterbot.application.exact_integer import require_int64
from butterbot.application.operations.idempotency import (
    TransportIdempotencyCoordinator,
    TransportRequest,
)
from butterbot.application.operations.mutation_eligibility import MutationEligibility
from butterbot.application.operations.ports import StableOutcome, TransportActor
from butterbot.application.transactions import ApplicationTransactionRunner, UnitOfWork

JOIN_NAMESPACE = "players.join"
type JoinStatus = Literal["created", "already_joined", "disabled", "inactive"]


@dataclass(frozen=True, slots=True)
class JoinResult:
    status: JoinStatus
    replayed: bool


class JoinUseCase(Protocol):
    async def join(self, *, discord_user_id: int, interaction_id: int) -> JoinResult: ...


class InvalidJoinOutcome(RuntimeError):
    """A stored join result is outside the fixed, payload-free outcome contract."""


def _result(outcome: StableOutcome, *, replayed: bool) -> JoinResult:
    # Join persists no input-derived payload: exactly {}, two serialized bytes.
    statuses: dict[tuple[str, str], JoinStatus] = {
        ("success", "players.joined"): "created",
        ("success", "players.already_joined"): "already_joined",
        ("typed_rejection", "players.join_disabled"): "disabled",
        ("typed_rejection", "players.join_inactive"): "inactive",
    }
    status = statuses.get((outcome.kind, outcome.code))
    if status is None or dict(outcome.payload) != {}:
        raise InvalidJoinOutcome("stored join outcome is incompatible")
    return JoinResult(status, replayed)


class JoinService:
    """Create one complete player/wallet aggregate in the owning transaction."""

    def __init__(
        self,
        transactions: ApplicationTransactionRunner,
        idempotency: TransportIdempotencyCoordinator,
        eligibility: MutationEligibility,
        *,
        clock_ms: Callable[[], int],
        id_factory: Callable[[], UUID],
    ) -> None:
        self._transactions = transactions
        self._idempotency = idempotency
        self._eligibility = eligibility
        self._clock_ms = clock_ms
        self._id_factory = id_factory

    async def join(self, *, discord_user_id: int, interaction_id: int) -> JoinResult:
        require_int64(discord_user_id, "discord_user_id", minimum=1)
        require_int64(interaction_id, "interaction_id", minimum=1)
        now_ms = self._clock_ms()
        require_int64(now_ms, "join timestamp", minimum=0)
        request = TransportRequest(
            namespace=JOIN_NAMESPACE,
            transport_key=str(interaction_id),
            actor=TransportActor(kind="discord_user", reference=str(discord_user_id)),
            semantic_input={},
        )

        async def execute(transaction: UnitOfWork) -> JoinResult:
            async def apply() -> StableOutcome:
                if not self._eligibility.evaluate().allowed:
                    return StableOutcome.typed_rejection("players.join_disabled")
                player, created = await transaction.players.create_if_absent(
                    player_id=self._id_factory(),
                    discord_user_id=discord_user_id,
                    created_at_ms=now_ms,
                )
                if player.lifecycle_state != "active":
                    return StableOutcome.typed_rejection("players.join_inactive")
                await transaction.accounts.create_wallet_if_absent(
                    account_id=self._id_factory(),
                    player_id=player.id,
                    created_at_ms=now_ms,
                    player_was_created=created,
                )
                return StableOutcome.success(
                    "players.joined" if created else "players.already_joined"
                )

            execution = await self._idempotency.execute(
                transaction, request, completed_at_ms=now_ms, operation=apply
            )
            return _result(execution.outcome, replayed=execution.replayed)

        return await self._transactions.run(JOIN_NAMESPACE, execute)
