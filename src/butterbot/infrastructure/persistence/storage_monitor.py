from __future__ import annotations

import asyncio
import logging
import shutil
from collections import deque
from pathlib import Path
from time import monotonic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from butterbot.application.operations.ports import (
    DatabaseStorageSnapshot,
    OperationsTelemetry,
)
from butterbot.application.operations.telemetry import emit_operational_telemetry
from butterbot.infrastructure.persistence.storage import (
    DatabaseStorageContract,
    UnsafeDatabaseStorage,
    ValidatedDatabaseStorage,
    identity_unchanged,
    validate_database_storage,
)

logger = logging.getLogger(__name__)


class DatabaseStorageMonitor:
    def __init__(
        self,
        *,
        storage: ValidatedDatabaseStorage,
        contract: DatabaseStorageContract,
        engine: AsyncEngine,
        telemetry: OperationsTelemetry,
        configured_mutations_enabled: bool = False,
        interval_seconds: float = 60.0,
    ) -> None:
        self._storage = storage
        self._contract = contract
        self._engine = engine
        self._telemetry = telemetry
        self._interval_seconds = interval_seconds
        self._configured_mutations_enabled = configured_mutations_enabled
        self._safe = True
        self._pending_safety_transitions: deque[tuple[bool, str]] = deque()
        self._baseline_time = monotonic()
        self._baseline_bytes = self._database_bytes()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def is_safe(self) -> bool:
        return self._safe

    async def sample(self) -> DatabaseStorageSnapshot:
        error_category: str | None = None
        checkpoint_busy: int | None = None
        checkpoint_log_frames: int | None = None
        checkpointed_frames: int | None = None
        try:
            current = validate_database_storage(self._storage.database_path, self._contract)
            if not identity_unchanged(self._storage):
                raise UnsafeDatabaseStorage(
                    "unsafe_path", "database file identity changed while the runtime was active"
                )
            async with self._engine.connect() as connection:
                checkpoint = (
                    await connection.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
                ).one()
            checkpoint_busy = int(checkpoint[0])
            checkpoint_log_frames = int(checkpoint[1])
            checkpointed_frames = int(checkpoint[2])
            free_bytes = current.free_bytes
            free_percent = current.free_percent
        except UnsafeDatabaseStorage as error:
            error_category = error.category
            free_bytes, free_percent = self._free_space_or_zero()
        except asyncio.CancelledError:
            raise
        except Exception:
            error_category = "storage_check_failed"
            free_bytes, free_percent = self._free_space_or_zero()

        current_bytes = self._database_bytes()
        elapsed = monotonic() - self._baseline_time
        daily_growth_bytes = (
            current_bytes - self._baseline_bytes if elapsed >= 24 * 60 * 60 else None
        )
        if daily_growth_bytes is not None:
            self._baseline_time = monotonic()
            self._baseline_bytes = current_bytes
        snapshot = DatabaseStorageSnapshot(
            main_bytes=self._file_size(self._storage.database_path),
            wal_bytes=self._file_size(Path(f"{self._storage.database_path}-wal")),
            shm_bytes=self._file_size(Path(f"{self._storage.database_path}-shm")),
            free_bytes=free_bytes,
            free_percent=free_percent,
            checkpoint_busy=checkpoint_busy,
            checkpoint_log_frames=checkpoint_log_frames,
            checkpointed_frames=checkpointed_frames,
            daily_growth_bytes=daily_growth_bytes,
        )
        self._set_safe(error_category is None)
        emit_operational_telemetry(
            "database.storage",
            lambda: self._telemetry.database_storage(
                snapshot=snapshot,
                outcome="healthy" if self._safe else "unsafe",
                error_category=error_category,
            ),
        )
        self._drain_safety_transitions()
        return snapshot

    def identity_failure(self, error_category: str) -> None:
        snapshot = self._fallback_snapshot()
        self._set_safe(False)
        emit_operational_telemetry(
            "database.storage",
            lambda: self._telemetry.database_storage(
                snapshot=snapshot,
                outcome="unsafe",
                error_category=error_category,
            ),
        )
        self._drain_safety_transitions()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            await task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                try:
                    await self.sample()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    emit_operational_telemetry(
                        "database.storage_monitor_failure",
                        lambda: logger.exception(
                            "Database storage sampling failed; monitoring will continue"
                        ),
                    )

    def _set_safe(self, safe: bool) -> None:
        if safe == self._safe:
            return
        self._safe = safe
        if safe:
            self._pending_safety_transitions.append(
                (
                    self._configured_mutations_enabled,
                    "enabled" if self._configured_mutations_enabled else "globally_disabled",
                )
            )
        else:
            self._pending_safety_transitions.append((False, "runtime_storage_unsafe"))

    def _drain_safety_transitions(self) -> None:
        while self._pending_safety_transitions:
            enabled, reason = self._pending_safety_transitions[0]
            emitted = emit_operational_telemetry(
                "economy.mutations_state",
                lambda enabled=enabled, reason=reason: self._telemetry.mutations_state(
                    enabled=enabled, reason=reason
                ),
            )
            if not emitted:
                return
            self._pending_safety_transitions.popleft()

    def _database_bytes(self) -> int:
        return sum(
            self._file_size(path)
            for path in (
                self._storage.database_path,
                Path(f"{self._storage.database_path}-wal"),
                Path(f"{self._storage.database_path}-shm"),
            )
        )

    def _fallback_snapshot(self) -> DatabaseStorageSnapshot:
        free_bytes, free_percent = self._free_space_or_zero()
        return DatabaseStorageSnapshot(
            main_bytes=self._file_size(self._storage.database_path),
            wal_bytes=self._file_size(Path(f"{self._storage.database_path}-wal")),
            shm_bytes=self._file_size(Path(f"{self._storage.database_path}-shm")),
            free_bytes=free_bytes,
            free_percent=free_percent,
            checkpoint_busy=None,
            checkpoint_log_frames=None,
            checkpointed_frames=None,
            daily_growth_bytes=None,
        )

    def _free_space_or_zero(self) -> tuple[int, float]:
        try:
            usage = shutil.disk_usage(self._storage.approved_root)
        except OSError:
            return 0, 0.0
        percent = usage.free / usage.total * 100 if usage.total else 0.0
        return usage.free, percent

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0
