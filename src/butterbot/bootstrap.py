from __future__ import annotations

from dataclasses import dataclass
from time import time_ns
from uuid import uuid4

from butterbot.application.economy.balance import BalanceService
from butterbot.application.operations.idempotency import (
    TransportIdempotencyCoordinator,
    discord_retention_registry,
)
from butterbot.application.operations.mutation_eligibility import GlobalMutationEligibility
from butterbot.application.operations.telemetry import emit_operational_telemetry
from butterbot.application.players.join import JOIN_NAMESPACE, JoinService
from butterbot.application.transactions import ApplicationTransactionRunner
from butterbot.discord_app.config import (
    PRODUCTION_DATABASE_PATH,
    PRODUCTION_DATABASE_ROOT,
    Settings,
)
from butterbot.infrastructure.persistence.database import (
    DatabaseRuntime,
    create_database_runtime,
    is_sqlite_busy,
)
from butterbot.infrastructure.persistence.readiness import (
    EXPECTED_SCHEMA_REVISION,
    DatabaseReadinessError,
)
from butterbot.infrastructure.persistence.storage import DatabaseStorageContract
from butterbot.infrastructure.telemetry import StructuredLoggingTelemetry


@dataclass(slots=True)
class ApplicationRuntime:
    database: DatabaseRuntime
    mutation_eligibility: GlobalMutationEligibility
    transport_idempotency: TransportIdempotencyCoordinator
    transactions: ApplicationTransactionRunner
    telemetry: StructuredLoggingTelemetry
    balance_service: BalanceService
    join_service: JoinService

    async def close(self) -> None:
        await self.database.close()


async def compose_application(settings: Settings) -> ApplicationRuntime:
    telemetry = StructuredLoggingTelemetry(release=settings.release_id)
    production_storage_configured = (
        settings.database_path.as_posix() == PRODUCTION_DATABASE_PATH
        and settings.database_root.as_posix() == PRODUCTION_DATABASE_ROOT
        and settings.database_volume_id is not None
        and settings.database_administrator_uid is not None
        and settings.database_service_group_gid is not None
    )
    if settings.economy_mutations_enabled and not production_storage_configured:
        error = DatabaseReadinessError(
            "unsafe_storage",
            "mutation enablement requires the approved production path, root, and volume",
        )
        emit_operational_telemetry(
            "database.schema_readiness",
            lambda: telemetry.schema_readiness(
                outcome="failed",
                expected_revision=error.expected_revision,
                observed_revision=None,
                mutation_enabled=False,
                error_category=error.category,
            ),
        )
        raise error
    try:
        database = await create_database_runtime(
            settings.database_path,
            storage_contract=DatabaseStorageContract(
                approved_root=settings.database_root,
                required_volume_id=settings.database_volume_id,
                administrator_uid=settings.database_administrator_uid,
                service_group_gid=settings.database_service_group_gid,
            ),
            telemetry=telemetry,
            configured_mutations_enabled=settings.economy_mutations_enabled,
        )
    except DatabaseReadinessError as error:
        emit_operational_telemetry(
            "database.schema_readiness",
            lambda: telemetry.schema_readiness(
                outcome="failed",
                expected_revision=error.expected_revision,
                observed_revision=error.observed_revision,
                mutation_enabled=False,
                error_category=error.category,
            ),
        )
        raise
    emit_operational_telemetry(
        "database.schema_readiness",
        lambda: telemetry.schema_readiness(
            outcome="ready",
            expected_revision=EXPECTED_SCHEMA_REVISION,
            observed_revision=database.readiness.observed_revision,
            mutation_enabled=settings.economy_mutations_enabled,
            quick_check=database.readiness.quick_check,
            foreign_keys=database.readiness.foreign_keys,
            journal_mode=database.readiness.journal_mode,
            synchronous=database.readiness.synchronous,
            busy_timeout_ms=database.readiness.busy_timeout_ms,
            foreign_key_violations=database.readiness.foreign_key_violations,
        ),
    )
    eligibility = GlobalMutationEligibility(
        configured_enabled=settings.economy_mutations_enabled,
        database_ready=True,
        runtime_safety=database.storage_monitor,
    )
    decision = eligibility.evaluate()
    emit_operational_telemetry(
        "economy.mutations_state",
        lambda: telemetry.mutations_state(enabled=decision.allowed, reason=decision.reason),
    )
    idempotency = TransportIdempotencyCoordinator(
        discord_retention_registry(JOIN_NAMESPACE), telemetry=telemetry
    )
    transactions = ApplicationTransactionRunner(
        database.unit_of_work_factory, is_retryable=is_sqlite_busy, telemetry=telemetry
    )
    return ApplicationRuntime(
        database=database,
        mutation_eligibility=eligibility,
        transport_idempotency=idempotency,
        transactions=transactions,
        telemetry=telemetry,
        balance_service=BalanceService(database.unit_of_work_factory.read_snapshot),
        join_service=JoinService(
            transactions,
            idempotency,
            eligibility,
            clock_ms=lambda: time_ns() // 1_000_000,
            id_factory=uuid4,
        ),
    )
