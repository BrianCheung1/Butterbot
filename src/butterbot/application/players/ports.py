from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    id: UUID
    discord_user_id: int
    created_at_ms: int
    lifecycle_state: str


class PlayerRepository(Protocol):
    async def get_by_discord_user_id(self, discord_user_id: int) -> PlayerRecord | None: ...

    async def create_if_absent(
        self,
        *,
        player_id: UUID,
        discord_user_id: int,
        created_at_ms: int,
    ) -> tuple[PlayerRecord, bool]: ...
