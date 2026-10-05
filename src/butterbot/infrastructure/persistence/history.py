from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.application.economy.history import HistoryCursor, HistoryEntry
from butterbot.infrastructure.persistence.models import (
    CorrectionModel,
    GrantExecutionModel,
    GrantTargetModel,
    LedgerPostingModel,
    LedgerTransactionModel,
)


class SqlAlchemyHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(
        self, account_id: UUID, cursor: HistoryCursor | None, limit: int
    ) -> tuple[HistoryEntry, ...]:
        ledger, posting = LedgerTransactionModel, LedgerPostingModel
        query = (
            select(
                ledger.id,
                ledger.committed_at_ms,
                ledger.transaction_kind,
                posting.amount,
                GrantTargetModel.after_amount,
                CorrectionModel.after_amount,
            )
            .join(posting, posting.transaction_id == ledger.id)
            .outerjoin(GrantExecutionModel, GrantExecutionModel.transaction_id == ledger.id)
            .outerjoin(
                GrantTargetModel,
                and_(
                    GrantTargetModel.proposal_id == GrantExecutionModel.proposal_id,
                    GrantTargetModel.account_id == posting.account_id,
                ),
            )
            .outerjoin(
                CorrectionModel,
                and_(
                    CorrectionModel.transaction_id == ledger.id,
                    CorrectionModel.account_id == posting.account_id,
                ),
            )
            .where(posting.account_id == account_id)
        )
        if cursor is not None:
            query = query.where(
                or_(
                    ledger.committed_at_ms < cursor.committed_at_ms,
                    and_(
                        ledger.committed_at_ms == cursor.committed_at_ms,
                        ledger.id < cursor.transaction_id,
                    ),
                )
            )
        rows = await self._session.execute(
            query.order_by(ledger.committed_at_ms.desc(), ledger.id.desc()).limit(limit)
        )
        # Only fixed public labels; never operator IDs, free-text reasons, or system accounts.
        labels = {"admin.grant": "Grant", "admin.correction": "Grant correction"}
        return tuple(
            HistoryEntry(
                row[0],
                row[1],
                labels.get(row[2], "Wallet adjustment"),
                row[3],
                row[5] if row[5] is not None else row[4],
            )
            for row in rows
        )
