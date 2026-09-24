from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.application.safety.ports import CAPABILITIES, Capability, Operation, Proposal
from butterbot.infrastructure.persistence.models import (
    AccessAuditModel,
    CapabilityModel,
    ProposalModel,
    ProposalTargetModel,
    RestrictionModel,
    SafetyBootstrapModel,
)


class SqlAlchemySafetyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def receipt(self, receipt_id: UUID) -> tuple[int, str, str] | None:
        row = await self._session.get(AccessAuditModel, receipt_id)
        return None if row is None else (row.actor_id, row.action, row.reason)

    async def has_capability(self, actor_id: int, capability: Capability) -> bool:
        return await self._session.get(CapabilityModel, (actor_id, capability)) is not None

    async def set_capability(self, actor_id: int, capability: Capability, enabled: bool) -> None:
        existing = await self._session.get(CapabilityModel, (actor_id, capability))
        if enabled and existing is None:
            self._session.add(CapabilityModel(actor_id=actor_id, capability=capability))
        elif not enabled and existing is not None:
            await self._session.delete(existing)
        await self._session.flush()

    async def bootstrap(self, operator_ids: tuple[int, ...], now_ms: int) -> bool:
        if await self._session.get(SafetyBootstrapModel, 1) is not None:
            return False
        # Never recover authority automatically from a restarted process or an empty capability set.
        self._session.add(SafetyBootstrapModel(id=1, created_at_ms=now_ms))
        for actor_id in operator_ids:
            for capability in CAPABILITIES:
                await self.set_capability(actor_id, capability, True)
        await self._session.flush()
        return True

    async def is_frozen(self, discord_user_id: int) -> bool:
        return (
            await self._session.scalar(
                select(RestrictionModel.target_id)
                .where(RestrictionModel.target_id.in_((0, discord_user_id)))
                .limit(1)
            )
            is not None
        )

    async def set_frozen(self, target_id: int, enabled: bool) -> None:
        existing = await self._session.get(RestrictionModel, target_id)
        if enabled and existing is None:
            self._session.add(RestrictionModel(target_id=target_id))
        elif not enabled:
            await self._session.execute(
                delete(RestrictionModel).where(RestrictionModel.target_id == target_id)
            )
        await self._session.flush()

    async def add_proposal(self, proposal: Proposal) -> None:
        self._session.add(
            ProposalModel(
                id=proposal.id,
                actor_id=proposal.actor_id,
                operation=proposal.operation,
                amount=proposal.amount,
                reason=proposal.reason,
                created_at_ms=proposal.created_at_ms,
                expires_at_ms=proposal.expires_at_ms,
                requires_approval=int(proposal.requires_approval),
                status="pending",
                approver_id=None,
            )
        )
        await self._session.flush()
        for target in proposal.targets:
            self._session.add(ProposalTargetModel(proposal_id=proposal.id, target_id=target))
        await self._session.flush()

    async def get_proposal(self, proposal_id: UUID) -> Proposal | None:
        row = await self._session.get(ProposalModel, proposal_id)
        if row is None:
            return None
        targets = tuple(
            await self._session.scalars(
                select(ProposalTargetModel.target_id)
                .where(ProposalTargetModel.proposal_id == proposal_id)
                .order_by(ProposalTargetModel.target_id)
            )
        )
        return Proposal(
            row.id,
            row.actor_id,
            cast(Operation, row.operation),
            targets,
            row.amount,
            row.reason,
            row.created_at_ms,
            row.expires_at_ms,
            bool(row.requires_approval),
            row.status,
            row.approver_id,
        )

    async def finish_proposal(
        self, proposal_id: UUID, approver_id: int | None, status: str
    ) -> None:
        row = await self._session.get(ProposalModel, proposal_id)
        if row is None or row.status != "pending":
            raise RuntimeError("proposal is not pending")
        row.approver_id = approver_id
        row.status = status
        await self._session.flush()

    async def proposed_amount_since(self, actor_id: int, since_ms: int) -> int:
        rows = await self._session.execute(
            select(ProposalModel.amount)
            .join(ProposalTargetModel, ProposalTargetModel.proposal_id == ProposalModel.id)
            .where(
                ProposalModel.actor_id == actor_id,
                ProposalModel.created_at_ms >= since_ms,
                ProposalModel.operation == "grant",
            )
        )
        # Python integers avoid SQLite SUM overflow before comparing with the approved ceiling.
        return sum(row[0] for row in rows)

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
    ) -> None:
        self._session.add(
            AccessAuditModel(
                id=audit_id,
                actor_id=actor_id,
                action=action,
                target_id=target_id,
                proposal_id=proposal_id,
                reason=reason,
                created_at_ms=now_ms,
            )
        )
        await self._session.flush()
