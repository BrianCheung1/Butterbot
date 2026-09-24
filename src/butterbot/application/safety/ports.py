from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

Capability = Literal[
    "capabilities.manage",
    "players.inspect",
    "restrictions.manage",
    "proposals.approve",
    "grants.propose",
]
CAPABILITIES: tuple[Capability, ...] = (
    "capabilities.manage",
    "players.inspect",
    "restrictions.manage",
    "proposals.approve",
    "grants.propose",
)
Operation = Literal["freeze", "release", "grant"]


@dataclass(frozen=True, slots=True)
class Proposal:
    id: UUID
    actor_id: int
    operation: Operation
    targets: tuple[int, ...]
    amount: int
    reason: str
    created_at_ms: int
    expires_at_ms: int
    requires_approval: bool
    status: str
    approver_id: int | None = None
    scope_verified: bool = False


class SafetyRepository(Protocol):
    async def receipt(self, receipt_id: UUID) -> tuple[int, str, str] | None: ...
    async def has_capability(self, actor_id: int, capability: Capability) -> bool: ...
    async def set_capability(
        self, actor_id: int, capability: Capability, enabled: bool
    ) -> None: ...
    async def bootstrap(self, operator_ids: tuple[int, ...], now_ms: int) -> bool: ...
    async def is_frozen(self, discord_user_id: int) -> bool: ...
    async def set_frozen(self, target_id: int, enabled: bool) -> None: ...
    async def add_proposal(self, proposal: Proposal) -> None: ...
    async def get_proposal(self, proposal_id: UUID) -> Proposal | None: ...
    async def finish_proposal(
        self, proposal_id: UUID, approver_id: int | None, status: str
    ) -> None: ...
    async def proposed_amount_since(self, actor_id: int, since_ms: int) -> int: ...
    async def audit(
        self,
        *,
        audit_id: UUID,
        actor_id: int,
        action: str,
        target_id: int | None,
        proposal_id: UUID | None,
        reason: str,
        now_ms: int,
    ) -> None: ...
