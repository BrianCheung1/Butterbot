from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from butterbot.application.exact_integer import require_int64


@dataclass(frozen=True, slots=True)
class HistoryCursor:
    committed_at_ms: int
    transaction_id: UUID


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    transaction_id: UUID
    committed_at_ms: int
    kind: str
    amount: int
    resulting_balance: int | None


@dataclass(frozen=True, slots=True)
class HistoryPage:
    status: str
    entries: tuple[HistoryEntry, ...] = ()
    next_cursor: HistoryCursor | None = None


class HistoryRepository(Protocol):
    async def page(
        self, account_id: UUID, cursor: HistoryCursor | None, limit: int
    ) -> tuple[HistoryEntry, ...]: ...


def validate_cursor(cursor: HistoryCursor | None) -> None:
    if cursor is not None:
        require_int64(cursor.committed_at_ms, "cursor timestamp", minimum=0)
        if type(cursor.transaction_id) is not UUID:
            raise ValueError("cursor identity must be a UUID")
