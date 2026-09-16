from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.application.economy.ports import WalletRecord
from butterbot.application.exact_integer import require_int64
from butterbot.application.operations.outcome_codec import (
    InvalidStableOutcome,
    canonicalize_stable_outcome,
    decode_canonical_stable_outcome,
)
from butterbot.application.operations.ports import (
    StableOutcome,
    TransportActor,
    TransportClaim,
    TransportStorageStats,
)
from butterbot.application.players.ports import PlayerRecord
from butterbot.infrastructure.persistence.models import (
    AccountBalanceModel,
    AccountModel,
    PlayerModel,
    TransportRequestModel,
)


class IncompleteTransportRequest(RuntimeError):
    """A supposedly committed transport row has no outcome."""


class CorruptTransportOutcome(RuntimeError):
    """A stored transport outcome violates the accepted persistence contract."""


class PersistenceInvariantError(RuntimeError):
    """Persisted aggregate state is incomplete or internally inconsistent."""


@dataclass(slots=True)
class AggregateCompletenessTracker:
    created_players: set[UUID] = field(default_factory=lambda: set[UUID]())
    completed_players: set[UUID] = field(default_factory=lambda: set[UUID]())
    created_accounts: set[UUID] = field(default_factory=lambda: set[UUID]())
    projected_accounts: set[UUID] = field(default_factory=lambda: set[UUID]())

    def assert_complete(self) -> None:
        if self.created_accounts - self.projected_accounts:
            raise PersistenceInvariantError(
                "an economy account is missing its required balance projection"
            )
        if self.created_players - self.completed_players:
            raise PersistenceInvariantError("a player is missing its required wallet")


class SqlAlchemyPlayerRepository:
    def __init__(self, session: AsyncSession, aggregates: AggregateCompletenessTracker) -> None:
        self._session = session
        self._aggregates = aggregates

    async def get_by_discord_user_id(self, discord_user_id: int) -> PlayerRecord | None:
        require_int64(discord_user_id, "discord_user_id", minimum=0)
        model = await self._session.scalar(
            select(PlayerModel).where(PlayerModel.discord_user_id == discord_user_id)
        )
        return None if model is None else _player_record(model)

    async def create_if_absent(
        self,
        *,
        player_id: UUID,
        discord_user_id: int,
        created_at_ms: int,
    ) -> tuple[PlayerRecord, bool]:
        require_int64(discord_user_id, "discord_user_id", minimum=0)
        require_int64(created_at_ms, "created_at_ms", minimum=0)
        # The owning SQLite unit of work holds BEGIN IMMEDIATE before this read.
        # Conflicting inserts are forbidden, including INSERT ... DO NOTHING.
        existing = await self.get_by_discord_user_id(discord_user_id)
        if existing is not None:
            return existing, False
        result = cast(
            "CursorResult[tuple[object, ...]]",
            await self._session.execute(
                sqlite_insert(PlayerModel).values(
                    id=player_id,
                    discord_user_id=discord_user_id,
                    created_at_ms=created_at_ms,
                    lifecycle_state="active",
                )
            ),
        )
        model = await self._session.scalar(
            select(PlayerModel).where(PlayerModel.discord_user_id == discord_user_id)
        )
        if model is None:
            raise RuntimeError("player insert did not produce a readable row")
        created = result.rowcount == 1
        if created:
            self._aggregates.created_players.add(model.id)
        return _player_record(model), created


class SqlAlchemyAccountRepository:
    def __init__(self, session: AsyncSession, aggregates: AggregateCompletenessTracker) -> None:
        self._session = session
        self._aggregates = aggregates

    async def get_wallet(self, player_id: UUID) -> WalletRecord | None:
        account = await self._session.scalar(
            select(AccountModel).where(
                AccountModel.player_id == player_id,
                AccountModel.account_kind == "wallet",
            )
        )
        if account is None:
            return None
        balance = await self._session.get(AccountBalanceModel, account.id)
        if balance is None:
            raise PersistenceInvariantError(
                "existing wallet account is missing its required balance projection"
            )
        if account.player_id is None:
            raise PersistenceInvariantError("wallet account is missing its required player")
        return WalletRecord(account.id, account.player_id, balance.amount, balance.version)

    async def create_wallet_if_absent(
        self,
        *,
        account_id: UUID,
        player_id: UUID,
        created_at_ms: int,
        player_was_created: bool,
    ) -> tuple[WalletRecord, bool]:
        require_int64(created_at_ms, "created_at_ms", minimum=0)
        player_created_in_this_unit = player_id in self._aggregates.created_players
        if player_was_created != player_created_in_this_unit:
            raise PersistenceInvariantError(
                "wallet creation state does not match player creation in this unit of work"
            )
        if not player_was_created:
            wallet = await self.get_wallet(player_id)
            if wallet is None:
                raise PersistenceInvariantError(
                    "existing player is missing its required wallet account"
                )
            return wallet, False

        # As above, writer ownership spans this lookup and the insert below.
        existing_wallet = await self.get_wallet(player_id)
        if existing_wallet is not None:
            self._aggregates.completed_players.add(player_id)
            return existing_wallet, False

        result = cast(
            "CursorResult[tuple[object, ...]]",
            await self._session.execute(
                sqlite_insert(AccountModel).values(
                    id=account_id,
                    player_id=player_id,
                    account_kind="wallet",
                    currency_key="coin",
                    system_key=None,
                    created_at_ms=created_at_ms,
                )
            ),
        )
        account = await self._session.scalar(
            select(AccountModel).where(
                AccountModel.player_id == player_id,
                AccountModel.account_kind == "wallet",
            )
        )
        if account is None:
            raise RuntimeError("wallet insert did not produce a readable row")
        if result.rowcount == 1:
            self._aggregates.created_accounts.add(account.id)
            await self._session.execute(
                sqlite_insert(AccountBalanceModel).values(
                    account_id=account.id,
                    account_kind="wallet",
                    amount=0,
                    version=0,
                )
            )
            self._aggregates.projected_accounts.add(account.id)
        wallet = await self.get_wallet(player_id)
        if wallet is None:
            raise PersistenceInvariantError(
                "newly created player is missing its required wallet account"
            )
        self._aggregates.completed_players.add(player_id)
        return wallet, result.rowcount == 1


class SqlAlchemyTransportIdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pending_request_ids: set[UUID] = set()

    async def claim(
        self,
        *,
        request_id: UUID,
        namespace: str,
        transport_key: str,
        actor: TransportActor,
        request_fingerprint: str,
    ) -> TransportClaim:
        result = cast(
            "CursorResult[tuple[object, ...]]",
            await self._session.execute(
                sqlite_insert(TransportRequestModel)
                .values(
                    id=request_id,
                    namespace=namespace,
                    transport_key=transport_key,
                    actor_kind=actor.kind,
                    actor_reference=actor.reference,
                    request_fingerprint=request_fingerprint,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        TransportRequestModel.namespace,
                        TransportRequestModel.transport_key,
                    ]
                )
            ),
        )
        if result.rowcount == 1:
            self._pending_request_ids.add(request_id)
            return TransportClaim(request_id, True, request_fingerprint, None)

        model = await self._session.scalar(
            select(TransportRequestModel).where(
                TransportRequestModel.namespace == namespace,
                TransportRequestModel.transport_key == transport_key,
            )
        )
        if model is None:
            raise RuntimeError("transport request conflict did not produce a readable row")
        outcome = _stored_outcome(model)
        return TransportClaim(model.id, False, model.request_fingerprint, outcome)

    async def complete(
        self,
        *,
        request_id: UUID,
        outcome: StableOutcome,
        completed_at_ms: int,
        retain_until_ms: int,
    ) -> None:
        require_int64(completed_at_ms, "completed_at_ms", minimum=0)
        require_int64(retain_until_ms, "retain_until_ms", minimum=0)
        if retain_until_ms <= completed_at_ms:
            raise ValueError("retain_until_ms must be later than completed_at_ms")
        outcome, payload = canonicalize_stable_outcome(outcome)
        result = cast(
            "CursorResult[tuple[object, ...]]",
            await self._session.execute(
                update(TransportRequestModel)
                .where(
                    TransportRequestModel.id == request_id,
                    TransportRequestModel.outcome_kind.is_(None),
                )
                .values(
                    outcome_kind=outcome.kind,
                    outcome_code=outcome.code,
                    outcome_payload=payload,
                    completed_at_ms=completed_at_ms,
                    retain_until_ms=retain_until_ms,
                )
            ),
        )
        if result.rowcount != 1:
            raise RuntimeError("transport request was not completed exactly once")
        self._pending_request_ids.discard(request_id)

    async def delete_expired(self, *, now_ms: int, limit: int) -> int:
        require_int64(now_ms, "now_ms", minimum=0)
        require_int64(limit, "cleanup limit", minimum=1)
        expired_ids = (
            select(TransportRequestModel.id)
            .where(
                TransportRequestModel.retain_until_ms.is_not(None),
                TransportRequestModel.retain_until_ms <= now_ms,
            )
            .order_by(TransportRequestModel.retain_until_ms, TransportRequestModel.id)
            .limit(limit)
        )
        result = cast(
            "CursorResult[tuple[object, ...]]",
            await self._session.execute(
                delete(TransportRequestModel).where(TransportRequestModel.id.in_(expired_ids))
            ),
        )
        return result.rowcount

    async def storage_stats(self, *, now_ms: int) -> TransportStorageStats:
        require_int64(now_ms, "now_ms", minimum=0)
        live_count = await self._session.scalar(
            select(func.count())
            .select_from(TransportRequestModel)
            .where(TransportRequestModel.retain_until_ms > now_ms)
        )
        expired_count = await self._session.scalar(
            select(func.count())
            .select_from(TransportRequestModel)
            .where(TransportRequestModel.retain_until_ms <= now_ms)
        )
        oldest = await self._session.scalar(
            select(func.min(TransportRequestModel.retain_until_ms)).where(
                TransportRequestModel.retain_until_ms.is_not(None)
            )
        )
        return TransportStorageStats(int(live_count or 0), int(expired_count or 0), oldest)

    def assert_no_pending_requests(self) -> None:
        if self._pending_request_ids:
            raise IncompleteTransportRequest(
                "unit of work cannot commit a transport request without an outcome"
            )


def _player_record(model: PlayerModel) -> PlayerRecord:
    return PlayerRecord(
        id=model.id,
        discord_user_id=model.discord_user_id,
        created_at_ms=model.created_at_ms,
        lifecycle_state=model.lifecycle_state,
    )


def _stored_outcome(model: TransportRequestModel) -> StableOutcome:
    if (
        model.outcome_kind is None
        or model.outcome_code is None
        or model.outcome_payload is None
        or model.completed_at_ms is None
        or model.retain_until_ms is None
    ):
        raise IncompleteTransportRequest("committed transport request has no completed outcome")
    try:
        return decode_canonical_stable_outcome(
            kind=model.outcome_kind,
            code=model.outcome_code,
            payload_text=model.outcome_payload,
        )
    except InvalidStableOutcome as error:
        raise CorruptTransportOutcome(
            "stored transport outcome violates the canonical JSON contract"
        ) from error
