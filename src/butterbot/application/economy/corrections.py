"""Bounded, once-per-grant-target compensating debits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from butterbot.application.economy.ports import WalletRecord
from butterbot.application.exact_integer import checked_add_int64

if TYPE_CHECKING:
    from butterbot.application.safety.service import SafetyPolicy, Status
    from butterbot.application.transactions import UnitOfWork


@dataclass(frozen=True, slots=True)
class Correction:
    transaction_id: UUID
    original_transaction_id: UUID
    account_id: UUID
    target_id: int
    actor_id: int
    amount: int
    before_amount: int
    after_amount: int
    executed_at_ms: int
    reason: str
    freeze_bypassed: bool


class CorrectionRepository(Protocol):
    async def original_amount(self, transaction_id: UUID, account_id: UUID) -> int | None: ...
    async def find(self, transaction_id: UUID, account_id: UUID) -> Correction | None: ...
    async def amount_since(self, actor_id: int, since_ms: int) -> int: ...
    async def debit(
        self, correction: Correction, wallet: WalletRecord, interaction_id: int
    ) -> None: ...


async def correct_grant(
    tx: UnitOfWork,
    *,
    actor_id: int,
    target_id: int,
    original_transaction_id: UUID,
    transaction_id: UUID,
    amount: int,
    reason: str,
    bypass_freeze: bool,
    interaction_id: int,
    now: int,
    policy: SafetyPolicy | None,
) -> Status:
    player = await tx.players.get_by_discord_user_id(target_id)
    if player is None or player.lifecycle_state != "active":
        return "unavailable"
    wallet = await tx.accounts.get_wallet(player.id)
    if wallet is None:
        raise RuntimeError("correction target has no wallet")
    prior = await tx.corrections.find(original_transaction_id, wallet.id)
    if prior is not None:
        # Business identity is permanent; a new transport cannot remove more coins.
        return "already_corrected"
    original = await tx.corrections.original_amount(original_transaction_id, wallet.id)
    if original is None:
        return "unavailable"
    if policy is None:
        return "unconfigured"
    # Only small single-target corrections; larger/policy-changing work is not exposed.
    if amount > min(original, policy.approval_threshold, policy.per_operation_ceiling):
        return "limit"
    if (
        await tx.corrections.amount_since(actor_id, now - 86_400_000) + amount
        > policy.rolling_24h_ceiling
    ):
        return "limit"
    frozen = await tx.safety.is_frozen(target_id)
    if bypass_freeze and not await tx.safety.has_capability(actor_id, "corrections.bypass_freeze"):
        return "denied"
    if frozen and not bypass_freeze:
        return "frozen"
    if wallet.amount < amount:
        return "insufficient_funds"
    checked_add_int64(wallet.version, 1, "wallet version")
    correction = Correction(
        transaction_id,
        original_transaction_id,
        wallet.id,
        target_id,
        actor_id,
        amount,
        wallet.amount,
        wallet.amount - amount,
        now,
        reason,
        frozen and bypass_freeze,
    )
    await tx.corrections.debit(correction, wallet, interaction_id)
    return "corrected"
