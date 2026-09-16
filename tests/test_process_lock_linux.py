from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.storage import (
    DatabaseIdentityMismatch,
    DatabaseStorageContract,
    UnsafeDatabaseStorage,
    validate_database_storage,
)
from butterbot.infrastructure.persistence.unit_of_work import TransactionPhase

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux ownership contract")

_LOCK_PROBE = """
import sys
from pathlib import Path
from butterbot.infrastructure.persistence.process_lock import (
    DatabaseProcessLock,
    ProcessLockUnavailable,
)

lock = DatabaseProcessLock(Path(sys.argv[1]))
try:
    lock.acquire()
except ProcessLockUnavailable:
    raise SystemExit(23)
print("READY", flush=True)
sys.stdin.readline()
lock.release()
"""


def _attempt_owner(lock_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _LOCK_PROBE, str(lock_path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.native_linux_kernel
def test_linux_process_ownership_survives_lock_path_unlink_and_recreate(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".butterbot-process.lock"
    owner = subprocess.Popen(
        [sys.executable, "-c", _LOCK_PROBE, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == "READY"

        lock_path.write_text("replacement", encoding="utf-8")
        lock_path.unlink()
        lock_path.write_text("second replacement", encoding="utf-8")

        contender = _attempt_owner(lock_path)
        assert contender.returncode == 23
    finally:
        if owner.stdin is not None:
            owner.stdin.close()
        owner.wait(timeout=5)

    successor = _attempt_owner(lock_path)
    assert successor.returncode == 0
    assert successor.stdout.strip() == "READY"


@pytest.mark.native_linux_kernel
def test_linux_process_ownership_survives_root_rename_and_recreation(tmp_path: Path) -> None:
    original_root = tmp_path / "data"
    moved_root = tmp_path / "moved-data"
    original_root.mkdir()
    lock_path = original_root / ".butterbot-process.lock"
    owner = subprocess.Popen(
        [sys.executable, "-c", _LOCK_PROBE, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == "READY"

        original_root.rename(moved_root)
        original_root.mkdir()
        contender = _attempt_owner(original_root / ".butterbot-process.lock")
        assert contender.returncode == 23
    finally:
        if owner.stdin is not None:
            owner.stdin.close()
        owner.wait(timeout=5)


@pytest.mark.native_linux_kernel
async def test_linux_database_replacement_during_active_transaction_fails_before_commit(
    migrated_database: Path,
) -> None:
    pristine = migrated_database.with_name("pristine.sqlite3")
    moved = migrated_database.with_name("moved.sqlite3")
    shutil.copyfile(migrated_database, pristine)
    runtime = await create_database_runtime(migrated_database)
    unit_of_work = None
    try:
        with pytest.raises(DatabaseIdentityMismatch):
            async with runtime.unit_of_work_factory() as unit_of_work:
                await unit_of_work.players.create_if_absent(
                    player_id=uuid4(), discord_user_id=3_001, created_at_ms=1
                )
                os.replace(migrated_database, moved)
                shutil.copyfile(pristine, migrated_database)
        assert unit_of_work is not None
        assert unit_of_work.transaction_phase is TransactionPhase.FAILED
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


async def test_linux_replacement_after_final_validation_preserves_commit_and_marks_unsafe(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pristine = migrated_database.with_name("post-check-pristine.sqlite3")
    moved = migrated_database.with_name("post-check-moved.sqlite3")
    shutil.copyfile(migrated_database, pristine)
    runtime = await create_database_runtime(migrated_database)
    guard = runtime.unit_of_work_factory.identity_guard
    original_verify = guard.verify_connection_path
    armed = False
    replaced = False
    callbacks: list[str] = []

    def replace_after_validation(connection_database_path: str) -> None:
        nonlocal replaced
        original_verify(connection_database_path)
        if armed and not replaced:
            os.replace(migrated_database, moved)
            shutil.copyfile(pristine, migrated_database)
            replaced = True

    monkeypatch.setattr(guard, "verify_connection_path", replace_after_validation)

    async def owner() -> str:
        nonlocal armed
        async with runtime.unit_of_work_factory() as unit_of_work:
            await unit_of_work.players.create_if_absent(
                player_id=uuid4(), discord_user_id=3_003, created_at_ms=1
            )
            unit_of_work.defer_until_commit(lambda: callbacks.append("committed"))
            armed = True
        return "committed-result"

    try:
        assert await owner() == "committed-result"
        assert replaced is True
        assert callbacks == ["committed"]
        assert runtime.storage_monitor.is_safe() is False
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


@pytest.mark.native_linux_kernel
async def test_linux_approved_root_replacement_during_active_transaction_fails_before_commit(
    migrated_database: Path,
) -> None:
    approved_root = migrated_database.parent
    moved_root = approved_root.with_name(f"{approved_root.name}-moved")
    runtime = await create_database_runtime(migrated_database)
    unit_of_work = None
    try:
        with pytest.raises(DatabaseIdentityMismatch):
            async with runtime.unit_of_work_factory() as unit_of_work:
                await unit_of_work.players.create_if_absent(
                    player_id=uuid4(), discord_user_id=3_002, created_at_ms=1
                )
                approved_root.rename(moved_root)
                approved_root.mkdir()
                shutil.copyfile(moved_root / migrated_database.name, migrated_database)
        assert unit_of_work is not None
        assert unit_of_work.transaction_phase is TransactionPhase.FAILED
    finally:
        await runtime.close(drain_timeout_seconds=0.1)


def test_linux_production_contract_rejects_service_owned_replaceable_storage(
    migrated_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from butterbot.infrastructure.persistence import storage as storage_module

    mountinfo = migrated_database.parent / "mountinfo"
    mountinfo.write_text(
        f"29 23 8:1 / {migrated_database.parent.as_posix()} rw,relatime - ext4 /dev/test rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_module, "LINUX_MOUNTINFO_PATH", mountinfo)
    get_effective_uid = cast("Callable[[], int]", os.__dict__["geteuid"])
    get_effective_gid = cast("Callable[[], int]", os.__dict__["getegid"])

    with pytest.raises(UnsafeDatabaseStorage, match="must not run as root|must not own"):
        validate_database_storage(
            migrated_database,
            DatabaseStorageContract(
                migrated_database.parent,
                required_volume_id="8:1",
                administrator_uid=get_effective_uid(),
                service_group_gid=get_effective_gid(),
            ),
        )


@pytest.mark.native_linux_kernel
def test_linux_process_ownership_requires_deployment_init_network_namespace() -> None:
    from butterbot.infrastructure.persistence.storage import validate_linux_network_namespace

    validate_linux_network_namespace()
