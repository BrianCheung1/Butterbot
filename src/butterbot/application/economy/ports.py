from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WalletRecord:
    id: UUID
    player_id: UUID
    amount: int
    version: int


class AccountRepository(Protocol):
    async def get_wallet(self, player_id: UUID) -> WalletRecord | None: ...

    async def create_wallet_if_absent(
        self,
        *,
        account_id: UUID,
        player_id: UUID,
        created_at_ms: int,
        player_was_created: bool,
    ) -> tuple[WalletRecord, bool]: ...
