from dataclasses import asdict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.application.economy.corrections import Correction
from butterbot.application.economy.ports import WalletRecord
from butterbot.application.exact_integer import checked_add_int64
from butterbot.infrastructure.persistence.grants import SqlAlchemyGrantRepository
from butterbot.infrastructure.persistence.models import (
    AccountBalanceModel,
    AccountModel,
    CorrectionModel,
    GrantExecutionModel,
    GrantTargetModel,
    LedgerPostingModel,
    LedgerTransactionModel,
    TransportRequestModel,
)
from butterbot.infrastructure.persistence.repositories import AggregateCompletenessTracker


class SqlAlchemyCorrectionRepository:
    def __init__(self, session: AsyncSession, aggregates: AggregateCompletenessTracker) -> None:
        self._session = session
        self._aggregates = aggregates

    async def original_amount(self, transaction_id: UUID, account_id: UUID) -> int | None:
        return await self._session.scalar(
            select(GrantTargetModel.after_amount - GrantTargetModel.before_amount)
            .join(
                GrantExecutionModel, GrantExecutionModel.proposal_id == GrantTargetModel.proposal_id
            )
            .where(
                GrantExecutionModel.transaction_id == transaction_id,
                GrantTargetModel.account_id == account_id,
            )
        )

    async def find(self, transaction_id: UUID, account_id: UUID) -> Correction | None:
        row = await self._session.scalar(
            select(CorrectionModel).where(
                CorrectionModel.original_transaction_id == transaction_id,
                CorrectionModel.account_id == account_id,
            )
        )
        if row is None:
            return None
        return Correction(
            row.transaction_id,
            row.original_transaction_id,
            row.account_id,
            row.target_id,
            row.actor_id,
            row.amount,
            row.before_amount,
            row.after_amount,
            row.executed_at_ms,
            row.reason,
            bool(row.freeze_bypassed),
        )

    async def amount_since(self, actor_id: int, since_ms: int) -> int:
        return sum(
            await self._session.scalars(
                select(CorrectionModel.amount).where(
                    CorrectionModel.actor_id == actor_id,
                    CorrectionModel.executed_at_ms > since_ms,
                )
            )
        )

    async def debit(
        self, correction: Correction, wallet: WalletRecord, interaction_id: int
    ) -> None:
        c = correction
        account = await self._session.scalar(
            select(AccountModel).where(AccountModel.system_key == "retirement.correction")
        )
        if account is None:
            account = AccountModel(
                id=uuid4(),
                player_id=None,
                account_kind="retirement",
                currency_key="coin",
                system_key="retirement.correction",
                created_at_ms=c.executed_at_ms,
            )
            self._session.add(account)
            await self._session.flush()
            self._aggregates.created_accounts.add(account.id)
            self._session.add(
                AccountBalanceModel(
                    account_id=account.id, account_kind="retirement", amount=0, version=0
                )
            )
            await self._session.flush()
            self._aggregates.projected_accounts.add(account.id)
        if (
            account.account_kind != "retirement"
            or account.currency_key != "coin"
            or account.player_id is not None
        ):
            raise RuntimeError("invalid correction retirement account")
        balance = await self._session.get(AccountBalanceModel, account.id)
        if balance is None or balance.account_kind != "retirement":
            raise RuntimeError("missing correction retirement projection")
        after = checked_add_int64(balance.amount, c.amount, "retirement amount")
        version = checked_add_int64(balance.version, 1, "retirement version")
        request = await self._session.scalar(
            select(TransportRequestModel.id).where(
                TransportRequestModel.namespace == "safety.correct_grant",
                TransportRequestModel.transport_key == str(interaction_id),
            )
        )
        if request is None:
            raise RuntimeError("correction has no transport request")
        self._session.add(
            LedgerTransactionModel(
                id=c.transaction_id,
                transaction_kind="admin.correction",
                committed_at_ms=c.executed_at_ms,
                actor_kind="discord_user",
                actor_reference=str(c.actor_id),
                reason_code="retirement.correction",
                correlation_id=c.transaction_id,
                transport_request_id=request,
                domain_reference=f"{c.original_transaction_id}:{c.target_id}",
                discord_interaction_id=interaction_id,
                content_version=None,
            )
        )
        await self._session.flush()
        projector = SqlAlchemyGrantRepository(self._session, self._aggregates)
        await projector.project(
            wallet.id,
            wallet.amount,
            wallet.version,
            c.after_amount,
            checked_add_int64(wallet.version, 1, "wallet version"),
        )
        await projector.project(account.id, balance.amount, balance.version, after, version)
        self._session.add_all(
            [
                LedgerPostingModel(
                    transaction_id=c.transaction_id, account_id=wallet.id, amount=-c.amount
                ),
                LedgerPostingModel(
                    transaction_id=c.transaction_id, account_id=account.id, amount=c.amount
                ),
            ]
        )
        await self._session.flush()
        self._session.add(
            CorrectionModel(**{**asdict(c), "freeze_bypassed": int(c.freeze_bypassed)})
        )
        await self._session.flush()
