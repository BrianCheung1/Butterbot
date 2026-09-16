from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

from butterbot.application.operations.ports import (
    DatabaseStorageSnapshot,
    TransportStorageStats,
)


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, default_release: str = "bootstrap") -> None:
        super().__init__()
        self._default_release = default_release

    def format(self, record: logging.LogRecord) -> str:
        event_data_value: object = getattr(record, "event_data", None)
        event_data = (
            cast("dict[str, object]", event_data_value)
            if isinstance(event_data_value, dict)
            else None
        )
        data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "event": record.name if not isinstance(event_data, dict) else event_data.get("event"),
            "severity": record.levelname.lower(),
            "message": record.getMessage(),
            "release": self._default_release,
            "mutation_enabled": None,
        }
        if isinstance(event_data, dict):
            data.update(event_data)
        if record.exc_info is not None:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, separators=(",", ":"), sort_keys=True)


class StructuredLoggingTelemetry:
    def __init__(self, *, release: str) -> None:
        self._release = release
        self._mutation_enabled = False
        self._logger = logging.getLogger("butterbot.telemetry")

    def transport_idempotency(self, *, namespace: str, outcome: str) -> None:
        self._emit(
            logging.INFO,
            "operations.transport_idempotency",
            namespace=namespace,
            outcome=outcome,
        )

    def discord_command_completed(self, *, command: str, outcome: str, duration_ms: float) -> None:
        self._emit(
            logging.INFO if outcome == "completed" else logging.ERROR,
            "discord.command.completed",
            command=command,
            outcome=outcome,
            duration_ms=round(duration_ms, 3),
        )

    def transport_storage(
        self,
        *,
        stats: TransportStorageStats,
        deleted: int,
        duration_ms: float,
        outcome: str,
    ) -> None:
        self._emit(
            logging.INFO,
            "operations.transport_idempotency_storage",
            live_rows=stats.live_count,
            expired_rows=stats.expired_count,
            oldest_retain_until_ms=stats.oldest_retain_until_ms,
            cleanup_deleted=deleted,
            duration_ms=round(duration_ms, 3),
            outcome=outcome,
        )

    def database_busy_retry(
        self,
        *,
        operation: str,
        attempt: int,
        wait_ms: int,
        elapsed_ms: float,
    ) -> None:
        self._emit(
            logging.WARNING,
            "database.busy_retry",
            operation=operation,
            attempt=attempt,
            wait_ms=wait_ms,
            elapsed_ms=round(elapsed_ms, 3),
        )

    def database_busy_exhausted(
        self,
        *,
        operation: str,
        attempts: int,
        elapsed_ms: float,
    ) -> None:
        self._emit(
            logging.CRITICAL,
            "database.busy_exhausted",
            operation=operation,
            attempts=attempts,
            elapsed_ms=round(elapsed_ms, 3),
        )

    def database_storage(
        self,
        *,
        snapshot: DatabaseStorageSnapshot,
        outcome: str,
        error_category: str | None,
    ) -> None:
        level = logging.INFO if outcome == "healthy" else logging.CRITICAL
        self._emit(
            level,
            "database.storage",
            main_bytes=snapshot.main_bytes,
            wal_bytes=snapshot.wal_bytes,
            shm_bytes=snapshot.shm_bytes,
            free_bytes=snapshot.free_bytes,
            free_percent=round(snapshot.free_percent, 3),
            checkpoint_busy=snapshot.checkpoint_busy,
            checkpoint_log_frames=snapshot.checkpoint_log_frames,
            checkpointed_frames=snapshot.checkpointed_frames,
            daily_growth_bytes=snapshot.daily_growth_bytes,
            outcome=outcome,
            error_category=error_category,
        )

    def schema_readiness(
        self,
        *,
        outcome: str,
        expected_revision: str,
        observed_revision: str | None,
        mutation_enabled: bool,
        error_category: str | None = None,
        quick_check: str | None = None,
        foreign_keys: int | None = None,
        journal_mode: str | None = None,
        synchronous: int | None = None,
        busy_timeout_ms: int | None = None,
        foreign_key_violations: int | None = None,
    ) -> None:
        level = logging.INFO if outcome == "ready" else logging.CRITICAL
        self._emit(
            level,
            "database.schema_readiness",
            outcome=outcome,
            expected_revision=expected_revision,
            observed_revision=observed_revision,
            mutation_enabled=mutation_enabled,
            error_category=error_category,
            database_path_alias="configured_database",
            quick_check=quick_check,
            foreign_keys=foreign_keys,
            journal_mode=journal_mode,
            synchronous=synchronous,
            busy_timeout_ms=busy_timeout_ms,
            foreign_key_violations=foreign_key_violations,
        )

    def mutations_state(self, *, enabled: bool, reason: str) -> None:
        self._mutation_enabled = enabled
        self._emit(
            logging.INFO,
            "economy.mutations_state",
            enabled=enabled,
            reason=reason,
        )

    def _emit(self, level: int, event: str, **fields: object) -> None:
        self._logger.log(
            level,
            event,
            extra={
                "event_data": {
                    "event": event,
                    "release": self._release,
                    "mutation_enabled": self._mutation_enabled,
                    **fields,
                }
            },
        )
