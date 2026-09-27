"""Grant rules; the caller owns the transaction and transport receipt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from butterbot.application.economy.ports import WalletRecord
from butterbot.application.exact_integer import checked_add_int64, require_int64

if TYPE_CHECKING:
    from butterbot.application.safety.service import SafetyPolicy, Status
    from butterbot.application.transactions import UnitOfWork

DAY_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class GrantCredit:
    target_id: int
    wallet: WalletRecord
    after: int


class GrantRepository(Protocol):
    async def executed(self, proposal_id: UUID) -> bool: ...
    async def amount_since(self, actor_id: int, since_ms: int) -> int: ...
    async def issue(
        self,
        *,
        proposal_id: UUID,
        transaction_id: UUID,
        actor_id: int,
        interaction_id: int,
        now_ms: int,
        credits: tuple[GrantCredit, ...],
    ) -> None: ...


async def execute_grant(
    tx: UnitOfWork,
    *,
    actor_id: int,
    proposal_id: UUID,
    interaction_id: int,
    transaction_id: UUID,
    now: int,
    policy: SafetyPolicy | None,
) -> Status:
    proposal = await tx.safety.get_proposal(proposal_id)
    if proposal is None or proposal.operation != "grant":
        return "unavailable"
    if proposal.actor_id != actor_id:
        return "denied"
    if not proposal.scope_verified:
        return "unverified_scope"
    # Permanent business identity survives transport retention and expired proposals.
    if await tx.grants.executed(proposal_id):
        return "already_executed"
    if proposal.status != "approved":
        return "approval_required"
    if not proposal.created_at_ms <= now < proposal.expires_at_ms:
        return "expired"
    if policy is None:
        return "unconfigured"
    total = require_int64(proposal.amount * len(proposal.targets), "grant total", minimum=1)
    if total > policy.per_operation_ceiling:
        return "limit"
    needs_approval = (
        proposal.requires_approval or len(proposal.targets) > 1 or total > policy.approval_threshold
    )
    if needs_approval and (
        proposal.approver_id is None
        or proposal.approver_id == actor_id
        or not await tx.safety.has_capability(proposal.approver_id, "proposals.approve")
    ):
        return "approval_required"
    # Executed amounts use execution time, not the earlier proposal reservation time.
    if await tx.grants.amount_since(actor_id, now - DAY_MS) + total > policy.rolling_24h_ceiling:
        return "limit"
    credits: list[GrantCredit] = []
    for target in proposal.targets:
        if await tx.safety.is_frozen(target):
            return "frozen"
        player = await tx.players.get_by_discord_user_id(target)
        if player is None or player.lifecycle_state != "active":
            return "unavailable"
        wallet = await tx.accounts.get_wallet(player.id)
        if wallet is None:
            raise RuntimeError("joined grant target has no wallet")
        credits.append(
            GrantCredit(
                target, wallet, checked_add_int64(wallet.amount, proposal.amount, "wallet amount")
            )
        )
        checked_add_int64(wallet.version, 1, "wallet version")
    await tx.grants.issue(
        proposal_id=proposal_id,
        transaction_id=transaction_id,
        actor_id=actor_id,
        interaction_id=interaction_id,
        now_ms=now,
        credits=tuple(credits),
    )
    return "executed"
