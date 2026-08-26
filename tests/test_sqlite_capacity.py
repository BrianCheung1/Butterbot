import json
from pathlib import Path

import pytest
from benchmarks.sqlite_capacity import (
    DEFAULT_MEASUREMENT_SECONDS,
    DEFAULT_REPEATS,
    DEFAULT_WARMUP_SECONDS,
    DEFAULT_WORKERS,
    EVIDENCE_FORMAT_VERSION,
    PROJECTED_PEAK_TPS,
    SCHEMA_VERSION,
    TWICE_PROJECTED_PEAK_TPS,
    RetryPolicy,
    capacity_assessment,
    implementation_sha256,
    initialize_database,
    open_connection,
    parse_concurrency,
    percentile,
    run_busy_timeout_check,
    run_duplicate_creation,
    run_guarded_contention_check,
    run_idempotency_check,
    run_offered_rate_repeat,
    run_retry_exhaustion_check,
    run_retry_recovery_check,
    run_rollback_check,
    run_saturation_level,
    run_wal_reader_check,
)

REPOSITORY_ROOT = Path(__file__).parents[1]
EVIDENCE_PATH = REPOSITORY_ROOT / "docs" / "evidence" / "sqlite-capacity-2026-08-25.json"


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([], 0.99) == 0.0


def test_parse_concurrency_rejects_non_positive_levels() -> None:
    with pytest.raises(Exception, match="must be positive"):
        parse_concurrency("1,0")


def _passing_run() -> dict[str, object]:
    return {
        "acceptance_passed": True,
        "latency_ms": {"p95": 10.0, "p99": 20.0},
        "retry_rate_percent": 0.0,
        "final_lock_failures": 0,
        "invariant_failures": [],
        "completed_within_window_tps": 34.0,
    }


def test_capacity_assessment_requires_twice_peak_and_every_repeat() -> None:
    saturation = [{"acceptance_passed": True, "completed_tps_including_drain": 400.0}]

    passed = capacity_assessment(
        [_passing_run(), _passing_run()],
        saturation,
        projected_peak_tps=17.0,
        offered_tps=34.0,
    )
    below_target = capacity_assessment(
        [_passing_run()],
        saturation,
        projected_peak_tps=17.0,
        offered_tps=33.9,
    )
    failed_run = _passing_run()
    failed_run["acceptance_passed"] = False
    one_repeat_failed = capacity_assessment(
        [_passing_run(), failed_run],
        saturation,
        projected_peak_tps=17.0,
        offered_tps=34.0,
    )

    assert passed["twice_peak_capacity_gate_passed"] is True
    assert below_target["twice_peak_capacity_gate_passed"] is False
    assert one_repeat_failed["twice_peak_capacity_gate_passed"] is False


async def test_disposable_schema_enforces_required_pragmas(tmp_path: Path) -> None:
    database = tmp_path / "pragmas.sqlite3"
    pragmas = await initialize_database(database, seed_accounts=1)

    assert pragmas == {
        "foreign_keys": 1,
        "journal_mode": "wal",
        "synchronous": 2,
        "busy_timeout_ms": 1_000,
    }

    connection = await open_connection(database, RetryPolicy())
    try:
        with pytest.raises(Exception, match="FOREIGN KEY constraint failed"):
            await connection.execute(
                "INSERT INTO bench_balances(account_id, amount, version) VALUES ('missing', 0, 0)"
            )
    finally:
        await connection.close()


async def test_small_open_loop_run_offers_requested_rate(tmp_path: Path) -> None:
    result, _ = await run_offered_rate_repeat(
        tmp_path,
        repeat=1,
        offered_tps=10.0,
        warmup_seconds=0.2,
        measurement_seconds=0.5,
        workers=2,
        seed_accounts=4,
    )

    assert result["target_offered_tps"] == 10.0
    assert result["actual_offered_tps"] == 10.0
    assert result["scheduled_operations"] == 5
    assert result["invariant_failures"] == []
    assert result["backlog_at_window_end"] >= 0


async def test_small_saturation_diagnostic_preserves_invariants(tmp_path: Path) -> None:
    result, _ = await run_saturation_level(tmp_path, concurrency=4, operations=20, seed_accounts=4)

    assert result["succeeded"] == 20
    assert result["invariant_failures"] == []
    assert result["workload"] == {"create": 4, "credit": 8, "guarded_debit": 8}


async def test_competing_creation_converges_on_one_player_and_wallet(tmp_path: Path) -> None:
    result = await run_duplicate_creation(tmp_path, concurrency=4)

    assert result["passed"] is True
    assert result["stored_players"] == 1
    assert result["stored_wallets"] == 1


async def test_injected_failure_rolls_back_every_write(tmp_path: Path) -> None:
    result = await run_rollback_check(tmp_path)

    assert result["passed"] is True


async def test_busy_timeout_is_applied(tmp_path: Path) -> None:
    result = await run_busy_timeout_check(tmp_path)

    assert result["passed"] is True


async def test_retry_succeeds_after_transient_lock(tmp_path: Path) -> None:
    result = await run_retry_recovery_check(tmp_path)

    assert result["passed"] is True
    assert result["attempts"] == 2


async def test_retry_exhaustion_stays_inside_budget(tmp_path: Path) -> None:
    result = await run_retry_exhaustion_check(tmp_path)

    assert result["passed"] is True
    assert result["attempts"] == 3


async def test_wal_reader_sees_committed_snapshot_during_write(tmp_path: Path) -> None:
    result = await run_wal_reader_check(tmp_path)

    assert result["passed"] is True


async def test_guarded_debit_contention_cannot_overdraw(tmp_path: Path) -> None:
    result = await run_guarded_contention_check(tmp_path, concurrency=16)

    assert result["passed"] is True
    assert result["applied"] == 5
    assert result["insufficient"] == 11
    assert result["ending_balance"] == 0


async def test_transport_and_business_idempotency_semantics(tmp_path: Path) -> None:
    result = await run_idempotency_check(tmp_path)

    assert result["passed"] is True
    assert result["first_applied"] is True
    assert result["same_key_same_fingerprint_applied"] is False
    assert result["same_key_mismatched_fingerprint_rejected"] is True
    assert result["distinct_transport_same_business_applied"] is False
    assert result["wallet_delta"] == 1


def test_checked_sqlite_evidence_matches_current_benchmark_contract() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    configuration = evidence["configuration"]
    assessment = evidence["capacity_assessment"]

    assert evidence["evidence_format"] == EVIDENCE_FORMAT_VERSION
    assert evidence["benchmark_schema"] == SCHEMA_VERSION
    assert evidence["implementation_sha256"] == implementation_sha256(), (
        "regenerate SQLite evidence with the command in docs/sqlite-capacity.md"
    )
    assert configuration["projected_peak_tps"] == PROJECTED_PEAK_TPS
    assert configuration["twice_projected_peak_tps"] == TWICE_PROJECTED_PEAK_TPS
    assert configuration["offered_tps"] == TWICE_PROJECTED_PEAK_TPS
    assert configuration["warmup_seconds"] == DEFAULT_WARMUP_SECONDS
    assert configuration["measurement_seconds"] == DEFAULT_MEASUREMENT_SECONDS
    assert configuration["repeats"] == DEFAULT_REPEATS
    assert configuration["workers"] == DEFAULT_WORKERS
    assert len(evidence["open_loop_runs"]) == DEFAULT_REPEATS
    assert assessment["projected_peak_tps"] == PROJECTED_PEAK_TPS
    assert assessment["twice_projected_peak_tps"] == TWICE_PROJECTED_PEAK_TPS
    assert assessment["offered_tps"] == TWICE_PROJECTED_PEAK_TPS
    assert all(result["passed"] for result in evidence["diagnostics"].values())
