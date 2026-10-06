from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from butterbot.application.economy.daily_ports import DailyClaim
from butterbot.application.exact_integer import checked_add_int64, require_int64
from butterbot.application.operations.idempotency import (
    FingerprintConflict,
    TransportIdempotencyCoordinator,
    TransportRequest,
)
from butterbot.application.operations.mutation_eligibility import MutationEligibility
from butterbot.application.operations.ports import StableOutcome, TransportActor
from butterbot.application.transactions import (
    ApplicationTransactionRunner,
    UnitOfWork,
    UnitOfWorkFactory,
)

DAILY_NAMESPACE = "economy.daily"
DAY_MS = 86_400_000
DAILY_COINS = 15


@dataclass(frozen=True, slots=True)
class DailyResult:
    status: str
    period: int
    balance: int | None = None
    transaction_id: UUID | None = None
    replayed: bool = False


class DailyUseCase(Protocol):
    async def inspect(self, *, discord_user_id: int) -> DailyResult: ...
    async def claim(
        self, *, discord_user_id: int, interaction_id: int, claim_period: int
    ) -> DailyResult: ...


class DailyService:
    def __init__(
        self,
        transactions: ApplicationTransactionRunner,
        snapshots: UnitOfWorkFactory,
        idempotency: TransportIdempotencyCoordinator,
        eligibility: MutationEligibility,
        *,
        clock_ms: Callable[[], int],
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._transactions = transactions
        self._snapshots = snapshots
        self._idempotency = idempotency
        self._eligibility = eligibility
        self._clock_ms = clock_ms
        self._id_factory = id_factory

    async def inspect(self, *, discord_user_id: int) -> DailyResult:
        require_int64(discord_user_id, "discord user", minimum=1)
        async with self._snapshots() as tx:
            period = require_int64(self._clock_ms(), "timestamp", minimum=0) // DAY_MS
            player = await tx.players.get_by_discord_user_id(discord_user_id)
            if player is None:
                return DailyResult("unjoined", period)
            if player.lifecycle_state != "active":
                return DailyResult("inactive", period)
            wallet = await tx.accounts.get_wallet(player.id)
            if wallet is None:
                return DailyResult("unavailable", period)
            if await tx.daily.find(player.id, period) is not None:
                return DailyResult("already_claimed", period)
            if not self._eligibility.evaluate().allowed or await tx.safety.is_frozen(
                discord_user_id
            ):
                return DailyResult("disabled", period)
            return DailyResult("available", period)

    async def claim(
        self, *, discord_user_id: int, interaction_id: int, claim_period: int
    ) -> DailyResult:
        require_int64(discord_user_id, "discord user", minimum=1)
        require_int64(interaction_id, "interaction", minimum=1)
        require_int64(claim_period, "claim period", minimum=0)
        request = TransportRequest(
            DAILY_NAMESPACE,
            str(interaction_id),
            TransportActor("discord_user", str(discord_user_id)),
            {"claim_period": claim_period},
        )

        async def execute(tx: UnitOfWork) -> DailyResult:
            # Sample only after writer admission, including retries across midnight.
            now = require_int64(self._clock_ms(), "timestamp", minimum=0)
            existing = await tx.daily.request(interaction_id)
            if existing is not None:
                if existing.actor_id != discord_user_id or existing.claim_period != claim_period:
                    raise FingerprintConflict("daily request identity changed")
                return DailyResult(
                    "claimed",
                    existing.claim_period,
                    existing.after_amount,
                    existing.transaction_id,
                    True,
                )

            async def apply() -> StableOutcome:
                def reject(status: str) -> StableOutcome:
                    return StableOutcome.typed_rejection("daily." + status)

                if claim_period != now // DAY_MS:
                    return reject("expired")
                if not self._eligibility.evaluate().allowed or await tx.safety.is_frozen(
                    discord_user_id
                ):
                    return reject("disabled")
                player = await tx.players.get_by_discord_user_id(discord_user_id)
                if player is None:
                    return reject("unjoined")
                if player.lifecycle_state != "active":
                    return reject("inactive")
                wallet = await tx.accounts.get_wallet(player.id)
                if wallet is None:
                    return reject("unavailable")
                if await tx.daily.find(player.id, claim_period) is not None:
                    return reject("already_claimed")
                after = checked_add_int64(wallet.amount, DAILY_COINS, "daily wallet")
                claim = DailyClaim(
                    self._id_factory(),
                    player.id,
                    wallet.id,
                    discord_user_id,
                    interaction_id,
                    claim_period,
                    now,
                    wallet.amount,
                    after,
                )
                await tx.daily.issue(claim, wallet)
                return StableOutcome.success(
                    "daily.claimed", {"balance": after, "transaction_id": str(claim.transaction_id)}
                )

            execution = await self._idempotency.execute(
                tx, request, completed_at_ms=now, operation=apply
            )
            outcome = execution.outcome
            if outcome.kind == "success" and outcome.code == "daily.claimed":
                payload = dict(outcome.payload)
                if (
                    set(payload) != {"balance", "transaction_id"}
                    or type(payload["balance"]) is not int
                    or not isinstance(payload["transaction_id"], str)
                ):
                    raise RuntimeError("invalid daily outcome")
                return DailyResult(
                    "claimed",
                    claim_period,
                    require_int64(payload["balance"], "daily balance", minimum=DAILY_COINS),
                    UUID(payload["transaction_id"]),
                    execution.replayed,
                )
            statuses = {
                "expired",
                "disabled",
                "unjoined",
                "inactive",
                "unavailable",
                "already_claimed",
            }
            status = outcome.code.removeprefix("daily.")
            if (
                outcome.kind != "typed_rejection"
                or outcome.code != "daily." + status
                or status not in statuses
                or dict(outcome.payload)
            ):
                raise RuntimeError("invalid daily outcome")
            return DailyResult(status, claim_period, replayed=execution.replayed)

        return await self._transactions.run(DAILY_NAMESPACE, execute)
