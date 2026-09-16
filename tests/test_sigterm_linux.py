from __future__ import annotations

import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(sys.platform != "linux", reason="native POSIX SIGTERM contract"),
    pytest.mark.native_linux_kernel,
]

_SIGTERM_PROBE = r"""
import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from butterbot.discord_app.startup import serve_until_shutdown
from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.process_lock import DatabaseProcessLock


async def main():
    database = Path(sys.argv[1])
    mode = sys.argv[2]
    runtime = await create_database_runtime(database)
    owners = []
    entered = asyncio.Event()
    finish = asyncio.Event()
    allow_commit = asyncio.Event()
    commit_started = asyncio.Event()
    original_commit = AsyncSession.commit

    if mode == "committing":
        async def delayed_commit(session):
            commit_started.set()
            print("READY:committing", flush=True)
            await allow_commit.wait()
            await asyncio.sleep(0.2)
            await original_commit(session)
        AsyncSession.commit = delayed_commit

    async def owner():
        async with runtime.unit_of_work_factory():
            entered.set()
            if mode != "committing":
                await finish.wait()

    class Bot:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def start(self, token):
            del token
            if mode == "active":
                owners.append(asyncio.create_task(owner()))
                await entered.wait()
                print("READY:active", flush=True)
            elif mode == "waiting":
                owners.extend(asyncio.create_task(owner()) for _ in range(5))
                await entered.wait()
                while not runtime._lifecycle._waiting:
                    await asyncio.sleep(0)
                print("READY:waiting", flush=True)
            else:
                owners.append(asyncio.create_task(owner()))
                await commit_started.wait()
            await self.closed.wait()

        async def close(self):
            finish.set()
            allow_commit.set()
            self.closed.set()

        closed = asyncio.Event()

    try:
        await serve_until_shutdown(Bot(), "unused")
    finally:
        await runtime.close()
        await asyncio.gather(*owners, return_exceptions=True)
    print("CLOSED", flush=True)
    lock = DatabaseProcessLock(database.parent / ".butterbot-process.lock")
    lock.acquire()
    lock.release()
    print("LOCK_RELEASED", flush=True)


asyncio.run(main())
"""

_SIGTERM_FAIL_STOP_PROBE = r"""
import asyncio
import sys
from pathlib import Path

from butterbot.discord_app.startup import serve_until_shutdown
from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.process_lock import (
    DatabaseProcessLock,
    ProcessLockUnavailable,
)
from butterbot.infrastructure.persistence.unit_of_work import ShutdownIncomplete


async def main():
    database = Path(sys.argv[1])
    runtime = await create_database_runtime(database)
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def owner():
        async with runtime.unit_of_work_factory():
            entered.set()
            while not finish.is_set():
                try:
                    await finish.wait()
                except asyncio.CancelledError:
                    print("OWNER_CANCELLATION_OBSERVED", flush=True)

    owner_task = asyncio.create_task(owner())

    class Bot:
        closed = asyncio.Event()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def start(self, token):
            del token
            await entered.wait()
            print("READY:unresolved", flush=True)
            await self.closed.wait()

        async def close(self):
            print("DISCORD_CLOSE_ENTERED", flush=True)
            self.closed.set()

    await serve_until_shutdown(Bot(), "unused")
    try:
        await runtime.close(drain_timeout_seconds=0.01)
    except ShutdownIncomplete:
        contender = DatabaseProcessLock(database.parent / ".butterbot-process.lock")
        try:
            contender.acquire()
        except ProcessLockUnavailable:
            print("FAIL_STOP_LOCK_HELD", flush=True)
        else:
            contender.release()
            raise RuntimeError("process ownership was released while owner was unresolved")
        finish.set()
        await owner_task
        await runtime.close(drain_timeout_seconds=0.2)
        return 24
    raise RuntimeError("unresolved transaction owner did not fail stopped")


raise SystemExit(asyncio.run(main()))
"""


def _run_after_external_sigterm(
    probe: str,
    database: Path,
    *arguments: str,
) -> tuple[subprocess.CompletedProcess[str], str, float]:
    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-c", probe, str(database), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    readable, _, _ = select.select([process.stdout], [], [], 10)
    if not readable:
        process.kill()
        _, stderr = process.communicate()
        pytest.fail(f"SIGTERM probe did not become ready: {stderr}")
    ready = process.stdout.readline().strip()
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    completed = subprocess.CompletedProcess(
        process.args,
        process.returncode,
        stdout=f"{ready}\n{stdout}",
        stderr=stderr,
    )
    return completed, ready, time.monotonic() - started


@pytest.mark.parametrize("phase", ["active", "waiting", "committing"])
def test_native_sigterm_drains_transactions_and_releases_process_lock(
    migrated_database: Path, phase: str
) -> None:
    result, ready, elapsed = _run_after_external_sigterm(_SIGTERM_PROBE, migrated_database, phase)

    assert result.returncode == 0, result.stderr
    assert ready == f"READY:{phase}"
    assert "CLOSED" in result.stdout
    assert "LOCK_RELEASED" in result.stdout
    assert elapsed < 30


def test_native_sigterm_fail_stops_while_transaction_owner_is_unresolved(
    migrated_database: Path,
) -> None:
    result, ready, elapsed = _run_after_external_sigterm(
        _SIGTERM_FAIL_STOP_PROBE, migrated_database
    )

    assert result.returncode == 24, result.stderr
    assert ready == "READY:unresolved"
    assert "DISCORD_CLOSE_ENTERED" in result.stdout
    assert "OWNER_CANCELLATION_OBSERVED" in result.stdout
    assert "FAIL_STOP_LOCK_HELD" in result.stdout
    assert elapsed < 30
