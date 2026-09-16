from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class TransportActor:
    kind: str
    reference: str


@dataclass(frozen=True, slots=True)
class StableOutcome:
    kind: str
    code: str
    payload: Mapping[str, JsonValue]

    @classmethod
    def success(cls, code: str, payload: Mapping[str, JsonValue] | None = None) -> StableOutcome:
        return cls(kind="success", code=code, payload={} if payload is None else payload)

    @classmethod
    def typed_rejection(
        cls, code: str, payload: Mapping[str, JsonValue] | None = None
    ) -> StableOutcome:
        return cls(kind="typed_rejection", code=code, payload={} if payload is None else payload)


@dataclass(frozen=True, slots=True)
class TransportClaim:
    request_id: UUID
    is_new: bool
    request_fingerprint: str
    outcome: StableOutcome | None


@dataclass(frozen=True, slots=True)
class TransportStorageStats:
    live_count: int
    expired_count: int
    oldest_retain_until_ms: int | None


@dataclass(frozen=True, slots=True)
class DatabaseStorageSnapshot:
    main_bytes: int
    wal_bytes: int
    shm_bytes: int
    free_bytes: int
    free_percent: float
    checkpoint_busy: int | None
    checkpoint_log_frames: int | None
    checkpointed_frames: int | None
    daily_growth_bytes: int | None


class TransportIdempotencyRepository(Protocol):
    async def claim(
        self,
        *,
        request_id: UUID,
        namespace: str,
        transport_key: str,
        actor: TransportActor,
        request_fingerprint: str,
    ) -> TransportClaim: ...

    async def complete(
        self,
        *,
        request_id: UUID,
        outcome: StableOutcome,
        completed_at_ms: int,
        retain_until_ms: int,
    ) -> None: ...

    async def delete_expired(self, *, now_ms: int, limit: int) -> int: ...

    async def storage_stats(self, *, now_ms: int) -> TransportStorageStats: ...


class OperationsTransaction(Protocol):
    @property
    def transport_requests(self) -> TransportIdempotencyRepository: ...

    def defer_until_commit(self, callback: Callable[[], None]) -> None: ...


class OperationsTelemetry(Protocol):
    def discord_command_completed(
        self, *, command: str, outcome: str, duration_ms: float
    ) -> None: ...

    def transport_idempotency(self, *, namespace: str, outcome: str) -> None: ...

    def transport_storage(
        self,
        *,
        stats: TransportStorageStats,
        deleted: int,
        duration_ms: float,
        outcome: str,
    ) -> None: ...

    def database_busy_retry(
        self,
        *,
        operation: str,
        attempt: int,
        wait_ms: int,
        elapsed_ms: float,
    ) -> None: ...

    def database_busy_exhausted(
        self,
        *,
        operation: str,
        attempts: int,
        elapsed_ms: float,
    ) -> None: ...

    def database_storage(
        self,
        *,
        snapshot: DatabaseStorageSnapshot,
        outcome: str,
        error_category: str | None,
    ) -> None: ...

    def mutations_state(self, *, enabled: bool, reason: str) -> None: ...
