from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, cast


class ProcessLockUnavailable(RuntimeError):
    """Another bot process already owns the database writer lock."""


class DatabaseProcessLock:
    _LINUX_ABSTRACT_NAME = "\0butterbot-economy-writer-v1"

    def __init__(self, lock_path: Path) -> None:
        self.path = lock_path
        self._file: BinaryIO | None = None
        self._socket: socket.socket | None = None

    def acquire(self) -> None:
        if self._file is not None or self._socket is not None:
            return
        if sys.platform == "linux":
            self._acquire_linux_socket()
            return
        if self.path.is_symlink():
            raise ProcessLockUnavailable("database process-lock path must not be a symlink")
        flags: int = os.O_RDWR | os.O_CREAT | cast("int", getattr(os, "O_NOFOLLOW", 0))
        lock_file: BinaryIO | None = None
        try:
            descriptor = os.open(self.path, flags, 0o600)
            lock_file = os.fdopen(descriptor, "r+b")
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                if lock_file.read(1) == b"":
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, PermissionError) as error:
            if lock_file is not None:
                lock_file.close()
            raise ProcessLockUnavailable(
                "another Butterbot process owns the database lock"
            ) from error
        self._file = lock_file

    def _acquire_linux_socket(self) -> None:
        unix_family = cast("int", vars(socket)["AF_UNIX"])
        owner_socket = socket.socket(unix_family, socket.SOCK_DGRAM)
        try:
            owner_socket.bind(self._LINUX_ABSTRACT_NAME)
        except OSError as error:
            owner_socket.close()
            raise ProcessLockUnavailable(
                "another Butterbot process owns the Linux process socket"
            ) from error
        self._socket = owner_socket

    def release(self) -> None:
        owner_socket = self._socket
        if owner_socket is not None:
            owner_socket.close()
            self._socket = None
        lock_file = self._file
        if lock_file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
            self._file = None

    def __enter__(self) -> DatabaseProcessLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
