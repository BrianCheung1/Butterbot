"""Reproducible Phase 0 SQLite capacity and correctness experiment.

The schema is disposable benchmark infrastructure. It is deliberately not imported by the
application and must never be copied into Alembic history.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal
from uuid import NAMESPACE_URL, uuid5

import aiosqlite

BUSY_TIMEOUT_MS: Final = 1_000
MAX_RETRIES: Final = 2
RETRY_BUDGET_MS: Final = 3_000
RETRY_BACKOFF_MS: Final = (25, 75)
RETRY_DEADLINE_GUARD_MS: Final = 200
PROJECTED_PEAK_TPS: Final = 17.0
TWICE_PROJECTED_PEAK_TPS: Final = 34.0
DEFAULT_WARMUP_SECONDS: Final = 10.0
DEFAULT_MEASUREMENT_SECONDS: Final = 30.0
DEFAULT_REPEATS: Final = 3
DEFAULT_WORKERS: Final = 4
DEFAULT_SATURATION_CONCURRENCY: Final = (1, 4, 8, 16)
DEFAULT_SATURATION_OPERATIONS: Final = 800
DEFAULT_SEED_ACCOUNTS: Final = 64
INITIAL_WALLET_BALANCE: Final = 1_000
SCHEMA_VERSION: Final = "phase0-disposable-v2"
EVIDENCE_FORMAT_VERSION: Final = "phase0-sqlite-evidence-v2"
SYSTEM_ISSUANCE_ACCOUNT_ID: Final = "00000000-0000-0000-0000-000000000001"
SYSTEM_RETIREMENT_ACCOUNT_ID: Final = "00000000-0000-0000-0000-000000000002"

OperationKind = Literal["create", "credit", "guarded_debit"]

SCHEMA_SQL: Final = """
CREATE TABLE bench_players (
    id TEXT PRIMARY KEY,
    discord_user_id INTEGER NOT NULL UNIQUE CHECK (discord_user_id >= 0)
);
CREATE TABLE bench_accounts (
    id TEXT PRIMARY KEY,
    player_id TEXT REFERENCES bench_players(id) ON DELETE RESTRICT,
    account_kind TEXT NOT NULL CHECK (account_kind IN ('wallet', 'issuance', 'retirement')),
    UNIQUE (player_id, account_kind)
);
CREATE TABLE bench_balances (
    account_id TEXT PRIMARY KEY REFERENCES bench_accounts(id) ON DELETE RESTRICT,
    amount INTEGER NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 0)
);
CREATE TABLE bench_requests (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    transport_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    outcome TEXT NOT NULL,
    UNIQUE (operation, transport_key)
);
CREATE TABLE bench_entitlements (
    operation TEXT NOT NULL,
    business_key TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE REFERENCES bench_requests(id) ON DELETE RESTRICT,
    PRIMARY KEY (operation, business_key)
);
CREATE TABLE bench_ledger_transactions (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE REFERENCES bench_requests(id) ON DELETE RESTRICT,
    committed_at_ms INTEGER NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE bench_postings (
    transaction_id TEXT NOT NULL REFERENCES bench_ledger_transactions(id) ON DELETE RESTRICT,
    account_id TEXT NOT NULL REFERENCES bench_accounts(id) ON DELETE RESTRICT,
    amount INTEGER NOT NULL CHECK (amount != 0),
    PRIMARY KEY (transaction_id, account_id)
);
"""


class IdempotencyFingerprintMismatch(RuntimeError):
    """A transport key was reused with different input."""


class InsufficientFunds(RuntimeError):
    """A guarded debit could not be applied."""


@dataclass(frozen=True)
class RetryPolicy:
    busy_timeout_ms: int = BUSY_TIMEOUT_MS
    max_retries: int = MAX_RETRIES
    total_budget_ms: int = RETRY_BUDGET_MS
    backoff_ms: tuple[int, ...] = RETRY_BACKOFF_MS
    deadline_guard_ms: int = RETRY_DEADLINE_GUARD_MS


DEFAULT_RETRY_POLICY: Final = RetryPolicy()


@dataclass
class OperationSample:
    operation: str
    latency_ms: float
    service_ms: float
    queue_delay_ms: float
    transaction_ms: float
    lock_held_ms: float
    attempts: int
    lock_events: int
    succeeded: bool
    applied: bool
    completed_at: float
    error: str | None = None


@dataclass(frozen=True)
class WorkItem:
    index: int
    kind: OperationKind
    target_index: int
    transport_key: str
    fingerprint: str
    business_key: str
    scheduled_at: float | None = None
    measured: bool = True


@dataclass(frozen=True)
class MutationClaim:
    apply: bool
    request_id: str
    prior_outcome: str


class FinalLockFailure(RuntimeError):
    def __init__(self, sample: OperationSample) -> None:
        super().__init__(sample.error)
        self.sample = sample


def stable_id(kind: str, value: str | int) -> str:
    return str(uuid5(NAMESPACE_URL, f"butterbot-phase0:{kind}:{value}"))


def implementation_sha256() -> str:
    """Fingerprint evidence against the exact benchmark implementation."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def is_locked(error: BaseException) -> bool:
    return isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower()


def make_work_item(
    index: int,
    seed_accounts: int,
    *,
    scheduled_at: float | None = None,
    measured: bool = True,
) -> WorkItem:
    """Create a deterministic 20/40/40 join/credit/guarded-debit mix.

    Guarded debits intentionally target four hot wallets so multiple workers contend on the same
    logical state. Credits are spread across the configured seed wallets.
    """
    position = index % 10
    if position in {0, 5}:
        kind: OperationKind = "create"
        target_index = index
    elif position in {1, 3, 7, 9}:
        kind = "credit"
        target_index = index % seed_accounts
    else:
        kind = "guarded_debit"
        target_index = index % min(seed_accounts, 4)
    return WorkItem(
        index=index,
        kind=kind,
        target_index=target_index,
        transport_key=f"{kind}:{index}",
        fingerprint=f"{kind}:target:{target_index}:amount:1",
        business_key=f"{kind}:{index}",
        scheduled_at=scheduled_at,
        measured=measured,
    )


async def configure_connection(
    connection: aiosqlite.Connection, policy: RetryPolicy = DEFAULT_RETRY_POLICY
) -> None:
    await connection.execute("PRAGMA foreign_keys=ON")
    await connection.execute("PRAGMA synchronous=FULL")
    await connection.execute(f"PRAGMA busy_timeout={policy.busy_timeout_ms}")


async def open_connection(
    database: Path, policy: RetryPolicy = DEFAULT_RETRY_POLICY
) -> aiosqlite.Connection:
    connection = await aiosqlite.connect(database, isolation_level=None)
    await configure_connection(connection, policy)
    return connection


async def fetch_row(
    connection: aiosqlite.Connection, sql: str, parameters: Sequence[object] = ()
) -> tuple[Any, ...]:
    row = await (await connection.execute(sql, parameters)).fetchone()
    if row is None:
        raise RuntimeError(f"query unexpectedly returned no row: {sql}")
    return tuple(row)


async def fetch_int(
    connection: aiosqlite.Connection, sql: str, parameters: Sequence[object] = ()
) -> int:
    return int((await fetch_row(connection, sql, parameters))[0])


async def initialize_database(database: Path, seed_accounts: int) -> dict[str, Any]:
    connection = await open_connection(database)
    try:
        journal_mode = str((await fetch_row(connection, "PRAGMA journal_mode=WAL"))[0])
        await connection.executescript(SCHEMA_SQL)
        system_accounts = (
            (SYSTEM_ISSUANCE_ACCOUNT_ID, "issuance", -seed_accounts * INITIAL_WALLET_BALANCE),
            (SYSTEM_RETIREMENT_ACCOUNT_ID, "retirement", 0),
        )
        for account_id, kind, balance in system_accounts:
            await connection.execute(
                "INSERT INTO bench_accounts(id, player_id, account_kind) VALUES (?, NULL, ?)",
                (account_id, kind),
            )
            await connection.execute(
                "INSERT INTO bench_balances(account_id, amount, version) VALUES (?, ?, 0)",
                (account_id, balance),
            )
        for index in range(seed_accounts):
            player_id = stable_id("seed-player", index)
            account_id = stable_id("seed-wallet", index)
            await connection.execute(
                "INSERT INTO bench_players(id, discord_user_id) VALUES (?, ?)",
                (player_id, 1_000_000 + index),
            )
            await connection.execute(
                "INSERT INTO bench_accounts(id, player_id, account_kind) VALUES (?, ?, 'wallet')",
                (account_id, player_id),
            )
            await connection.execute(
                "INSERT INTO bench_balances(account_id, amount, version) VALUES (?, ?, 0)",
                (account_id, INITIAL_WALLET_BALANCE),
            )
        return {
            "foreign_keys": await fetch_int(connection, "PRAGMA foreign_keys"),
            "journal_mode": journal_mode,
            "synchronous": await fetch_int(connection, "PRAGMA synchronous"),
            "busy_timeout_ms": await fetch_int(connection, "PRAGMA busy_timeout"),
        }
    finally:
        await connection.close()


async def claim_mutation(
    connection: aiosqlite.Connection,
    *,
    operation: str,
    transport_key: str,
    fingerprint: str,
    business_key: str,
    request_id: str,
) -> MutationClaim:
    existing = await (
        await connection.execute(
            "SELECT fingerprint, outcome FROM bench_requests "
            "WHERE operation = ? AND transport_key = ?",
            (operation, transport_key),
        )
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != fingerprint:
            raise IdempotencyFingerprintMismatch(
                f"transport key {transport_key!r} was reused with a different fingerprint"
            )
        return MutationClaim(apply=False, request_id=request_id, prior_outcome=str(existing[1]))

    await connection.execute(
        "INSERT INTO bench_requests(id, operation, transport_key, fingerprint, outcome) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (request_id, operation, transport_key, fingerprint),
    )
    entitlement = await connection.execute(
        "INSERT INTO bench_entitlements(operation, business_key, request_id) VALUES (?, ?, ?) "
        "ON CONFLICT(operation, business_key) DO NOTHING",
        (operation, business_key, request_id),
    )
    if entitlement.rowcount == 1:
        return MutationClaim(apply=True, request_id=request_id, prior_outcome="pending")

    winner = await fetch_row(
        connection,
        "SELECT r.outcome FROM bench_entitlements e "
        "JOIN bench_requests r ON r.id = e.request_id "
        "WHERE e.operation = ? AND e.business_key = ?",
        (operation, business_key),
    )
    prior_outcome = str(winner[0])
    await connection.execute(
        "UPDATE bench_requests SET outcome = ? WHERE id = ?",
        (prior_outcome, request_id),
    )
    return MutationClaim(apply=False, request_id=request_id, prior_outcome=prior_outcome)


async def finish_request(connection: aiosqlite.Connection, request_id: str, outcome: str) -> None:
    updated = await connection.execute(
        "UPDATE bench_requests SET outcome = ? WHERE id = ?", (outcome, request_id)
    )
    if updated.rowcount != 1:
        raise RuntimeError("idempotency request disappeared before completion")


async def create_player_wallet(
    connection: aiosqlite.Connection,
    item: WorkItem,
    *,
    duplicate_discord_id: int | None = None,
) -> bool:
    discord_id = duplicate_discord_id or 2_000_000 + item.target_index
    request_id = stable_id("request", f"{item.transport_key}:{item.index}")
    claim = await claim_mutation(
        connection,
        operation="join",
        transport_key=item.transport_key,
        fingerprint=item.fingerprint,
        business_key=f"discord:{discord_id}",
        request_id=request_id,
    )
    if not claim.apply:
        return False

    player_id = stable_id("player", discord_id)
    wallet_id = stable_id("wallet", discord_id)
    player = await connection.execute(
        "INSERT INTO bench_players(id, discord_user_id) VALUES (?, ?) "
        "ON CONFLICT(discord_user_id) DO NOTHING",
        (player_id, discord_id),
    )
    stored_player_id = str(
        (
            await fetch_row(
                connection,
                "SELECT id FROM bench_players WHERE discord_user_id = ?",
                (discord_id,),
            )
        )[0]
    )
    await connection.execute(
        "INSERT INTO bench_accounts(id, player_id, account_kind) VALUES (?, ?, 'wallet') "
        "ON CONFLICT(player_id, account_kind) DO NOTHING",
        (wallet_id, stored_player_id),
    )
    stored_wallet_id = str(
        (
            await fetch_row(
                connection,
                "SELECT id FROM bench_accounts WHERE player_id = ? AND account_kind = 'wallet'",
                (stored_player_id,),
            )
        )[0]
    )
    await connection.execute(
        "INSERT INTO bench_balances(account_id, amount, version) VALUES (?, 0, 0) "
        "ON CONFLICT(account_id) DO NOTHING",
        (stored_wallet_id,),
    )
    created = player.rowcount == 1
    await finish_request(connection, request_id, "created" if created else "existing")
    return created


async def write_ledger(
    connection: aiosqlite.Connection,
    item: WorkItem,
    *,
    fail_before_postings: bool = False,
) -> bool:
    if item.kind not in {"credit", "guarded_debit"}:
        raise ValueError("write_ledger requires a credit or guarded_debit item")
    operation = f"ledger_{item.kind}"
    request_id = stable_id("request", f"{item.transport_key}:{item.index}")
    claim = await claim_mutation(
        connection,
        operation=operation,
        transport_key=item.transport_key,
        fingerprint=item.fingerprint,
        business_key=item.business_key,
        request_id=request_id,
    )
    if not claim.apply:
        return False

    wallet_id = stable_id("seed-wallet", item.target_index)
    transaction_id = stable_id("ledger-transaction", f"{item.transport_key}:{item.index}")
    await connection.execute(
        "INSERT INTO bench_ledger_transactions(id, request_id, committed_at_ms, reason) "
        "VALUES (?, ?, ?, ?)",
        (transaction_id, request_id, item.index, f"benchmark.{item.kind}"),
    )

    if item.kind == "credit":
        wallet_update = await connection.execute(
            "UPDATE bench_balances SET amount = amount + 1, version = version + 1 "
            "WHERE account_id = ?",
            (wallet_id,),
        )
        system_update = await connection.execute(
            "UPDATE bench_balances SET amount = amount - 1, version = version + 1 "
            "WHERE account_id = ?",
            (SYSTEM_ISSUANCE_ACCOUNT_ID,),
        )
        postings = (
            (transaction_id, SYSTEM_ISSUANCE_ACCOUNT_ID, -1),
            (transaction_id, wallet_id, 1),
        )
    else:
        amount, version = await fetch_row(
            connection,
            "SELECT amount, version FROM bench_balances WHERE account_id = ?",
            (wallet_id,),
        )
        if int(amount) < 1:
            raise InsufficientFunds("guarded debit requires a positive available balance")
        wallet_update = await connection.execute(
            "UPDATE bench_balances SET amount = amount - 1, version = version + 1 "
            "WHERE account_id = ? AND amount >= 1 AND version = ?",
            (wallet_id, int(version)),
        )
        system_update = await connection.execute(
            "UPDATE bench_balances SET amount = amount + 1, version = version + 1 "
            "WHERE account_id = ?",
            (SYSTEM_RETIREMENT_ACCOUNT_ID,),
        )
        postings = (
            (transaction_id, wallet_id, -1),
            (transaction_id, SYSTEM_RETIREMENT_ACCOUNT_ID, 1),
        )
    if wallet_update.rowcount != 1 or system_update.rowcount != 1:
        raise RuntimeError("guarded balance projection update missed or was stale")
    if fail_before_postings:
        raise RuntimeError("injected failure before postings")
    await connection.executemany(
        "INSERT INTO bench_postings(transaction_id, account_id, amount) VALUES (?, ?, ?)",
        postings,
    )
    await finish_request(connection, request_id, "committed")
    return True


async def run_with_retry[T](
    connection: aiosqlite.Connection,
    operation: str,
    body: Callable[[], Awaitable[T]],
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    *,
    scheduled_at: float | None = None,
) -> tuple[T, OperationSample]:
    service_started = time.perf_counter()
    latency_started = scheduled_at if scheduled_at is not None else service_started
    queue_delay_ms = max(0.0, (service_started - latency_started) * 1_000)
    attempts = 0
    lock_events = 0
    transaction_ms = 0.0
    lock_held_ms = 0.0
    while True:
        attempts += 1
        elapsed_before_attempt_ms = (time.perf_counter() - service_started) * 1_000
        remaining_before_attempt_ms = policy.total_budget_ms - elapsed_before_attempt_ms
        attempt_timeout_ms = min(
            policy.busy_timeout_ms,
            max(1, int(remaining_before_attempt_ms - policy.deadline_guard_ms)),
        )
        await connection.execute(f"PRAGMA busy_timeout={attempt_timeout_ms}")
        transaction_started = time.perf_counter()
        try:
            await connection.execute("BEGIN IMMEDIATE")
            lock_acquired = time.perf_counter()
            value = await body()
            await connection.commit()
            completed_at = time.perf_counter()
            lock_held_ms = (completed_at - lock_acquired) * 1_000
            await connection.execute(f"PRAGMA busy_timeout={policy.busy_timeout_ms}")
            transaction_ms += (completed_at - transaction_started) * 1_000
            return value, OperationSample(
                operation=operation,
                latency_ms=(completed_at - latency_started) * 1_000,
                service_ms=(completed_at - service_started) * 1_000,
                queue_delay_ms=queue_delay_ms,
                transaction_ms=transaction_ms,
                lock_held_ms=lock_held_ms,
                attempts=attempts,
                lock_events=lock_events,
                succeeded=True,
                applied=bool(value),
                completed_at=completed_at,
            )
        except BaseException as error:
            transaction_ms += (time.perf_counter() - transaction_started) * 1_000
            await connection.rollback()
            if not is_locked(error):
                await connection.execute(f"PRAGMA busy_timeout={policy.busy_timeout_ms}")
                raise
            lock_events += 1
            completed_at = time.perf_counter()
            elapsed_ms = (completed_at - service_started) * 1_000
            exhausted = attempts > policy.max_retries or elapsed_ms >= policy.total_budget_ms
            if exhausted:
                await connection.execute(f"PRAGMA busy_timeout={policy.busy_timeout_ms}")
                raise FinalLockFailure(
                    OperationSample(
                        operation=operation,
                        latency_ms=(completed_at - latency_started) * 1_000,
                        service_ms=elapsed_ms,
                        queue_delay_ms=queue_delay_ms,
                        transaction_ms=transaction_ms,
                        lock_held_ms=lock_held_ms,
                        attempts=attempts,
                        lock_events=lock_events,
                        succeeded=False,
                        applied=False,
                        completed_at=completed_at,
                        error=str(error),
                    )
                ) from error
            backoff_index = min(attempts - 1, len(policy.backoff_ms) - 1)
            remaining_ms = max(0.0, policy.total_budget_ms - elapsed_ms)
            await asyncio.sleep(min(policy.backoff_ms[backoff_index], remaining_ms) / 1_000)


async def execute_item(connection: aiosqlite.Connection, item: WorkItem) -> OperationSample:
    async def body() -> bool:
        if item.kind == "create":
            return await create_player_wallet(connection, item)
        return await write_ledger(connection, item)

    try:
        _, sample = await run_with_retry(
            connection,
            item.kind,
            body,
            scheduled_at=item.scheduled_at,
        )
        return sample
    except FinalLockFailure as error:
        return error.sample


async def verify_invariants(
    database: Path,
    *,
    seed_accounts: int,
    expected_credits: int,
    expected_debits: int,
) -> list[str]:
    connection = await open_connection(database)
    failures: list[str] = []
    expected_ledgers = expected_credits + expected_debits
    try:
        foreign_key_failures = await (
            await connection.execute("PRAGMA foreign_key_check")
        ).fetchall()
        if foreign_key_failures:
            failures.append(f"foreign key failures: {foreign_key_failures!r}")
        unbalanced = await (
            await connection.execute(
                "SELECT transaction_id, SUM(amount) FROM bench_postings "
                "GROUP BY transaction_id HAVING SUM(amount) != 0"
            )
        ).fetchall()
        if unbalanced:
            failures.append(f"unbalanced transactions: {unbalanced!r}")
        incomplete = await (
            await connection.execute(
                "SELECT t.id FROM bench_ledger_transactions t "
                "LEFT JOIN bench_postings p ON p.transaction_id = t.id "
                "GROUP BY t.id HAVING COUNT(p.account_id) != 2"
            )
        ).fetchall()
        if incomplete:
            failures.append(f"transactions without two postings: {incomplete!r}")
        ledger_count = await fetch_int(connection, "SELECT COUNT(*) FROM bench_ledger_transactions")
        posting_count = await fetch_int(connection, "SELECT COUNT(*) FROM bench_postings")
        wallet_total = await fetch_int(
            connection,
            "SELECT COALESCE(SUM(b.amount), 0) FROM bench_balances b "
            "JOIN bench_accounts a ON a.id = b.account_id WHERE a.account_kind = 'wallet'",
        )
        negative_wallets = await fetch_int(
            connection,
            "SELECT COUNT(*) FROM bench_balances b JOIN bench_accounts a ON a.id = b.account_id "
            "WHERE a.account_kind = 'wallet' AND b.amount < 0",
        )
        issuance = await fetch_int(
            connection,
            "SELECT amount FROM bench_balances WHERE account_id = ?",
            (SYSTEM_ISSUANCE_ACCOUNT_ID,),
        )
        retirement = await fetch_int(
            connection,
            "SELECT amount FROM bench_balances WHERE account_id = ?",
            (SYSTEM_RETIREMENT_ACCOUNT_ID,),
        )
        expected_wallet_total = (
            seed_accounts * INITIAL_WALLET_BALANCE + expected_credits - expected_debits
        )
        if ledger_count != expected_ledgers:
            failures.append(f"expected {expected_ledgers} ledgers, found {ledger_count}")
        if posting_count != expected_ledgers * 2:
            failures.append(f"expected {expected_ledgers * 2} postings, found {posting_count}")
        if wallet_total != expected_wallet_total:
            failures.append(f"expected wallet total {expected_wallet_total}, found {wallet_total}")
        if issuance != -(seed_accounts * INITIAL_WALLET_BALANCE + expected_credits):
            failures.append(f"issuance projection mismatch: {issuance}")
        if retirement != expected_debits:
            failures.append(f"retirement projection mismatch: {retirement}")
        if wallet_total != -issuance - retirement:
            failures.append("custody total does not equal minted less retired")
        if negative_wallets:
            failures.append(f"negative wallet balances: {negative_wallets}")
    finally:
        await connection.close()
    return failures


def summarize_samples(
    samples: Sequence[OperationSample],
    elapsed_seconds: float,
    invariant_failures: Sequence[str],
) -> dict[str, Any]:
    successes = [sample for sample in samples if sample.succeeded]
    latencies = [sample.latency_ms for sample in successes]
    service_times = [sample.service_ms for sample in successes]
    queue_delays = [sample.queue_delay_ms for sample in successes]
    lock_held_times = [sample.lock_held_ms for sample in successes]
    retried = sum(sample.attempts > 1 for sample in samples)
    final_lock_failures = sum(not sample.succeeded for sample in samples)
    retry_rate_percent = round(retried / len(samples) * 100, 3) if samples else 0.0
    latency_summary = {
        "median": round(statistics.median(latencies), 3) if latencies else 0.0,
        "p95": round(percentile(latencies, 0.95), 3),
        "p99": round(percentile(latencies, 0.99), 3),
        "max": round(max(latencies), 3) if latencies else 0.0,
    }
    acceptance_failures: list[str] = []
    if latency_summary["p95"] > 100:
        acceptance_failures.append("p95 > 100 ms")
    if latency_summary["p99"] > 250:
        acceptance_failures.append("p99 > 250 ms")
    if retry_rate_percent >= 1:
        acceptance_failures.append("retry rate >= 1%")
    if final_lock_failures:
        acceptance_failures.append("final lock failures")
    if invariant_failures:
        acceptance_failures.append("invariant failures")
    return {
        "scheduled_operations": len(samples),
        "succeeded": len(successes),
        "applied_mutations": sum(sample.applied for sample in successes),
        "completed_tps_including_drain": round(len(successes) / elapsed_seconds, 3),
        "latency_ms": latency_summary,
        "service_ms": {
            "p95": round(percentile(service_times, 0.95), 3),
            "p99": round(percentile(service_times, 0.99), 3),
        },
        "queue_delay_ms": {
            "p95": round(percentile(queue_delays, 0.95), 3),
            "p99": round(percentile(queue_delays, 0.99), 3),
            "max": round(max(queue_delays), 3) if queue_delays else 0.0,
        },
        "lock_held_ms": {
            "p95": round(percentile(lock_held_times, 0.95), 3),
            "p99": round(percentile(lock_held_times, 0.99), 3),
        },
        "retried_operations": retried,
        "retry_rate_percent": retry_rate_percent,
        "lock_events": sum(sample.lock_events for sample in samples),
        "final_lock_failures": final_lock_failures,
        "invariant_failures": list(invariant_failures),
        "acceptance_passed": not acceptance_failures,
        "acceptance_failures": acceptance_failures,
        "workload": {
            kind: sum(sample.operation == kind for sample in samples)
            for kind in ("create", "credit", "guarded_debit")
        },
    }


async def wal_size(database: Path) -> int:
    wal_path = Path(f"{database}-wal")

    def get_size() -> int:
        try:
            return wal_path.stat().st_size
        except FileNotFoundError:
            return 0

    return await asyncio.to_thread(get_size)


async def checkpoint(connection: aiosqlite.Connection, database: Path) -> dict[str, int]:
    bytes_before = await wal_size(database)
    row = await fetch_row(connection, "PRAGMA wal_checkpoint(PASSIVE)")
    return {
        "bytes_before_checkpoint": bytes_before,
        "checkpoint_busy": int(row[0]),
        "log_frames": int(row[1]),
        "checkpointed_frames": int(row[2]),
    }


async def run_saturation_level(
    directory: Path,
    concurrency: int,
    operations: int,
    seed_accounts: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    database = directory / f"saturation-c{concurrency}.sqlite3"
    pragmas = await initialize_database(database, seed_accounts)
    connections = [await open_connection(database) for _ in range(concurrency)]
    queue: asyncio.Queue[WorkItem] = asyncio.Queue()
    for index in range(operations):
        queue.put_nowait(make_work_item(index, seed_accounts))
    samples: list[OperationSample] = []

    async def worker(connection: aiosqlite.Connection) -> None:
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            samples.append(await execute_item(connection, item))
            queue.task_done()

    started = time.perf_counter()
    await asyncio.gather(*(worker(connection) for connection in connections))
    elapsed = time.perf_counter() - started
    wal = await checkpoint(connections[0], database)
    for connection in connections:
        await connection.close()
    credits = sum(s.operation == "credit" and s.applied for s in samples)
    debits = sum(s.operation == "guarded_debit" and s.applied for s in samples)
    failures = await verify_invariants(
        database,
        seed_accounts=seed_accounts,
        expected_credits=credits,
        expected_debits=debits,
    )
    summary = summarize_samples(samples, elapsed, failures)
    summary.update({"concurrency": concurrency, "elapsed_seconds": round(elapsed, 3), "wal": wal})
    return summary, pragmas


async def _schedule_phase(
    queue: asyncio.Queue[WorkItem | None],
    *,
    offered_tps: float,
    duration_seconds: float,
    seed_accounts: int,
    start_index: int,
    measured: bool,
) -> tuple[int, float, float]:
    phase_started = time.perf_counter()
    count = max(1, math.ceil(offered_tps * duration_seconds))
    for offset in range(count):
        scheduled_at = phase_started + offset / offered_tps
        delay = scheduled_at - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        await queue.put(
            make_work_item(
                start_index + offset,
                seed_accounts,
                scheduled_at=scheduled_at,
                measured=measured,
            )
        )
    phase_end = phase_started + duration_seconds
    final_delay = phase_end - time.perf_counter()
    if final_delay > 0:
        await asyncio.sleep(final_delay)
    return count, phase_started, phase_end


async def run_offered_rate_repeat(
    directory: Path,
    *,
    repeat: int,
    offered_tps: float,
    warmup_seconds: float,
    measurement_seconds: float,
    workers: int,
    seed_accounts: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    database = directory / f"offered-repeat-{repeat}.sqlite3"
    pragmas = await initialize_database(database, seed_accounts)
    connections = [await open_connection(database) for _ in range(workers)]
    queue: asyncio.Queue[WorkItem | None] = asyncio.Queue()
    measured_samples: list[OperationSample] = []
    warmup_samples: list[OperationSample] = []

    async def worker(connection: aiosqlite.Connection) -> None:
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return
            sample = await execute_item(connection, item)
            if item.measured:
                measured_samples.append(sample)
            else:
                warmup_samples.append(sample)
            queue.task_done()

    worker_tasks = [asyncio.create_task(worker(connection)) for connection in connections]
    warmup_count, _, _ = await _schedule_phase(
        queue,
        offered_tps=offered_tps,
        duration_seconds=warmup_seconds,
        seed_accounts=seed_accounts,
        start_index=repeat * 10_000_000,
        measured=False,
    )
    await queue.join()
    measured_count, measured_started, measured_end = await _schedule_phase(
        queue,
        offered_tps=offered_tps,
        duration_seconds=measurement_seconds,
        seed_accounts=seed_accounts,
        start_index=repeat * 10_000_000 + warmup_count,
        measured=True,
    )
    completed_within_window = sum(
        sample.succeeded and sample.completed_at <= measured_end for sample in measured_samples
    )
    backlog_at_window_end = measured_count - len(measured_samples)
    await queue.join()
    measured_elapsed_with_drain = time.perf_counter() - measured_started
    for _ in connections:
        await queue.put(None)
    await queue.join()
    await asyncio.gather(*worker_tasks)
    wal = await checkpoint(connections[0], database)
    for connection in connections:
        await connection.close()
    credits = sum(s.operation == "credit" and s.applied for s in measured_samples)
    debits = sum(s.operation == "guarded_debit" and s.applied for s in measured_samples)
    warmup_credits = sum(s.operation == "credit" and s.applied for s in warmup_samples)
    warmup_debits = sum(s.operation == "guarded_debit" and s.applied for s in warmup_samples)
    failures = await verify_invariants(
        database,
        seed_accounts=seed_accounts,
        expected_credits=credits + warmup_credits,
        expected_debits=debits + warmup_debits,
    )
    summary = summarize_samples(measured_samples, measured_elapsed_with_drain, failures)
    completion_percent = completed_within_window / measured_count * 100
    if completion_percent < 99:
        summary["acceptance_failures"].append("less than 99% completed inside measurement window")
        summary["acceptance_passed"] = False
    summary.update(
        {
            "repeat": repeat,
            "workers": workers,
            "warmup_seconds": warmup_seconds,
            "warmup_operations": warmup_count,
            "measurement_seconds": measurement_seconds,
            "target_offered_tps": offered_tps,
            "actual_offered_tps": round(measured_count / measurement_seconds, 3),
            "completed_within_window": completed_within_window,
            "completed_within_window_tps": round(completed_within_window / measurement_seconds, 3),
            "completion_within_window_percent": round(completion_percent, 3),
            "backlog_at_window_end": backlog_at_window_end,
            "drain_seconds": round(max(0.0, measured_elapsed_with_drain - measurement_seconds), 3),
            "wal": wal,
        }
    )
    return summary, pragmas


async def run_duplicate_creation(directory: Path, concurrency: int = 16) -> dict[str, Any]:
    database = directory / "duplicates.sqlite3"
    await initialize_database(database, seed_accounts=1)
    connections = [await open_connection(database) for _ in range(concurrency)]
    discord_id = 9_999_999

    async def attempt(index: int, connection: aiosqlite.Connection) -> tuple[bool, OperationSample]:
        item = WorkItem(
            index=100_000 + index,
            kind="create",
            target_index=index,
            transport_key=f"duplicate-join:{index}",
            fingerprint=f"discord:{discord_id}",
            business_key=f"discord:{discord_id}",
        )
        return await run_with_retry(
            connection,
            "duplicate_create",
            lambda: create_player_wallet(connection, item, duplicate_discord_id=discord_id),
        )

    outcomes = await asyncio.gather(
        *(attempt(index, connection) for index, connection in enumerate(connections))
    )
    for connection in connections:
        await connection.close()
    check = await open_connection(database)
    try:
        player_count = await fetch_int(
            check,
            "SELECT COUNT(*) FROM bench_players WHERE discord_user_id = ?",
            (discord_id,),
        )
        wallet_count = await fetch_int(
            check,
            "SELECT COUNT(*) FROM bench_accounts a JOIN bench_players p ON p.id = a.player_id "
            "WHERE p.discord_user_id = ?",
            (discord_id,),
        )
    finally:
        await check.close()
    created = sum(value for value, _ in outcomes)
    return {
        "concurrency": concurrency,
        "created_outcomes": created,
        "existing_outcomes": concurrency - created,
        "stored_players": player_count,
        "stored_wallets": wallet_count,
        "passed": created == player_count == wallet_count == 1,
    }


async def run_rollback_check(directory: Path) -> dict[str, Any]:
    database = directory / "rollback.sqlite3"
    await initialize_database(database, seed_accounts=1)
    connection = await open_connection(database)
    item = WorkItem(
        index=200_000,
        kind="credit",
        target_index=0,
        transport_key="rollback-credit",
        fingerprint="credit:target:0:amount:1",
        business_key="rollback-credit",
    )
    error_message = ""
    try:
        await connection.execute("BEGIN IMMEDIATE")
        await write_ledger(connection, item, fail_before_postings=True)
    except RuntimeError as error:
        error_message = str(error)
        await connection.rollback()
    finally:
        await connection.close()
    check = await open_connection(database)
    try:
        request_count = await fetch_int(check, "SELECT COUNT(*) FROM bench_requests")
        ledger_count = await fetch_int(check, "SELECT COUNT(*) FROM bench_ledger_transactions")
        wallet = await fetch_int(
            check,
            "SELECT amount FROM bench_balances WHERE account_id = ?",
            (stable_id("seed-wallet", 0),),
        )
    finally:
        await check.close()
    return {
        "injected_error": error_message,
        "requests_after_rollback": request_count,
        "ledgers_after_rollback": ledger_count,
        "wallet_after_rollback": wallet,
        "passed": request_count == ledger_count == 0 and wallet == INITIAL_WALLET_BALANCE,
    }


async def run_wal_reader_check(directory: Path) -> dict[str, Any]:
    database = directory / "wal-reader.sqlite3"
    await initialize_database(database, seed_accounts=1)
    writer = await open_connection(database)
    reader = await open_connection(database)
    wallet_id = stable_id("seed-wallet", 0)
    try:
        await writer.execute("BEGIN IMMEDIATE")
        await writer.execute(
            "UPDATE bench_balances SET amount = amount + 1 WHERE account_id = ?", (wallet_id,)
        )
        started = time.perf_counter()
        visible = await fetch_int(
            reader,
            "SELECT amount FROM bench_balances WHERE account_id = ?",
            (wallet_id,),
        )
        reader_ms = (time.perf_counter() - started) * 1_000
        await writer.rollback()
    finally:
        await writer.close()
        await reader.close()
    return {
        "reader_latency_ms": round(reader_ms, 3),
        "reader_saw_pre_transaction_value": visible == INITIAL_WALLET_BALANCE,
        "passed": visible == INITIAL_WALLET_BALANCE and reader_ms < BUSY_TIMEOUT_MS,
    }


async def run_busy_timeout_check(directory: Path) -> dict[str, Any]:
    database = directory / "busy-timeout.sqlite3"
    await initialize_database(database, seed_accounts=1)
    locker = await open_connection(database)
    contender = await open_connection(database)
    try:
        await locker.execute("BEGIN IMMEDIATE")
        started = time.perf_counter()
        locked = False
        try:
            await contender.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            locked = is_locked(error)
        elapsed_ms = (time.perf_counter() - started) * 1_000
        await contender.rollback()
        await locker.rollback()
    finally:
        await locker.close()
        await contender.close()
    within_tolerance = BUSY_TIMEOUT_MS * 0.9 <= elapsed_ms <= BUSY_TIMEOUT_MS * 1.5
    return {
        "configured_ms": BUSY_TIMEOUT_MS,
        "observed_ms": round(elapsed_ms, 3),
        "raised_locked": locked,
        "within_tolerance": within_tolerance,
        "passed": locked and within_tolerance,
    }


async def run_retry_recovery_check(directory: Path) -> dict[str, Any]:
    database = directory / "retry-recovery.sqlite3"
    await initialize_database(database, seed_accounts=1)
    locker = await open_connection(database)
    contender = await open_connection(database)
    await locker.execute("BEGIN IMMEDIATE")

    async def release_lock() -> None:
        await asyncio.sleep(1.4)
        await locker.rollback()

    release_task = asyncio.create_task(release_lock())
    item = make_work_item(1, 1)
    try:
        _, sample = await run_with_retry(
            contender,
            "retry_recovery",
            lambda: write_ledger(contender, item),
        )
    finally:
        await release_task
        await contender.close()
        await locker.close()
    failures = await verify_invariants(
        database, seed_accounts=1, expected_credits=1, expected_debits=0
    )
    return {
        "attempts": sample.attempts,
        "lock_events": sample.lock_events,
        "latency_ms": round(sample.latency_ms, 3),
        "within_budget": sample.service_ms <= RETRY_BUDGET_MS,
        "invariant_failures": failures,
        "passed": sample.attempts == 2 and sample.lock_events == 1 and not failures,
    }


async def run_retry_exhaustion_check(directory: Path) -> dict[str, Any]:
    database = directory / "retry-exhaustion.sqlite3"
    await initialize_database(database, seed_accounts=1)
    locker = await open_connection(database)
    contender = await open_connection(database)
    await locker.execute("BEGIN IMMEDIATE")
    sample: OperationSample | None = None
    try:
        try:
            await run_with_retry(contender, "retry_exhaustion", lambda: asyncio.sleep(0))
        except FinalLockFailure as error:
            sample = error.sample
    finally:
        await locker.rollback()
        await contender.close()
        await locker.close()
    if sample is None:
        raise RuntimeError("retry exhaustion check unexpectedly acquired the writer lock")
    return {
        "attempts": sample.attempts,
        "lock_events": sample.lock_events,
        "latency_ms": round(sample.latency_ms, 3),
        "within_budget": sample.service_ms <= RETRY_BUDGET_MS,
        "passed": sample.attempts == MAX_RETRIES + 1
        and sample.lock_events == MAX_RETRIES + 1
        and sample.service_ms <= RETRY_BUDGET_MS,
    }


async def run_guarded_contention_check(directory: Path, concurrency: int = 16) -> dict[str, Any]:
    database = directory / "guarded-contention.sqlite3"
    await initialize_database(database, seed_accounts=1)
    setup = await open_connection(database)
    try:
        await setup.execute(
            "UPDATE bench_balances SET amount = 5 WHERE account_id = ?",
            (stable_id("seed-wallet", 0),),
        )
        await setup.execute(
            "UPDATE bench_balances SET amount = -5 WHERE account_id = ?",
            (SYSTEM_ISSUANCE_ACCOUNT_ID,),
        )
    finally:
        await setup.close()
    connections = [await open_connection(database) for _ in range(concurrency)]

    async def attempt(index: int, connection: aiosqlite.Connection) -> str:
        item = WorkItem(
            index=400_000 + index,
            kind="guarded_debit",
            target_index=0,
            transport_key=f"guarded:{index}",
            fingerprint="debit:wallet:0:amount:1",
            business_key=f"guarded:{index}",
        )
        try:
            await run_with_retry(
                connection,
                "guarded_contention",
                lambda: write_ledger(connection, item),
            )
            return "applied"
        except InsufficientFunds:
            return "insufficient"

    outcomes = await asyncio.gather(
        *(attempt(index, connection) for index, connection in enumerate(connections))
    )
    for connection in connections:
        await connection.close()
    check = await open_connection(database)
    try:
        wallet = await fetch_int(
            check,
            "SELECT amount FROM bench_balances WHERE account_id = ?",
            (stable_id("seed-wallet", 0),),
        )
        ledger_count = await fetch_int(check, "SELECT COUNT(*) FROM bench_ledger_transactions")
        retirement = await fetch_int(
            check,
            "SELECT amount FROM bench_balances WHERE account_id = ?",
            (SYSTEM_RETIREMENT_ACCOUNT_ID,),
        )
    finally:
        await check.close()
    applied = outcomes.count("applied")
    insufficient = outcomes.count("insufficient")
    return {
        "concurrency": concurrency,
        "starting_balance": 5,
        "applied": applied,
        "insufficient": insufficient,
        "ending_balance": wallet,
        "ledger_transactions": ledger_count,
        "retirement_balance": retirement,
        "passed": applied == ledger_count == retirement == 5
        and insufficient == concurrency - 5
        and wallet == 0,
    }


async def run_idempotency_check(directory: Path) -> dict[str, Any]:
    database = directory / "idempotency.sqlite3"
    await initialize_database(database, seed_accounts=1)
    connection = await open_connection(database)
    first = WorkItem(
        index=500_000,
        kind="credit",
        target_index=0,
        transport_key="credit-key",
        fingerprint="credit:wallet:0:amount:1",
        business_key="credit-entitlement",
    )
    same_key = first
    mismatch = WorkItem(
        index=first.index,
        kind=first.kind,
        target_index=first.target_index,
        transport_key=first.transport_key,
        fingerprint="credit:wallet:0:amount:2",
        business_key=first.business_key,
    )
    distinct_transport = WorkItem(
        index=500_001,
        kind=first.kind,
        target_index=first.target_index,
        transport_key="credit-key-2",
        fingerprint=first.fingerprint,
        business_key=first.business_key,
    )
    fingerprint_mismatch_rejected = False
    try:
        first_applied, _ = await run_with_retry(
            connection, "idempotency_first", lambda: write_ledger(connection, first)
        )
        replay_applied, _ = await run_with_retry(
            connection, "idempotency_replay", lambda: write_ledger(connection, same_key)
        )
        try:
            await run_with_retry(
                connection, "idempotency_mismatch", lambda: write_ledger(connection, mismatch)
            )
        except IdempotencyFingerprintMismatch:
            fingerprint_mismatch_rejected = True
        domain_replay_applied, _ = await run_with_retry(
            connection,
            "idempotency_domain_replay",
            lambda: write_ledger(connection, distinct_transport),
        )
    finally:
        await connection.close()
    check = await open_connection(database)
    try:
        wallet = await fetch_int(
            check,
            "SELECT amount FROM bench_balances WHERE account_id = ?",
            (stable_id("seed-wallet", 0),),
        )
        ledgers = await fetch_int(check, "SELECT COUNT(*) FROM bench_ledger_transactions")
        requests = await fetch_int(check, "SELECT COUNT(*) FROM bench_requests")
        entitlements = await fetch_int(check, "SELECT COUNT(*) FROM bench_entitlements")
    finally:
        await check.close()
    return {
        "first_applied": first_applied,
        "same_key_same_fingerprint_applied": replay_applied,
        "same_key_mismatched_fingerprint_rejected": fingerprint_mismatch_rejected,
        "distinct_transport_same_business_applied": domain_replay_applied,
        "wallet_delta": wallet - INITIAL_WALLET_BALANCE,
        "ledger_transactions": ledgers,
        "transport_requests": requests,
        "business_entitlements": entitlements,
        "passed": first_applied
        and not replay_applied
        and fingerprint_mismatch_rejected
        and not domain_replay_applied
        and wallet == INITIAL_WALLET_BALANCE + 1
        and ledgers == entitlements == 1
        and requests == 2,
    }


def environment_metadata(directory: Path, storage_description: str) -> dict[str, Any]:
    usage = shutil.disk_usage(directory)
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "logical_cpus": os.cpu_count(),
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "aiosqlite": aiosqlite.__version__,
        "storage": {
            "temporary_directory": str(directory.parent),
            "description": storage_description,
            "volume_total_bytes": usage.total,
            "volume_free_bytes_at_start": usage.free,
        },
    }


def capacity_assessment(
    offered_runs: Sequence[dict[str, Any]],
    saturation_levels: Sequence[dict[str, Any]],
    *,
    projected_peak_tps: float,
    offered_tps: float,
) -> dict[str, Any]:
    passing_saturation = [level for level in saturation_levels if level["acceptance_passed"]]
    saturation_boundary = passing_saturation[-1] if passing_saturation else None
    saturation_tps = (
        float(saturation_boundary["completed_tps_including_drain"])
        if saturation_boundary is not None
        else 0.0
    )
    every_repeat_passed = all(bool(run["acceptance_passed"]) for run in offered_runs)
    offered_target_met = offered_tps >= projected_peak_tps * 2
    twice_peak_passed = every_repeat_passed and offered_target_met
    start_tps = round(saturation_tps * 0.5, 2)
    complete_tps = round(saturation_tps * 0.7, 2)
    return {
        "projected_peak_tps": projected_peak_tps,
        "twice_projected_peak_tps": projected_peak_tps * 2,
        "offered_tps": offered_tps,
        "repeat_count": len(offered_runs),
        "every_repeat_passed": every_repeat_passed,
        "twice_peak_capacity_gate_passed": twice_peak_passed,
        "highest_p95_ms": max(float(run["latency_ms"]["p95"]) for run in offered_runs),
        "highest_p99_ms": max(float(run["latency_ms"]["p99"]) for run in offered_runs),
        "highest_retry_rate_percent": max(float(run["retry_rate_percent"]) for run in offered_runs),
        "total_final_lock_failures": sum(int(run["final_lock_failures"]) for run in offered_runs),
        "total_invariant_failures": sum(len(run["invariant_failures"]) for run in offered_runs),
        "minimum_completed_within_window_tps": min(
            float(run["completed_within_window_tps"]) for run in offered_runs
        ),
        "saturation_diagnostic_tps": saturation_tps,
        "postgresql_start_tps": start_tps,
        "postgresql_complete_tps": complete_tps,
        "postgresql_load_trigger_reached": (not twice_peak_passed)
        or (saturation_tps > 0 and projected_peak_tps >= start_tps),
    }


async def run_experiment(
    saturation_concurrency: Sequence[int] = DEFAULT_SATURATION_CONCURRENCY,
    saturation_operations: int = DEFAULT_SATURATION_OPERATIONS,
    seed_accounts: int = DEFAULT_SEED_ACCOUNTS,
    *,
    projected_peak_tps: float = PROJECTED_PEAK_TPS,
    offered_tps: float = TWICE_PROJECTED_PEAK_TPS,
    warmup_seconds: float = DEFAULT_WARMUP_SECONDS,
    measurement_seconds: float = DEFAULT_MEASUREMENT_SECONDS,
    repeats: int = DEFAULT_REPEATS,
    workers: int = DEFAULT_WORKERS,
    storage_description: str = "local temporary files; physical production storage not selected",
) -> dict[str, Any]:
    if any(level < 1 for level in saturation_concurrency):
        raise ValueError("saturation concurrency levels must be positive")
    if saturation_operations < max(saturation_concurrency, default=1):
        raise ValueError("saturation operations must cover the highest concurrency")
    if (
        min(
            seed_accounts,
            repeats,
            workers,
        )
        < 1
        or min(projected_peak_tps, offered_tps, warmup_seconds, measurement_seconds) <= 0
    ):
        raise ValueError("benchmark counts, rates, and durations must be positive")
    with tempfile.TemporaryDirectory(prefix="butterbot-sqlite-capacity-") as temp:
        directory = Path(temp)
        saturation_levels: list[dict[str, Any]] = []
        pragmas: dict[str, Any] = {}
        for concurrency in saturation_concurrency:
            level, pragmas = await run_saturation_level(
                directory, concurrency, saturation_operations, seed_accounts
            )
            saturation_levels.append(level)
        offered_runs: list[dict[str, Any]] = []
        for repeat in range(1, repeats + 1):
            result, pragmas = await run_offered_rate_repeat(
                directory,
                repeat=repeat,
                offered_tps=offered_tps,
                warmup_seconds=warmup_seconds,
                measurement_seconds=measurement_seconds,
                workers=workers,
                seed_accounts=seed_accounts,
            )
            offered_runs.append(result)
        diagnostics = {
            "duplicate_creation": await run_duplicate_creation(directory),
            "rollback": await run_rollback_check(directory),
            "wal_reader": await run_wal_reader_check(directory),
            "busy_timeout": await run_busy_timeout_check(directory),
            "retry_recovery": await run_retry_recovery_check(directory),
            "retry_exhaustion": await run_retry_exhaustion_check(directory),
            "guarded_contention": await run_guarded_contention_check(directory),
            "idempotency": await run_idempotency_check(directory),
        }
        return {
            "evidence_format": EVIDENCE_FORMAT_VERSION,
            "benchmark_schema": SCHEMA_VERSION,
            "disposable_schema": True,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "implementation_sha256": implementation_sha256(),
            "environment": environment_metadata(directory, storage_description),
            "configuration": {
                "foreign_keys": "ON",
                "journal_mode": "WAL",
                "synchronous": "FULL",
                "busy_timeout_ms": BUSY_TIMEOUT_MS,
                "max_retries_after_initial": MAX_RETRIES,
                "retry_budget_ms": RETRY_BUDGET_MS,
                "retry_backoff_ms": list(RETRY_BACKOFF_MS),
                "retry_deadline_guard_ms": RETRY_DEADLINE_GUARD_MS,
                "projected_peak_tps": projected_peak_tps,
                "twice_projected_peak_tps": projected_peak_tps * 2,
                "offered_tps": offered_tps,
                "warmup_seconds": warmup_seconds,
                "measurement_seconds": measurement_seconds,
                "repeats": repeats,
                "workers": workers,
                "seed_accounts": seed_accounts,
                "initial_wallet_balance": INITIAL_WALLET_BALANCE,
                "workload_mix": (
                    "20% unique join, 40% credit, 40% sufficient-funds and revision-guarded debit"
                ),
                "saturation_concurrency": list(saturation_concurrency),
                "saturation_operations_per_level": saturation_operations,
            },
            "observed_pragmas": pragmas,
            "open_loop_runs": offered_runs,
            "saturation_diagnostic": saturation_levels,
            "capacity_assessment": capacity_assessment(
                offered_runs,
                saturation_levels,
                projected_peak_tps=projected_peak_tps,
                offered_tps=offered_tps,
            ),
            "diagnostics": diagnostics,
            "limitations": [
                "This is a disposable candidate-persistence workload, not a production schema.",
                "The final mining/gameplay transaction requires its own later load gate.",
                (
                    "The deployment host is not selected; storage metadata describes this "
                    "development run."
                ),
                "Discord/network time is excluded because no transaction may wait on either.",
            ],
        }


def parse_concurrency(value: str) -> tuple[int, ...]:
    try:
        levels = tuple(int(item) for item in value.split(",") if item)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use comma-separated integers") from error
    if not levels or any(level < 1 for level in levels):
        raise argparse.ArgumentTypeError("concurrency levels must be positive")
    return levels


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--saturation-concurrency",
        type=parse_concurrency,
        default=DEFAULT_SATURATION_CONCURRENCY,
    )
    parser.add_argument("--saturation-operations", type=int, default=DEFAULT_SATURATION_OPERATIONS)
    parser.add_argument("--seed-accounts", type=int, default=DEFAULT_SEED_ACCOUNTS)
    parser.add_argument("--projected-peak-tps", type=float, default=PROJECTED_PEAK_TPS)
    parser.add_argument("--offered-tps", type=float, default=TWICE_PROJECTED_PEAK_TPS)
    parser.add_argument("--warmup-seconds", type=float, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument("--measurement-seconds", type=float, default=DEFAULT_MEASUREMENT_SECONDS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--storage-description",
        default="local temporary files; physical production storage not selected",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(
            run_experiment(
                args.saturation_concurrency,
                args.saturation_operations,
                args.seed_accounts,
                projected_peak_tps=args.projected_peak_tps,
                offered_tps=args.offered_tps,
                warmup_seconds=args.warmup_seconds,
                measurement_seconds=args.measurement_seconds,
                repeats=args.repeats,
                workers=args.workers,
                storage_description=args.storage_description,
            )
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
