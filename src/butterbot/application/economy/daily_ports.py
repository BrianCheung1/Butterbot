from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from butterbot.application.economy.ports import WalletRecord


@dataclass(frozen=True, slots=True)
class DailyClaim:
    transaction_id: UUID
    player_id: UUID
    account_id: UUID
    actor_id: int
    interaction_id: int
    claim_period: int
    executed_at_ms: int
    before_amount: int
    after_amount: int


class DailyRepository(Protocol):
    async def find(self, player_id: UUID, period: int) -> DailyClaim | None: ...
    async def request(self, interaction_id: int) -> DailyClaim | None: ...
    async def issue(self, claim: DailyClaim, wallet: WalletRecord) -> None: ...
