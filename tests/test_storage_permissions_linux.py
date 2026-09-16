from __future__ import annotations

import os
import platform
from pathlib import Path
from types import SimpleNamespace

import pytest

from butterbot.infrastructure.persistence import storage as storage_module
from butterbot.infrastructure.persistence.storage import UnsafeDatabaseStorage

pytestmark = pytest.mark.skipif(
    platform.system() != "Linux",
    reason="production ownership and mode enforcement requires a native Linux gate host",
)

ADMINISTRATOR_UID = 0
SERVICE_UID = 1001
SERVICE_GROUP_GID = 1002


def _validate_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    database_uid: int = ADMINISTRATOR_UID,
    database_gid: int = SERVICE_GROUP_GID,
    database_mode: int = 0o660,
    root_uid: int = ADMINISTRATOR_UID,
    root_gid: int = SERVICE_GROUP_GID,
    root_mode: int = 0o1770,
    parent_writable: bool | int = False,
    capabilities: int = 0,
) -> None:
    database_path = tmp_path / "butterbot.sqlite3"
    approved_root = tmp_path
    real_stat = type(database_path).stat

    def fake_stat(path: Path, *args: object, **kwargs: object) -> os.stat_result | SimpleNamespace:
        if path == database_path:
            return SimpleNamespace(
                st_uid=database_uid,
                st_gid=database_gid,
                st_mode=database_mode,
            )
        if path == approved_root:
            return SimpleNamespace(st_uid=root_uid, st_gid=root_gid, st_mode=root_mode)
        return real_stat(path, *args, **kwargs)

    def fake_access(path: os.PathLike[str], mode: int, *, effective_ids: bool = False) -> bool:
        assert effective_ids is True
        candidate = Path(path)
        if candidate == database_path:
            return mode == os.W_OK
        if candidate == approved_root:
            return mode == os.W_OK | os.X_OK
        if candidate == approved_root.parent:
            return bool(parent_writable)
        return False

    monkeypatch.setattr(type(database_path), "stat", fake_stat)
    monkeypatch.setattr(storage_module.os, "geteuid", lambda: SERVICE_UID)
    monkeypatch.setattr(storage_module.os, "access", fake_access)
    monkeypatch.setattr(storage_module, "_linux_effective_capabilities", lambda: capabilities)
    storage_module._validate_linux_replacement_protection(  # pyright: ignore[reportPrivateUsage]
        database_path,
        approved_root,
        administrator_uid=ADMINISTRATOR_UID,
        service_group_gid=SERVICE_GROUP_GID,
    )


def test_linux_storage_accepts_administrator_owner_service_group_and_exact_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _validate_permissions(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"root_mode": 0o1777}, "root must have exact mode 1770"),
        ({"database_mode": 0o666}, "database file must have exact mode 0660"),
        ({"database_uid": 2000}, "owned by the approved administrator"),
        ({"root_uid": 2000}, "owned by the approved administrator"),
        ({"database_gid": 2000}, "must use the Butterbot service group"),
        ({"root_gid": 2000}, "must use the Butterbot service group"),
        ({"database_uid": SERVICE_UID}, "owned by the approved administrator"),
        ({"root_uid": SERVICE_UID}, "owned by the approved administrator"),
        ({"root_mode": 0o1771}, "root must have exact mode 1770"),
        ({"database_mode": 0o664}, "database file must have exact mode 0660"),
        ({"capabilities": 1}, "without effective Linux capabilities"),
    ],
)
def test_linux_storage_rejects_unsafe_ownership_modes_and_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(UnsafeDatabaseStorage, match=message):
        _validate_permissions(tmp_path, monkeypatch, **overrides)


def test_linux_storage_rejects_service_access_that_can_replace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(UnsafeDatabaseStorage, match="must not be able to replace"):
        _validate_permissions(tmp_path, monkeypatch, parent_writable=True)
