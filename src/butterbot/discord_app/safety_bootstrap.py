"""One-time, stopped-service bootstrap for explicitly approved disposable local operators."""

import argparse
import asyncio
from pathlib import Path
from time import time_ns
from uuid import uuid4

from butterbot.application.operations.idempotency import (
    NullOperationsTelemetry,
    TransportIdempotencyCoordinator,
    discord_retention_registry,
)
from butterbot.application.safety.service import SAFETY_NAMESPACES, SafetyPolicy, SafetyService
from butterbot.application.transactions import ApplicationTransactionRunner
from butterbot.discord_app.development import REPOSITORY_ROOT
from butterbot.discord_app.startup import configure_logging
from butterbot.infrastructure.persistence.database import create_database_runtime, is_sqlite_busy
from butterbot.infrastructure.safety_alerts import local_safety_alert


def _validate_local_path(database_path: Path) -> None:
    parent = REPOSITORY_ROOT / "data" / "discord-development"
    if (
        database_path != database_path.resolve()
        or parent != parent.resolve()
        or not database_path.is_relative_to(parent)
    ):
        raise ValueError("local bootstrap only accepts canonical disposable development storage")


async def bootstrap_local(
    database_path: Path, operators: tuple[int, ...], policy: SafetyPolicy
) -> bool:
    await asyncio.to_thread(_validate_local_path, database_path)
    runtime = await create_database_runtime(database_path)
    try:
        telemetry = NullOperationsTelemetry()
        service = SafetyService(
            ApplicationTransactionRunner(
                runtime.unit_of_work_factory, is_retryable=is_sqlite_busy, telemetry=telemetry
            ),
            TransportIdempotencyCoordinator(
                discord_retention_registry(*SAFETY_NAMESPACES), telemetry=telemetry
            ),
            policy=policy,
            clock_ms=lambda: time_ns() // 1_000_000,
            id_factory=uuid4,
            alert=local_safety_alert,
            runtime_safety=runtime.storage_monitor,
        )
        return await service.bootstrap(operators)
    finally:
        await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--operator", type=int, action="append", required=True)
    parser.add_argument("--approval-threshold", type=int, required=True)
    parser.add_argument("--operation-ceiling", type=int, required=True)
    parser.add_argument("--rolling-ceiling", type=int, required=True)
    parser.add_argument("--alert-destination", choices=["local_log"], required=True)
    args = parser.parse_args()
    configure_logging(release="local-safety-bootstrap")
    applied = asyncio.run(
        bootstrap_local(
            args.database,
            tuple(args.operator),
            SafetyPolicy(args.approval_threshold, args.operation_ceiling, args.rolling_ceiling),
        )
    )
    print(
        "Bootstrap applied." if applied else "Bootstrap already consumed; no capabilities changed."
    )


if __name__ == "__main__":
    main()
