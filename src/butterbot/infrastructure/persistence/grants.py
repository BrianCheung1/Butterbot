from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.application.economy.grants import GrantCredit
from butterbot.application.exact_integer import checked_add_int64, require_int64
from butterbot.infrastructure.persistence.models import (
    AccountBalanceModel,
    AccountModel,
    GrantExecutionModel,
    GrantTargetModel,
    LedgerPostingModel,
    LedgerTransactionModel,
    TransportRequestModel,
)
from butterbot.infrastructure.persistence.repositories import AggregateCompletenessTracker


class SqlAlchemyGrantRepository:
    def __init__(self, session: AsyncSession, aggregates: AggregateCompletenessTracker) -> None:
        self._session = session
        self._aggregates = aggregates

    async def executed(self, proposal_id: UUID) -> bool:
        return await self._session.get(GrantExecutionModel, proposal_id) is not None

    async def amount_since(self, actor_id: int, since_ms: int) -> int:
        # Python integer sum avoids SQLite SUM overflow. Include future rows conservatively
        # if the injected wall clock moves backwards; exact cutoff is outside the window.
        return sum(
            await self._session.scalars(
                select(GrantExecutionModel.total).where(
                    GrantExecutionModel.actor_id == actor_id,
                    GrantExecutionModel.executed_at_ms > since_ms,
                )
            )
        )

    async def issue(
        self,
        *,
        proposal_id: UUID,
        transaction_id: UUID,
        actor_id: int,
        interaction_id: int,
        now_ms: int,
        credits: tuple[GrantCredit, ...],
    ) -> None:
        total = require_int64(
            sum(c.after - c.wallet.amount for c in credits), "grant total", minimum=1
        )
        account = await self._session.scalar(
            select(AccountModel).where(AccountModel.system_key == "issuance.admin")
        )
        if account is None:
            account = AccountModel(
                id=uuid4(),
                player_id=None,
                account_kind="issuance",
                currency_key="coin",
                system_key="issuance.admin",
                created_at_ms=now_ms,
            )
            self._session.add(account)
            await self._session.flush()
            self._aggregates.created_accounts.add(account.id)
            self._session.add(
                AccountBalanceModel(
                    account_id=account.id, account_kind="issuance", amount=0, version=0
                )
            )
            await self._session.flush()
            self._aggregates.projected_accounts.add(account.id)
        if (
            account.account_kind != "issuance"
            or account.currency_key != "coin"
            or account.player_id is not None
        ):
            raise RuntimeError("invalid administrative issuance account")
        balance = await self._session.get(AccountBalanceModel, account.id)
        if balance is None or balance.account_kind != "issuance":
            raise RuntimeError("administrative issuance projection missing or invalid")
        after = checked_add_int64(balance.amount, -total, "issuance amount")
        next_version = checked_add_int64(balance.version, 1, "issuance version")
        request = await self._session.scalar(
            select(TransportRequestModel.id).where(
                TransportRequestModel.namespace == "safety.execute_grant",
                TransportRequestModel.transport_key == str(interaction_id),
            )
        )
        if request is None:
            raise RuntimeError("grant has no transport request")
        self._session.add(
            LedgerTransactionModel(
                id=transaction_id,
                transaction_kind="admin.grant",
                committed_at_ms=now_ms,
                actor_kind="discord_user",
                actor_reference=str(actor_id),
                reason_code="issuance.admin",
                correlation_id=transaction_id,
                transport_request_id=request,
                domain_reference=str(proposal_id),
                discord_interaction_id=interaction_id,
                content_version=None,
            )
        )
        await self._session.flush()
        await self._project(account.id, balance.amount, balance.version, after, next_version)
        self._session.add(
            LedgerPostingModel(transaction_id=transaction_id, account_id=account.id, amount=-total)
        )
        for credit in credits:
            wallet = credit.wallet
            await self._project(
                wallet.id,
                wallet.amount,
                wallet.version,
                credit.after,
                checked_add_int64(wallet.version, 1, "wallet version"),
            )
            self._session.add(
                LedgerPostingModel(
                    transaction_id=transaction_id,
                    account_id=wallet.id,
                    amount=credit.after - wallet.amount,
                )
            )
            self._session.add(
                GrantTargetModel(
                    proposal_id=proposal_id,
                    account_id=wallet.id,
                    target_id=credit.target_id,
                    before_amount=wallet.amount,
                    after_amount=credit.after,
                )
            )
        await self._session.flush()
        self._session.add(
            GrantExecutionModel(
                proposal_id=proposal_id,
                transaction_id=transaction_id,
                actor_id=actor_id,
                executed_at_ms=now_ms,
                total=total,
            )
        )
        await self._session.flush()

    async def _project(
        self, account_id: UUID, before: int, version: int, after: int, next_version: int
    ) -> None:
        result = cast(
            "CursorResult[tuple[object, ...]]",
            await self._session.execute(
                update(AccountBalanceModel)
                .where(
                    AccountBalanceModel.account_id == account_id,
                    AccountBalanceModel.amount == before,
                    AccountBalanceModel.version == version,
                )
                .values(amount=after, version=next_version)
                .execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount != 1:
            raise RuntimeError("grant projection changed during transaction")
