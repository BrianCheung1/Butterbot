from __future__ import annotations

import io
import json
import logging
from typing import cast

from butterbot.application.operations.ports import (
    DatabaseStorageSnapshot,
    JsonValue,
    TransportStorageStats,
)
from butterbot.infrastructure.telemetry import JsonLogFormatter, StructuredLoggingTelemetry


def test_structured_operational_events_include_required_safe_fields() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("butterbot.telemetry")
    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagate = logger.propagate
    original_disabled = logger.disabled
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.disabled = False
    try:
        telemetry = StructuredLoggingTelemetry(release="slice-1.0-test")
        telemetry.discord_command_completed(command="ping", outcome="completed", duration_ms=1.2)
        telemetry.schema_readiness(
            outcome="ready",
            expected_revision="20260825_0001",
            observed_revision="20260825_0001",
            mutation_enabled=False,
            quick_check="ok",
            foreign_keys=1,
            journal_mode="wal",
            synchronous=2,
            busy_timeout_ms=1_000,
            foreign_key_violations=0,
        )
        telemetry.mutations_state(enabled=False, reason="globally_disabled")
        telemetry.transport_idempotency(
            namespace="operations.test_mutation",
            outcome="replay",
        )
        telemetry.transport_storage(
            stats=TransportStorageStats(2, 1, 1_000),
            deleted=1,
            duration_ms=1.25,
            outcome="completed",
        )
        telemetry.database_busy_exhausted(
            operation="operations.test_mutation",
            attempts=3,
            elapsed_ms=2_801.0,
        )
        telemetry.database_storage(
            snapshot=DatabaseStorageSnapshot(
                main_bytes=1_024,
                wal_bytes=512,
                shm_bytes=128,
                free_bytes=10_000,
                free_percent=25.0,
                checkpoint_busy=0,
                checkpoint_log_frames=2,
                checkpointed_frames=2,
                daily_growth_bytes=None,
            ),
            outcome="healthy",
            error_category=None,
        )
        telemetry.database_storage(
            snapshot=DatabaseStorageSnapshot(
                main_bytes=1_024,
                wal_bytes=512,
                shm_bytes=128,
                free_bytes=0,
                free_percent=0.0,
                checkpoint_busy=None,
                checkpoint_log_frames=None,
                checkpointed_frames=None,
                daily_growth_bytes=None,
            ),
            outcome="unsafe",
            error_category="storage_check_failed",
        )
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        logger.disabled = original_disabled

    events = [
        cast("dict[str, JsonValue]", json.loads(line)) for line in stream.getvalue().splitlines()
    ]
    assert [event["event"] for event in events] == [
        "discord.command.completed",
        "database.schema_readiness",
        "economy.mutations_state",
        "operations.transport_idempotency",
        "operations.transport_idempotency_storage",
        "database.busy_exhausted",
        "database.storage",
        "database.storage",
    ]
    assert all(event["timestamp"] for event in events)
    assert all(event["severity"] in {"info", "warning", "critical"} for event in events)
    assert all(event["release"] == "slice-1.0-test" for event in events)
    assert all(event["mutation_enabled"] is False for event in events)
    readiness = events[1]
    assert readiness["database_path_alias"] == "configured_database"
    assert readiness["quick_check"] == "ok"
    assert readiness["foreign_keys"] == 1
    assert readiness["journal_mode"] == "wal"
    assert readiness["synchronous"] == 2
    assert readiness["busy_timeout_ms"] == 1_000
    assert events[-1]["severity"] == "critical"
    assert events[-1]["error_category"] == "storage_check_failed"
    rendered = stream.getvalue()
    assert "transport_key" not in rendered
    assert "request_fingerprint" not in rendered
