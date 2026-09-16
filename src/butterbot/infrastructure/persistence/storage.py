from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

MINIMUM_FREE_BYTES = 5 * 1024 * 1024 * 1024
MINIMUM_FREE_PERCENT = 20.0
SUPPORTED_PRODUCTION_FILESYSTEMS = frozenset({"ext4", "xfs"})
LINUX_MOUNTINFO_PATH = Path("/proc/self/mountinfo")

logger = logging.getLogger(__name__)


class UnsafeDatabaseStorage(RuntimeError):
    """The configured database storage cannot satisfy the deployment contract."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class DatabaseIdentityMismatch(RuntimeError):
    """The configured path or a checked-out connection changed database identity."""


@dataclass(frozen=True, slots=True)
class DatabaseStorageContract:
    approved_root: Path
    required_volume_id: str | None = None
    administrator_uid: int | None = None
    service_group_gid: int | None = None


@dataclass(frozen=True, slots=True)
class ValidatedDatabaseStorage:
    database_path: Path
    approved_root: Path
    device: int
    inode: int
    root_device: int
    root_inode: int
    free_bytes: int
    free_percent: float
    filesystem: str | None
    volume_id: str


@dataclass(frozen=True, slots=True)
class _LinuxMount:
    mount_point: Path
    filesystem: str
    volume_id: str


def validate_database_storage(
    database_path: Path,
    contract: DatabaseStorageContract,
) -> ValidatedDatabaseStorage:
    if not database_path.is_absolute():
        raise UnsafeDatabaseStorage("unsafe_path", "database path must be absolute")
    if not contract.approved_root.is_absolute():
        raise UnsafeDatabaseStorage("unsafe_path", "approved database root must be absolute")
    if _contains_symlink(database_path) or _contains_symlink(contract.approved_root):
        raise UnsafeDatabaseStorage(
            "unsafe_path", "database path and approved root must not traverse symlinks"
        )
    try:
        canonical_path = database_path.resolve(strict=True)
        canonical_root = contract.approved_root.resolve(strict=True)
    except OSError as error:
        raise UnsafeDatabaseStorage(
            "missing_database", "database path or approved root does not exist"
        ) from error
    if not canonical_root.is_dir():
        raise UnsafeDatabaseStorage("unsafe_path", "approved database root is not a directory")
    if not canonical_path.is_file():
        raise UnsafeDatabaseStorage("unsafe_path", "database path is not a regular file")
    try:
        relative_path = canonical_path.relative_to(canonical_root)
    except ValueError as error:
        raise UnsafeDatabaseStorage(
            "unsafe_path", "database path is outside the approved data root"
        ) from error
    if len(relative_path.parts) != 1:
        raise UnsafeDatabaseStorage(
            "unsafe_path", "database file must be directly inside the approved data root"
        )

    stat_result = canonical_path.stat()
    root_stat = canonical_root.stat()
    if stat_result.st_nlink != 1:
        raise UnsafeDatabaseStorage("unsafe_path", "database file must not have hard-link aliases")

    usage = shutil.disk_usage(canonical_root)
    free_percent = usage.free / usage.total * 100 if usage.total else 0.0
    if usage.free < MINIMUM_FREE_BYTES or free_percent < MINIMUM_FREE_PERCENT:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "database volume must have at least 5 GiB and 20% free"
        )

    filesystem: str | None = None
    volume_id = str(stat_result.st_dev)
    if contract.required_volume_id is not None:
        if contract.administrator_uid is None or contract.service_group_gid is None:
            raise UnsafeDatabaseStorage(
                "unsafe_storage",
                "production storage requires approved administrator UID and service-group GID",
            )
        mount = _linux_mount_for(canonical_path)
        filesystem = mount.filesystem
        volume_id = mount.volume_id
        if mount.filesystem not in SUPPORTED_PRODUCTION_FILESYSTEMS:
            raise UnsafeDatabaseStorage(
                "unsafe_storage", "production database filesystem must be ext4 or XFS"
            )
        if mount.volume_id != contract.required_volume_id:
            raise UnsafeDatabaseStorage(
                "unsafe_storage", "database is not on the approved deployment volume"
            )
        _validate_linux_replacement_protection(
            canonical_path,
            canonical_root,
            administrator_uid=contract.administrator_uid,
            service_group_gid=contract.service_group_gid,
        )
        validate_linux_network_namespace()

    return ValidatedDatabaseStorage(
        database_path=canonical_path,
        approved_root=canonical_root,
        device=stat_result.st_dev,
        inode=stat_result.st_ino,
        root_device=root_stat.st_dev,
        root_inode=root_stat.st_ino,
        free_bytes=usage.free,
        free_percent=free_percent,
        filesystem=filesystem,
        volume_id=volume_id,
    )


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _linux_mount_for(path: Path) -> _LinuxMount:
    if platform.system() != "Linux":
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "production database storage requires the approved Linux host"
        )
    try:
        lines = LINUX_MOUNTINFO_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "Linux mount identity cannot be inspected"
        ) from error

    matches: list[_LinuxMount] = []
    for line in lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        after_fields = after.split()
        if len(fields) < 5 or not after_fields:
            continue
        mount_point = Path(_unescape_mount_field(fields[4])).resolve()
        try:
            path.relative_to(mount_point)
        except ValueError:
            continue
        matches.append(
            _LinuxMount(
                mount_point=mount_point,
                filesystem=after_fields[0].lower(),
                volume_id=fields[2],
            )
        )
    if not matches:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "database mount identity cannot be established"
        )
    return max(matches, key=lambda mount: len(mount.mount_point.parts))


def _unescape_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _validate_linux_replacement_protection(
    database_path: Path,
    approved_root: Path,
    *,
    administrator_uid: int,
    service_group_gid: int,
) -> None:
    get_effective_uid = getattr(os, "geteuid", None)
    if get_effective_uid is None:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "production replacement protection requires Linux user identities"
        )
    effective_uid = get_effective_uid()
    database_stat = database_path.stat()
    root_stat = approved_root.stat()
    if effective_uid == 0:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "the Butterbot production process must not run as root"
        )
    if administrator_uid < 0 or service_group_gid < 0:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "approved production UID and GID must be non-negative"
        )
    if database_stat.st_uid != administrator_uid or root_stat.st_uid != administrator_uid:
        raise UnsafeDatabaseStorage(
            "unsafe_storage",
            "database file and approved root must be owned by the approved administrator",
        )
    if database_stat.st_gid != service_group_gid or root_stat.st_gid != service_group_gid:
        raise UnsafeDatabaseStorage(
            "unsafe_storage",
            "database file and approved root must use the Butterbot service group",
        )
    if database_stat.st_uid == effective_uid or root_stat.st_uid == effective_uid:
        raise UnsafeDatabaseStorage(
            "unsafe_storage",
            "the service identity must not own the database file or approved root",
        )
    if stat.S_IMODE(root_stat.st_mode) != 0o1770:
        raise UnsafeDatabaseStorage("unsafe_storage", "the approved root must have exact mode 1770")
    if stat.S_IMODE(database_stat.st_mode) != 0o660:
        raise UnsafeDatabaseStorage("unsafe_storage", "the database file must have exact mode 0660")
    if not os.access(database_path, os.W_OK, effective_ids=True) or not os.access(
        approved_root, os.W_OK | os.X_OK, effective_ids=True
    ):
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "the service identity must be able to write SQLite and its sidecars"
        )
    if os.access(approved_root.parent, os.W_OK, effective_ids=True):
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "the service identity must not be able to replace the approved root"
        )
    if _linux_effective_capabilities() != 0:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "the service process must run without effective Linux capabilities"
        )


def _linux_effective_capabilities() -> int:
    try:
        status_lines = Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "Linux process capabilities cannot be inspected"
        ) from error
    for line in status_lines:
        label, separator, value = line.partition(":")
        if separator and label == "CapEff":
            try:
                return int(value.strip(), 16)
            except ValueError as error:
                raise UnsafeDatabaseStorage(
                    "unsafe_storage", "Linux effective capabilities are malformed"
                ) from error
    raise UnsafeDatabaseStorage("unsafe_storage", "Linux effective capabilities are unavailable")


def validate_linux_network_namespace() -> None:
    try:
        process_namespace = Path("/proc/self/ns/net").stat()
        init_namespace = Path("/proc/1/ns/net").stat()
    except OSError as error:
        raise UnsafeDatabaseStorage(
            "unsafe_storage", "Linux network namespace identity cannot be inspected"
        ) from error
    if (
        process_namespace.st_dev != init_namespace.st_dev
        or process_namespace.st_ino != init_namespace.st_ino
    ):
        raise UnsafeDatabaseStorage(
            "unsafe_storage",
            "production process ownership requires the deployment init network namespace",
        )


def fixed_process_lock_path(storage: ValidatedDatabaseStorage) -> Path:
    return storage.approved_root / ".butterbot-process.lock"


class DatabaseIdentityGuard:
    def __init__(self, storage: ValidatedDatabaseStorage) -> None:
        self._storage = storage
        self._on_failure: Callable[[str], None] | None = None

    def set_failure_callback(self, callback: Callable[[str], None]) -> None:
        self._on_failure = callback

    def mark_unsafe(self, error_category: str) -> None:
        callback = self._on_failure
        if callback is None:
            with suppress(BaseException):
                logger.critical(
                    "Database runtime became unsafe before a safety-state callback was "
                    "installed: %s",
                    error_category,
                )
            return
        try:
            callback(error_category)
        except BaseException:
            with suppress(BaseException):
                logger.exception(
                    "Database safety-state callback failed for category %s",
                    error_category,
                )

    def verify_path(self) -> None:
        try:
            if _contains_symlink(self._storage.database_path) or _contains_symlink(
                self._storage.approved_root
            ):
                self._fail("database path or approved root gained symlink traversal")
            database_path = self._storage.database_path.resolve(strict=True)
            approved_root = self._storage.approved_root.resolve(strict=True)
            database_stat = database_path.stat()
            root_stat = approved_root.stat()
            if (
                database_path != self._storage.database_path
                or approved_root != self._storage.approved_root
                or database_path.parent != approved_root
                or database_stat.st_dev != self._storage.device
                or database_stat.st_ino != self._storage.inode
                or database_stat.st_nlink != 1
                or root_stat.st_dev != self._storage.root_device
                or root_stat.st_ino != self._storage.root_inode
            ):
                self._fail("database or approved-root device/inode identity changed")
        except DatabaseIdentityMismatch:
            raise
        except OSError as error:
            self._fail("database identity could not be revalidated", cause=error)

    def verify_connection_path(self, connection_database_path: str) -> None:
        self.verify_path()
        try:
            connected_path = Path(connection_database_path).resolve(strict=True)
            connected_stat = connected_path.stat()
        except OSError as error:
            self._fail("checked-out connection database path is unreadable", cause=error)
        if (
            connected_path != self._storage.database_path
            or connected_stat.st_dev != self._storage.device
            or connected_stat.st_ino != self._storage.inode
        ):
            self._fail("checked-out connection does not match the approved database identity")

    def _fail(self, message: str, *, cause: OSError | None = None) -> NoReturn:
        self.mark_unsafe("database_identity_mismatch")
        error = DatabaseIdentityMismatch(message)
        if cause is None:
            raise error
        raise error from cause


def identity_unchanged(storage: ValidatedDatabaseStorage) -> bool:
    try:
        current = storage.database_path.stat()
        current_root = storage.approved_root.stat()
    except OSError:
        return False
    return (
        current.st_dev == storage.device
        and current.st_ino == storage.inode
        and current.st_nlink == 1
        and current_root.st_dev == storage.root_device
        and current_root.st_ino == storage.root_inode
        and not _contains_symlink(storage.database_path)
        and not _contains_symlink(storage.approved_root)
    )


__all__ = [
    "DatabaseStorageContract",
    "DatabaseIdentityGuard",
    "DatabaseIdentityMismatch",
    "MINIMUM_FREE_BYTES",
    "MINIMUM_FREE_PERCENT",
    "UnsafeDatabaseStorage",
    "ValidatedDatabaseStorage",
    "fixed_process_lock_path",
    "identity_unchanged",
    "validate_linux_network_namespace",
    "validate_database_storage",
]
