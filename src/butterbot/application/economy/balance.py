from dataclasses import dataclass
from typing import Literal, Protocol

from butterbot.application.economy.history import HistoryCursor, HistoryPage, validate_cursor
from butterbot.application.exact_integer import require_int64
from butterbot.application.transactions import UnitOfWorkFactory

BalanceStatus = Literal["available", "unjoined", "inactive", "unavailable"]


@dataclass(frozen=True, slots=True)
class BalanceResult:
    status: BalanceStatus
    amount: int | None = None


class BalanceUseCase(Protocol):
    async def balance(self, *, discord_user_id: int) -> BalanceResult: ...
    async def history(
        self, *, discord_user_id: int, cursor: HistoryCursor | None = None
    ) -> HistoryPage: ...


class BalanceService:
    """Self-only wallet query; no eligibility check, creation, repair, or replay writes."""

    def __init__(self, snapshots: UnitOfWorkFactory) -> None:
        self._snapshots = snapshots

    async def balance(self, *, discord_user_id: int) -> BalanceResult:
        require_int64(discord_user_id, "discord_user_id", minimum=1)
        async with self._snapshots() as snapshot:
            player = await snapshot.players.get_by_discord_user_id(discord_user_id)
            if player is None:
                return BalanceResult("unjoined")
            if player.lifecycle_state != "active":
                return BalanceResult("inactive")
            wallet = await snapshot.accounts.get_wallet(player.id)
            if wallet is None:
                return BalanceResult("unavailable")
            require_int64(wallet.amount, "wallet amount", minimum=0)
            return BalanceResult("available", wallet.amount)

    async def history(
        self, *, discord_user_id: int, cursor: HistoryCursor | None = None
    ) -> HistoryPage:
        require_int64(discord_user_id, "discord_user_id", minimum=1)
        validate_cursor(cursor)
        async with self._snapshots() as snapshot:
            player = await snapshot.players.get_by_discord_user_id(discord_user_id)
            if player is None:
                return HistoryPage("unjoined")
            if player.lifecycle_state != "active":
                return HistoryPage("inactive")
            wallet = await snapshot.accounts.get_wallet(player.id)
            if wallet is None:
                return HistoryPage("unavailable")
            entries = await snapshot.history.page(wallet.id, cursor, 6)
            visible = entries[:5]
            next_cursor = None
            if len(entries) > 5:
                last = visible[-1]
                next_cursor = HistoryCursor(last.committed_at_ms, last.transaction_id)
            return HistoryPage("available", visible, next_cursor)
