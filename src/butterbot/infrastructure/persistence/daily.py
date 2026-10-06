from dataclasses import asdict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.application.economy.daily_ports import DailyClaim
from butterbot.application.economy.ports import WalletRecord
from butterbot.application.exact_integer import checked_add_int64
from butterbot.infrastructure.persistence.grants import SqlAlchemyGrantRepository
from butterbot.infrastructure.persistence.models import (
    AccountBalanceModel,
    AccountModel,
    DailyClaimModel,
    LedgerPostingModel,
    LedgerTransactionModel,
    TransportRequestModel,
)
from butterbot.infrastructure.persistence.repositories import AggregateCompletenessTracker


class SqlAlchemyDailyRepository:
    def __init__(self, session: AsyncSession, aggregates: AggregateCompletenessTracker) -> None:
        self._session = session
        self._aggregates = aggregates

    @staticmethod
    def _claim(row: DailyClaimModel | None) -> DailyClaim | None:
        if row is None:
            return None
        return DailyClaim(
            row.transaction_id,
            row.player_id,
            row.account_id,
            row.actor_id,
            row.interaction_id,
            row.claim_period,
            row.executed_at_ms,
            row.before_amount,
            row.after_amount,
        )

    async def find(self, player_id: UUID, period: int) -> DailyClaim | None:
        return self._claim(
            await self._session.scalar(
                select(DailyClaimModel).where(
                    DailyClaimModel.player_id == player_id, DailyClaimModel.claim_period == period
                )
            )
        )

    async def request(self, interaction_id: int) -> DailyClaim | None:
        return self._claim(
            await self._session.scalar(
                select(DailyClaimModel).where(DailyClaimModel.interaction_id == interaction_id)
            )
        )

    async def issue(self, claim: DailyClaim, wallet: WalletRecord) -> None:
        c = claim
        interaction_id = c.interaction_id
        account = await self._session.scalar(
            select(AccountModel).where(AccountModel.system_key == "issuance.daily")
        )
        if account is None:
            account = AccountModel(
                id=uuid4(),
                player_id=None,
                account_kind="issuance",
                currency_key="coin",
                system_key="issuance.daily",
                created_at_ms=c.executed_at_ms,
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
            raise RuntimeError("invalid daily issuance account")
        balance = await self._session.get(AccountBalanceModel, account.id)
        if balance is None or balance.account_kind != "issuance":
            raise RuntimeError("missing daily issuance projection")
        after = checked_add_int64(balance.amount, -15, "issuance amount")
        version = checked_add_int64(balance.version, 1, "issuance version")
        request = await self._session.scalar(
            select(TransportRequestModel.id).where(
                TransportRequestModel.namespace == "economy.daily",
                TransportRequestModel.transport_key == str(interaction_id),
            )
        )
        if request is None:
            raise RuntimeError("daily has no transport request")
        self._session.add(
            LedgerTransactionModel(
                id=c.transaction_id,
                transaction_kind="daily.claim",
                committed_at_ms=c.executed_at_ms,
                actor_kind="discord_user",
                actor_reference=str(c.actor_id),
                reason_code="issuance.daily",
                correlation_id=c.transaction_id,
                transport_request_id=request,
                domain_reference=f"{c.player_id.hex}:{c.claim_period}",
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
                    transaction_id=c.transaction_id, account_id=wallet.id, amount=15
                ),
                LedgerPostingModel(
                    transaction_id=c.transaction_id, account_id=account.id, amount=-15
                ),
            ]
        )
        await self._session.flush()
        self._session.add(DailyClaimModel(**asdict(c)))
        await self._session.flush()
