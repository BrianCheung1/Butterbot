from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from butterbot.application.exact_integer import checked_add_int64, require_int64
from butterbot.application.operations.idempotency import (
    FingerprintConflict,
    TransportIdempotencyCoordinator,
    TransportRequest,
    request_fingerprint,
)
from butterbot.application.operations.mutation_eligibility import RuntimeSafety
from butterbot.application.operations.ports import JsonValue, StableOutcome, TransportActor
from butterbot.application.safety.ports import CAPABILITIES, Capability, Operation, Proposal
from butterbot.application.transactions import ApplicationTransactionRunner, UnitOfWork

SAFETY_NAMESPACES = ("safety.capability", "safety.propose", "safety.approve")
DAY_MS = 86_400_000
Status = Literal[
    "applied",
    "pending",
    "approved",
    "denied",
    "unavailable",
    "expired",
    "already_finished",
    "self_approval",
    "limit",
    "frozen",
    "unconfigured",
    "unverified_scope",
]
_STATUSES = {
    "applied",
    "pending",
    "approved",
    "denied",
    "unavailable",
    "expired",
    "already_finished",
    "self_approval",
    "limit",
    "frozen",
    "unconfigured",
    "unverified_scope",
}


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    approval_threshold: int
    per_operation_ceiling: int
    rolling_24h_ceiling: int

    def __post_init__(self) -> None:
        for name in ("approval_threshold", "per_operation_ceiling", "rolling_24h_ceiling"):
            require_int64(
                getattr(self, name), name, minimum=0 if name == "approval_threshold" else 1
            )
        if not self.approval_threshold <= self.per_operation_ceiling <= self.rolling_24h_ceiling:
            raise ValueError("safety policy limits must be ordered")


@dataclass(frozen=True, slots=True)
class SafetyResult:
    status: str
    proposal_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class InspectionResult:
    status: str
    amount: int | None = None
    frozen: bool = False


@dataclass(frozen=True, slots=True)
class ProposalView:
    status: str
    proposal: Proposal | None = None


def proposal_identity(interaction_id: int) -> UUID:
    require_int64(interaction_id, "interaction_id", minimum=1)
    return uuid5(NAMESPACE_URL, f"butterbot:safety:proposal:{interaction_id}")


def _reason(reason: str) -> None:
    if not 1 <= len(reason) <= 256 or reason != reason.strip() or not reason.isprintable():
        raise ValueError(
            "reason must contain 1 to 256 printable characters without edge whitespace"
        )


def _capability(operation: Operation) -> Capability:
    return "grants.propose" if operation == "grant" else "restrictions.manage"


class SafetyService:
    def __init__(
        self,
        transactions: ApplicationTransactionRunner,
        idempotency: TransportIdempotencyCoordinator,
        *,
        policy: SafetyPolicy | None,
        clock_ms: Callable[[], int],
        id_factory: Callable[[], UUID],
        alert: Callable[[str, UUID], None],
        runtime_safety: RuntimeSafety | None = None,
    ) -> None:
        self._transactions = transactions
        self._idempotency = idempotency
        self._policy = policy
        self._clock_ms = clock_ms
        self._id_factory = id_factory
        self._alert = alert
        self._runtime_safety = runtime_safety

    def _now(self) -> int:
        now = self._clock_ms()
        require_int64(now, "safety timestamp", minimum=0)
        return now

    async def _audit(
        self,
        tx: UnitOfWork,
        actor_id: int,
        action: str,
        reason: str,
        now: int,
        *,
        target: int | None = None,
        proposal: UUID | None = None,
    ) -> None:
        audit_id = self._id_factory()
        await tx.safety.audit(
            audit_id=audit_id,
            actor_id=actor_id,
            action=action,
            target_id=target,
            proposal_id=proposal,
            reason=reason,
            now_ms=now,
        )
        tx.defer_until_commit(lambda: self._alert(action, audit_id))

    async def bootstrap(self, operator_ids: tuple[int, ...]) -> bool:
        if not 1 <= len(operator_ids) <= 10 or len(set(operator_ids)) != len(operator_ids):
            raise ValueError("bootstrap requires 1 to 10 distinct reviewed operators")
        for actor in operator_ids:
            require_int64(actor, "operator", minimum=1)
        now = self._now()

        async def execute(tx: UnitOfWork) -> bool:
            if self._runtime_safety is not None and not self._runtime_safety.is_safe():
                raise RuntimeError("runtime storage is unsafe")
            if not await tx.safety.bootstrap(operator_ids, now):
                return False
            for actor in operator_ids:
                await self._audit(
                    tx, actor, "bootstrap", "explicit operator bootstrap", now, target=actor
                )
            return True

        return await self._transactions.run("safety.bootstrap", execute)

    async def _mutate(
        self,
        *,
        actor_id: int,
        interaction_id: int,
        namespace: str,
        capability: Capability,
        semantic: dict[str, JsonValue],
        now: int,
        body: Callable[[UnitOfWork], Awaitable[Status]],
    ) -> SafetyResult:
        require_int64(actor_id, "actor_id", minimum=1)
        require_int64(interaction_id, "interaction_id", minimum=1)
        request = TransportRequest(
            namespace, str(interaction_id), TransportActor("discord_user", str(actor_id)), semantic
        )

        async def execute(tx: UnitOfWork) -> SafetyResult:
            if self._runtime_safety is not None and not self._runtime_safety.is_safe():
                return SafetyResult("unavailable")
            # Recheck authority before replay; cached success cannot restore revoked access.
            if not await tx.safety.has_capability(actor_id, capability):
                await self._audit(tx, actor_id, "denied", "missing durable capability", now)
                return SafetyResult("denied")

            async def apply() -> StableOutcome:
                receipt_id = uuid5(
                    NAMESPACE_URL, f"butterbot:safety:receipt:{namespace}:{interaction_id}"
                )
                fingerprint = request_fingerprint(request)
                receipt = await tx.safety.receipt(receipt_id)
                if receipt is not None:
                    if receipt[0] != actor_id or receipt[2] != fingerprint:
                        raise FingerprintConflict("administrative request identity changed")
                    status = receipt[1].removeprefix("receipt.")
                else:
                    status = await body(tx)
                    await tx.safety.audit(
                        audit_id=receipt_id,
                        actor_id=actor_id,
                        action=f"receipt.{status}",
                        target_id=None,
                        proposal_id=None,
                        reason=fingerprint,
                        now_ms=now,
                    )
                return (
                    StableOutcome.success(f"safety.{status}")
                    if status in {"applied", "pending", "approved"}
                    else StableOutcome.typed_rejection(f"safety.{status}")
                )

            execution = await self._idempotency.execute(
                tx, request, completed_at_ms=now, operation=apply
            )
            outcome = execution.outcome
            status = outcome.code.removeprefix("safety.")
            expected_kind = (
                "success" if status in {"applied", "pending", "approved"} else "typed_rejection"
            )
            if (
                outcome.code != f"safety.{status}"
                or status not in _STATUSES
                or outcome.kind != expected_kind
                or dict(outcome.payload) != {}
            ):
                raise RuntimeError("incompatible safety outcome")
            return SafetyResult(status)

        return await self._transactions.run(namespace, execute)

    async def change_capability(
        self,
        *,
        actor_id: int,
        target_id: int,
        capability: Capability,
        enabled: bool,
        reason: str,
        interaction_id: int,
    ) -> SafetyResult:
        require_int64(target_id, "target_id", minimum=1)
        if capability not in CAPABILITIES or type(enabled) is not bool:
            raise ValueError("invalid capability change")
        _reason(reason)
        now = self._now()

        async def apply(tx: UnitOfWork) -> Status:
            await tx.safety.set_capability(target_id, capability, enabled)
            await self._audit(
                tx,
                actor_id,
                f"capability.grant.{capability}" if enabled else f"capability.revoke.{capability}",
                reason,
                now,
                target=target_id,
            )
            return "applied"

        return await self._mutate(
            actor_id=actor_id,
            interaction_id=interaction_id,
            namespace="safety.capability",
            capability="capabilities.manage",
            semantic={
                "target": target_id,
                "capability": capability,
                "enabled": enabled,
                "reason": reason,
            },
            now=now,
            body=apply,
        )

    async def inspect(self, *, actor_id: int, target_id: int, reason: str) -> InspectionResult:
        require_int64(actor_id, "actor_id", minimum=1)
        require_int64(target_id, "target_id", minimum=1)
        _reason(reason)
        now = self._now()

        async def execute(tx: UnitOfWork) -> InspectionResult:
            if self._runtime_safety is not None and not self._runtime_safety.is_safe():
                return InspectionResult("unavailable")
            if not await tx.safety.has_capability(actor_id, "players.inspect"):
                await self._audit(tx, actor_id, "inspect.denied", reason, now, target=target_id)
                return InspectionResult("denied")
            player = await tx.players.get_by_discord_user_id(target_id)
            frozen = await tx.safety.is_frozen(target_id)
            await self._audit(tx, actor_id, "inspect", reason, now, target=target_id)
            if player is None:
                return InspectionResult("unjoined", frozen=frozen)
            if player.lifecycle_state != "active":
                return InspectionResult("inactive", frozen=frozen)
            wallet = await tx.accounts.get_wallet(player.id)
            return InspectionResult(
                "available" if wallet else "unavailable", wallet.amount if wallet else None, frozen
            )

        return await self._transactions.run("safety.inspect", execute)

    async def propose(
        self,
        *,
        actor_id: int,
        operation: Operation,
        targets: tuple[int, ...],
        amount: int,
        reason: str,
        interaction_id: int,
    ) -> SafetyResult:
        if (
            operation not in {"freeze", "release", "grant"}
            or not 1 <= len(targets) <= 25
            or len(set(targets)) != len(targets)
        ):
            raise ValueError("invalid operation or target count")
        for target in targets:
            require_int64(target, "target", minimum=1 if operation == "grant" else 0)
        if 0 in targets and targets != (0,):
            raise ValueError("global target must stand alone")
        require_int64(amount, "amount", minimum=1 if operation == "grant" else 0)
        if operation != "grant" and amount != 0:
            raise ValueError("restriction proposals have no monetary amount")
        _reason(reason)
        targets = tuple(sorted(targets))
        now = self._now()
        proposal_id = proposal_identity(interaction_id)

        async def apply(tx: UnitOfWork) -> Status:
            policy = self._policy
            if policy is None:
                return "unconfigured"
            total = amount * len(targets)
            if operation == "grant":
                if (
                    total > policy.per_operation_ceiling
                    or total + await tx.safety.proposed_amount_since(actor_id, max(0, now - DAY_MS))
                    > policy.rolling_24h_ceiling
                ):
                    return "limit"
                if any([await tx.safety.is_frozen(target) for target in targets]):
                    return "frozen"
            requires = len(targets) > 1 or targets == (0,) or total > policy.approval_threshold
            proposal = Proposal(
                proposal_id,
                actor_id,
                operation,
                targets,
                amount,
                reason,
                now,
                checked_add_int64(now, DAY_MS, "proposal expiry"),
                requires,
                "pending",
            )
            await tx.safety.add_proposal(proposal)
            await self._audit(tx, actor_id, "proposal.created", reason, now, proposal=proposal_id)
            if requires:
                return "pending"
            return await self._finish(tx, proposal, None, now)

        result = await self._mutate(
            actor_id=actor_id,
            interaction_id=interaction_id,
            namespace="safety.propose",
            capability=_capability(operation),
            semantic={
                "operation": operation,
                "targets": list(targets),
                "amount": amount,
                "reason": reason,
            },
            now=now,
            body=apply,
        )
        return SafetyResult(
            result.status,
            proposal_id if result.status in {"pending", "applied", "approved"} else None,
        )

    async def _finish(
        self, tx: UnitOfWork, proposal: Proposal, approver_id: int | None, now: int
    ) -> Status:
        if proposal.operation == "grant":
            status: Status = "approved"
        else:
            for target in proposal.targets:
                await tx.safety.set_frozen(target, proposal.operation == "freeze")
            status = "applied"
        await tx.safety.finish_proposal(proposal.id, approver_id, status)
        await self._audit(
            tx,
            approver_id or proposal.actor_id,
            f"proposal.{status}",
            proposal.reason,
            now,
            proposal=proposal.id,
        )
        return status

    async def view_proposal(self, *, actor_id: int, proposal_id: UUID) -> ProposalView:
        require_int64(actor_id, "actor_id", minimum=1)
        if type(proposal_id) is not UUID:
            raise ValueError("proposal identity must be a UUID")
        now = self._now()

        async def execute(tx: UnitOfWork) -> ProposalView:
            if self._runtime_safety is not None and not self._runtime_safety.is_safe():
                return ProposalView("unavailable")
            if not await tx.safety.has_capability(actor_id, "proposals.approve"):
                await self._audit(
                    tx,
                    actor_id,
                    "proposal.inspect.denied",
                    "missing durable capability",
                    now,
                    proposal=proposal_id,
                )
                return ProposalView("denied")
            proposal = await tx.safety.get_proposal(proposal_id)
            await self._audit(
                tx, actor_id, "proposal.inspect", "approval review", now, proposal=proposal_id
            )
            return ProposalView("available" if proposal is not None else "unavailable", proposal)

        return await self._transactions.run("safety.proposal_inspect", execute)

    async def approve(
        self, *, actor_id: int, proposal_id: UUID, interaction_id: int
    ) -> SafetyResult:
        if type(proposal_id) is not UUID:
            raise ValueError("proposal identity must be a UUID")
        now = self._now()

        async def apply(tx: UnitOfWork) -> Status:
            proposal = await tx.safety.get_proposal(proposal_id)
            if proposal is None:
                return "unavailable"
            if not proposal.scope_verified:
                return "unverified_scope"
            if proposal.actor_id == actor_id:
                return "self_approval"
            if proposal.status != "pending":
                return "already_finished"
            if now >= proposal.expires_at_ms:
                return "expired"
            if not await tx.safety.has_capability(
                proposal.actor_id, _capability(proposal.operation)
            ):
                return "denied"
            policy = self._policy
            if policy is None:
                return "unconfigured"
            if proposal.operation == "grant":
                if (
                    proposal.amount * len(proposal.targets) > policy.per_operation_ceiling
                    or await tx.safety.proposed_amount_since(
                        proposal.actor_id, max(0, now - DAY_MS)
                    )
                    > policy.rolling_24h_ceiling
                ):
                    return "limit"
                if any([await tx.safety.is_frozen(target) for target in proposal.targets]):
                    return "frozen"
            return await self._finish(tx, proposal, actor_id, now)

        return await self._mutate(
            actor_id=actor_id,
            interaction_id=interaction_id,
            namespace="safety.approve",
            capability="proposals.approve",
            semantic={"proposal": str(proposal_id)},
            now=now,
            body=apply,
        )
