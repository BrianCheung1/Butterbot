from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID, uuid4

from butterbot.application.exact_integer import INT64_MAX, checked_add_int64, require_int64
from butterbot.application.identity import is_permanent_reference
from butterbot.application.operations.outcome_codec import canonicalize_stable_outcome
from butterbot.application.operations.ports import (
    DatabaseStorageSnapshot,
    JsonValue,
    OperationsTelemetry,
    OperationsTransaction,
    StableOutcome,
    TransportActor,
    TransportStorageStats,
)
from butterbot.application.operations.telemetry import emit_operational_telemetry

DISCORD_RETENTION_MS = 7 * 24 * 60 * 60 * 1_000
_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_STABLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class FingerprintConflict(RuntimeError):
    """A transport key was reused with different semantic input."""


class InvalidTransportRequest(ValueError):
    """A transport request does not satisfy the stable application contract."""


class UnregisteredTransportNamespace(RuntimeError):
    """A namespace has no reviewed retention period."""


class NullOperationsTelemetry:
    def discord_command_completed(self, *, command: str, outcome: str, duration_ms: float) -> None:
        del command, outcome, duration_ms

    def transport_idempotency(self, *, namespace: str, outcome: str) -> None:
        del namespace, outcome

    def transport_storage(
        self,
        *,
        stats: TransportStorageStats,
        deleted: int,
        duration_ms: float,
        outcome: str,
    ) -> None:
        del stats, deleted, duration_ms, outcome

    def database_busy_retry(
        self,
        *,
        operation: str,
        attempt: int,
        wait_ms: int,
        elapsed_ms: float,
    ) -> None:
        del operation, attempt, wait_ms, elapsed_ms

    def database_busy_exhausted(
        self,
        *,
        operation: str,
        attempts: int,
        elapsed_ms: float,
    ) -> None:
        del operation, attempts, elapsed_ms

    def database_storage(
        self,
        *,
        snapshot: DatabaseStorageSnapshot,
        outcome: str,
        error_category: str | None,
    ) -> None:
        del snapshot, outcome, error_category

    def mutations_state(self, *, enabled: bool, reason: str) -> None:
        del enabled, reason


@dataclass(frozen=True, slots=True)
class TransportRequest:
    namespace: str
    transport_key: str
    actor: TransportActor
    semantic_input: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class IdempotencyExecution:
    outcome: StableOutcome
    replayed: bool
    request_id: UUID


@dataclass(frozen=True, slots=True)
class RetentionRegistry:
    periods_ms: Mapping[str, int]

    def retain_until_ms(self, namespace: str, completed_at_ms: int) -> int:
        require_int64(completed_at_ms, "completed_at_ms", minimum=0)
        try:
            period_ms = self.periods_ms[namespace]
        except KeyError as error:
            raise UnregisteredTransportNamespace(namespace) from error
        require_int64(period_ms, "transport retention period", minimum=1)
        if period_ms < 1:
            raise ValueError("transport retention periods must be positive")
        return checked_add_int64(completed_at_ms, period_ms, "retain_until_ms")


def discord_retention_registry(*namespaces: str) -> RetentionRegistry:
    return RetentionRegistry({namespace: DISCORD_RETENTION_MS for namespace in namespaces})


def request_fingerprint(request: TransportRequest) -> str:
    _validate_request(request)
    canonical = json.dumps(
        {
            "actor": {"kind": request.actor.kind, "reference": request.actor.reference},
            "semantic_input": request.semantic_input,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_request(request: TransportRequest) -> None:
    if len(request.namespace) > 100 or not _NAMESPACE_PATTERN.fullmatch(request.namespace):
        raise InvalidTransportRequest("namespace must be a stable lowercase dotted name")
    if not 1 <= len(request.transport_key) <= 255:
        raise InvalidTransportRequest("transport key must contain 1 to 255 characters")
    if "\x00" in request.transport_key:
        raise InvalidTransportRequest("transport key must not contain NUL characters")
    if not 1 <= len(request.actor.kind) <= 32 or not _STABLE_CODE_PATTERN.fullmatch(
        request.actor.kind
    ):
        raise InvalidTransportRequest("actor kind must be a stable lowercase name")
    if not is_permanent_reference(request.actor.reference):
        raise InvalidTransportRequest(
            "actor reference must be visible ASCII without whitespace or controls, including NUL"
        )


class TransportIdempotencyCoordinator:
    def __init__(
        self,
        retention: RetentionRegistry,
        *,
        telemetry: OperationsTelemetry | None = None,
        request_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._retention = retention
        self._telemetry = telemetry or NullOperationsTelemetry()
        self._request_id_factory = request_id_factory

    async def execute(
        self,
        transaction: OperationsTransaction,
        request: TransportRequest,
        *,
        completed_at_ms: int,
        operation: Callable[[], Awaitable[StableOutcome]],
    ) -> IdempotencyExecution:
        require_int64(completed_at_ms, "completed_at_ms", minimum=0)
        repository = transaction.transport_requests
        fingerprint = request_fingerprint(request)
        request_id = self._request_id_factory()
        claim = await repository.claim(
            request_id=request_id,
            namespace=request.namespace,
            transport_key=request.transport_key,
            actor=request.actor,
            request_fingerprint=fingerprint,
        )
        if not claim.is_new:
            if claim.request_fingerprint != fingerprint:
                emit_operational_telemetry(
                    "operations.transport_idempotency",
                    lambda: self._telemetry.transport_idempotency(
                        namespace=request.namespace, outcome="fingerprint_conflict"
                    ),
                )
                raise FingerprintConflict("transport key was reused with different semantic input")
            if claim.outcome is None:
                raise RuntimeError("a committed transport request has no completed outcome")
            emit_operational_telemetry(
                "operations.transport_idempotency",
                lambda: self._telemetry.transport_idempotency(
                    namespace=request.namespace, outcome="replay"
                ),
            )
            return IdempotencyExecution(
                outcome=claim.outcome,
                replayed=True,
                request_id=claim.request_id,
            )

        outcome, _ = canonicalize_stable_outcome(await operation())
        await repository.complete(
            request_id=claim.request_id,
            outcome=outcome,
            completed_at_ms=completed_at_ms,
            retain_until_ms=self._retention.retain_until_ms(request.namespace, completed_at_ms),
        )
        committed_outcome = "applied" if outcome.kind == "success" else "typed_rejection"

        def emit_committed_outcome() -> None:
            emit_operational_telemetry(
                "operations.transport_idempotency",
                lambda: self._telemetry.transport_idempotency(
                    namespace=request.namespace,
                    outcome=committed_outcome,
                ),
            )

        transaction.defer_until_commit(emit_committed_outcome)
        return IdempotencyExecution(
            outcome=outcome,
            replayed=False,
            request_id=claim.request_id,
        )


class TransportIdempotencyMaintenance:
    def __init__(self, telemetry: OperationsTelemetry | None = None) -> None:
        self._telemetry = telemetry or NullOperationsTelemetry()

    async def cleanup(
        self,
        transaction: OperationsTransaction,
        *,
        now_ms: int,
        limit: int,
    ) -> int:
        require_int64(now_ms, "now_ms", minimum=0)
        require_int64(limit, "cleanup limit", minimum=1, maximum=INT64_MAX)
        repository = transaction.transport_requests
        if limit < 1:
            raise ValueError("cleanup limit must be positive")
        started = perf_counter()
        stats_before = await repository.storage_stats(now_ms=now_ms)
        try:
            deleted = await repository.delete_expired(now_ms=now_ms, limit=limit)
            stats = await repository.storage_stats(now_ms=now_ms)
        except BaseException:
            emit_operational_telemetry(
                "operations.transport_idempotency_storage",
                lambda: self._telemetry.transport_storage(
                    stats=stats_before,
                    deleted=0,
                    duration_ms=(perf_counter() - started) * 1_000,
                    outcome="failed",
                ),
            )
            raise
        duration_ms = (perf_counter() - started) * 1_000

        def emit_committed_cleanup() -> None:
            emit_operational_telemetry(
                "operations.transport_idempotency_storage",
                lambda: self._telemetry.transport_storage(
                    stats=stats,
                    deleted=deleted,
                    duration_ms=duration_ms,
                    outcome="completed",
                ),
            )

        transaction.defer_until_commit(emit_committed_cleanup)
        return deleted


__all__ = [
    "DISCORD_RETENTION_MS",
    "FingerprintConflict",
    "IdempotencyExecution",
    "RetentionRegistry",
    "StableOutcome",
    "TransportActor",
    "TransportIdempotencyCoordinator",
    "TransportIdempotencyMaintenance",
    "TransportRequest",
    "discord_retention_registry",
    "request_fingerprint",
]
