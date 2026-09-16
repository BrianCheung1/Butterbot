from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from benchmarks.native_linux_gate import NAMESPACE_SKIP_REASON, namespace_host_denied
from sqlalchemy import URL

from butterbot.infrastructure.persistence.storage import SUPPORTED_PRODUCTION_FILESYSTEMS

pytestmark = [
    pytest.mark.skipif(sys.platform != "linux", reason="requires a native Linux kernel"),
    pytest.mark.native_linux_kernel,
]

REPOSITORY_ROOT = Path(__file__).parents[1]


def _effective_uid() -> int:
    function = cast("Callable[[], int] | None", os.__dict__.get("geteuid"))
    if function is None:
        raise RuntimeError("effective UID is unavailable")
    return function()


def _chown(path: Path, uid: int, gid: int) -> None:
    function = cast("Callable[[Path, int, int], None] | None", os.__dict__.get("chown"))
    if function is None:
        raise RuntimeError("chown is unavailable")
    function(path, uid, gid)


@dataclass(frozen=True, slots=True)
class NativeLayout:
    parent: Path
    approved_root: Path
    database: Path
    service_uid: int
    service_gid: int
    administrator_uid: int
    volume_id: str
    filesystem: str
    setpriv: str


def _mount_for(path: Path) -> tuple[str, str, str]:
    resolved = path.resolve(strict=True)
    matches: list[tuple[Path, str, str, str]] = []
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        after_fields = after.split()
        if len(fields) < 6 or not after_fields:
            continue
        mount_point = Path(fields[4].replace("\\040", " ")).resolve()
        try:
            resolved.relative_to(mount_point)
        except ValueError:
            continue
        matches.append((mount_point, fields[2], after_fields[0].lower(), line))
    if not matches:
        raise RuntimeError(f"no kernel mountinfo entry covers {resolved}")
    _, volume_id, filesystem, line = max(matches, key=lambda item: len(item[0].parts))
    return volume_id, filesystem, line


def _alembic_config(database: Path) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(database)).render_as_string(hide_password=False),
    )
    return config


def _setpriv_command(
    layout: NativeLayout,
    code: str,
    *arguments: str,
    uid: int | None = None,
    gid: int | None = None,
    capabilities: bool = False,
) -> list[str]:
    command_line = [
        layout.setpriv,
        f"--reuid={layout.service_uid if uid is None else uid}",
        f"--regid={layout.service_gid if gid is None else gid}",
        "--clear-groups",
    ]
    if capabilities:
        command_line.extend(
            [
                "--inh-caps=+net_raw",
                "--ambient-caps=+net_raw",
                "--bounding-set=+net_raw",
            ]
        )
    else:
        command_line.extend(["--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all"])
    command_line.extend([sys.executable, "-c", code, *arguments])
    return command_line


def _run_as_service(
    layout: NativeLayout,
    code: str,
    *arguments: str,
    uid: int | None = None,
    gid: int | None = None,
    capabilities: bool = False,
    timeout: float = 20,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _setpriv_command(
            layout,
            code,
            *arguments,
            uid=uid,
            gid=gid,
            capabilities=capabilities,
        ),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        cwd=REPOSITORY_ROOT,
    )


def _merge_native_evidence(section: str, value: object) -> None:
    evidence_path = os.getenv("BUTTERBOT_NATIVE_GATE_EVIDENCE")
    if not evidence_path:
        return
    path = Path(evidence_path)
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence[section] = value
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


@pytest.fixture(scope="session")
def native_layout() -> Iterator[NativeLayout]:
    if platform.system() != "Linux":
        pytest.skip("native gate requires Linux; mocked platform state is not accepted")
    if _effective_uid() != 0:
        pytest.skip(
            "native ownership gate must run as root to provision distinct numeric identities"
        )
    parent_text = os.getenv("BUTTERBOT_NATIVE_GATE_PARENT")
    if not parent_text:
        pytest.skip(
            "BUTTERBOT_NATIVE_GATE_PARENT must name a root-owned, service-nonwritable ext4/XFS path"
        )
    parent = Path(parent_text).resolve(strict=True)
    if not parent.is_dir():
        pytest.skip("BUTTERBOT_NATIVE_GATE_PARENT is not a directory")
    service_uid = int(os.getenv("BUTTERBOT_NATIVE_SERVICE_UID", "61001"))
    service_gid = int(os.getenv("BUTTERBOT_NATIVE_SERVICE_GID", "61002"))
    administrator_uid = int(os.getenv("BUTTERBOT_NATIVE_ADMIN_UID", "0"))
    if min(service_uid, service_gid) <= 0 or administrator_uid < 0:
        pytest.skip(
            "native gate UID/GID values must be distinct non-negative production identities"
        )
    if service_uid == administrator_uid:
        pytest.skip("service UID must differ from the administrator UID")
    setpriv = shutil.which("setpriv")
    if setpriv is None:
        pytest.skip("util-linux setpriv is required to execute the real service identity")
    parent_stat = parent.stat()
    if parent_stat.st_uid != administrator_uid:
        pytest.skip("native gate parent is not owned by the configured administrator UID")

    volume_id, filesystem, mountinfo_line = _mount_for(parent)
    if filesystem not in SUPPORTED_PRODUCTION_FILESYSTEMS:
        pytest.skip(
            f"native gate parent filesystem is {filesystem!r}; production requires ext4 or XFS"
        )

    approved_root = Path(tempfile.mkdtemp(prefix="butterbot-native-", dir=parent))
    database = approved_root / "butterbot.sqlite3"
    try:
        command.upgrade(_alembic_config(database), "head")
        _chown(approved_root, administrator_uid, service_gid)
        os.chmod(approved_root, 0o1770)
        for sqlite_path in (
            database,
            database.with_name(f"{database.name}-wal"),
            database.with_name(f"{database.name}-shm"),
        ):
            if sqlite_path.exists():
                _chown(sqlite_path, administrator_uid, service_gid)
                os.chmod(sqlite_path, 0o660)
        layout = NativeLayout(
            parent=parent,
            approved_root=approved_root,
            database=database,
            service_uid=service_uid,
            service_gid=service_gid,
            administrator_uid=administrator_uid,
            volume_id=volume_id,
            filesystem=filesystem,
            setpriv=setpriv,
        )
        evidence_path = os.getenv("BUTTERBOT_NATIVE_GATE_EVIDENCE")
        if evidence_path:
            Path(evidence_path).write_text(
                json.dumps(
                    {
                        "approved_root": str(approved_root),
                        "database": str(database),
                        "administrator_uid": administrator_uid,
                        "service_uid": service_uid,
                        "service_gid": service_gid,
                        "root_mode": oct(stat.S_IMODE(approved_root.stat().st_mode)),
                        "database_mode": oct(stat.S_IMODE(database.stat().st_mode)),
                        "root_owner": [approved_root.stat().st_uid, approved_root.stat().st_gid],
                        "database_owner": [database.stat().st_uid, database.stat().st_gid],
                        "volume_id": volume_id,
                        "filesystem": filesystem,
                        "mountinfo": mountinfo_line,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        yield layout
    finally:
        os.chmod(approved_root, 0o700)
        shutil.rmtree(approved_root, ignore_errors=True)


_RUNTIME_PROBE = r"""
import asyncio
import json
import os
import sys
from pathlib import Path
from butterbot.infrastructure.persistence.database import create_database_runtime
from butterbot.infrastructure.persistence.storage import DatabaseStorageContract

async def main():
    database = Path(sys.argv[1])
    contract = DatabaseStorageContract(
        database.parent,
        required_volume_id=sys.argv[2],
        administrator_uid=int(sys.argv[3]),
        service_group_gid=int(sys.argv[4]),
    )
    runtime = await create_database_runtime(database, storage_contract=contract)
    try:
        cap_eff = next(
            line.split(':', 1)[1].strip()
            for line in Path('/proc/self/status').read_text().splitlines()
            if line.startswith('CapEff:')
        )
        print(json.dumps({
            'uid': os.geteuid(),
            'gid': os.getegid(),
            'groups': os.getgroups(),
            'cap_eff': cap_eff,
            'filesystem': runtime.readiness.filesystem,
            'volume_id': runtime.readiness.volume_id,
            'revision': runtime.readiness.observed_revision,
            'net_namespace': [
                Path('/proc/self/ns/net').stat().st_dev,
                Path('/proc/self/ns/net').stat().st_ino,
            ],
            'init_net_namespace': [
                Path('/proc/1/ns/net').stat().st_dev,
                Path('/proc/1/ns/net').stat().st_ino,
            ],
        }, sort_keys=True))
    finally:
        await runtime.close(drain_timeout_seconds=0.2)

asyncio.run(main())
"""


def test_native_service_identity_accepts_exact_production_storage(
    native_layout: NativeLayout,
) -> None:
    result = _run_as_service(
        native_layout,
        _RUNTIME_PROBE,
        str(native_layout.database),
        native_layout.volume_id,
        str(native_layout.administrator_uid),
        str(native_layout.service_gid),
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence["uid"] == native_layout.service_uid
    assert evidence["gid"] == native_layout.service_gid
    assert evidence["cap_eff"] == "0000000000000000"
    assert evidence["filesystem"] == native_layout.filesystem
    assert evidence["volume_id"] == native_layout.volume_id
    assert evidence["net_namespace"] == evidence["init_net_namespace"]
    _merge_native_evidence("service_runtime", evidence)


_ACCESS_PROBE = r"""
import json
import os
import sys
from pathlib import Path

database = Path(sys.argv[1])
root = database.parent
write_error = None
try:
    with database.open('ab'):
        pass
except OSError as error:
    write_error = type(error).__name__
create_error = None
try:
    (root / 'group-access-probe').write_text('probe')
except OSError as error:
    create_error = type(error).__name__
print(json.dumps({
    'uid': os.geteuid(),
    'gid': os.getegid(),
    'database_write': write_error,
    'root_create': create_error,
}))
"""


def test_native_group_membership_controls_database_and_directory_access(
    native_layout: NativeLayout,
) -> None:
    member = _run_as_service(native_layout, _ACCESS_PROBE, str(native_layout.database))
    assert member.returncode == 0, member.stderr
    member_result = json.loads(member.stdout)
    assert member_result["database_write"] is None
    assert member_result["root_create"] is None

    outsider = _run_as_service(
        native_layout,
        _ACCESS_PROBE,
        str(native_layout.database),
        uid=native_layout.service_uid + 1,
        gid=native_layout.service_gid + 1,
    )
    assert outsider.returncode == 0, outsider.stderr
    outsider_result = json.loads(outsider.stdout)
    assert outsider_result["database_write"] == "PermissionError"
    assert outsider_result["root_create"] == "PermissionError"
    _merge_native_evidence(
        "group_access",
        {"service_group_member": member_result, "unrelated_identity": outsider_result},
    )


_REPLACEMENT_PROBE = r"""
import json
import os
import sys
from pathlib import Path

database = Path(sys.argv[1])
attacker = database.parent / 'service-owned-replacement'
attacker.write_text('replacement')
errors = {}
for operation in ('unlink', 'replace'):
    try:
        if operation == 'unlink':
            database.unlink()
        else:
            os.replace(attacker, database)
    except OSError as error:
        errors[operation] = type(error).__name__
print(json.dumps(errors, sort_keys=True))
"""


def test_native_sticky_root_blocks_service_database_replacement(
    native_layout: NativeLayout,
) -> None:
    result = _run_as_service(native_layout, _REPLACEMENT_PROBE, str(native_layout.database))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "replace": "PermissionError",
        "unlink": "PermissionError",
    }
    assert native_layout.database.is_file()


_VALIDATION_PROBE = r"""
import json
import sys
from pathlib import Path
from butterbot.infrastructure.persistence.storage import (
    DatabaseStorageContract,
    UnsafeDatabaseStorage,
    validate_database_storage,
)

database = Path(sys.argv[1])
try:
    validate_database_storage(
        database,
        DatabaseStorageContract(
            database.parent,
            required_volume_id=sys.argv[2],
            administrator_uid=int(sys.argv[3]),
            service_group_gid=int(sys.argv[4]),
        ),
    )
except UnsafeDatabaseStorage as error:
    print(json.dumps({'category': error.category, 'message': str(error)}))
    raise SystemExit(23)
raise SystemExit(0)
"""


def test_native_symlink_and_hardlink_aliases_are_rejected(native_layout: NativeLayout) -> None:
    hardlink = native_layout.approved_root / "database-hardlink"
    symlink = native_layout.approved_root / "database-symlink"
    os.link(native_layout.database, hardlink)
    os.symlink(native_layout.database, symlink)
    try:
        hardlink_result = _run_as_service(
            native_layout,
            _VALIDATION_PROBE,
            str(native_layout.database),
            native_layout.volume_id,
            str(native_layout.administrator_uid),
            str(native_layout.service_gid),
        )
        assert hardlink_result.returncode == 23, hardlink_result.stderr
        assert "hard-link" in hardlink_result.stdout

        symlink_result = _run_as_service(
            native_layout,
            _VALIDATION_PROBE,
            str(symlink),
            native_layout.volume_id,
            str(native_layout.administrator_uid),
            str(native_layout.service_gid),
        )
        assert symlink_result.returncode == 23, symlink_result.stderr
        assert "symlink" in symlink_result.stdout
    finally:
        hardlink.unlink()
        symlink.unlink()


def test_native_unexpected_effective_capability_is_rejected(
    native_layout: NativeLayout,
) -> None:
    result = _run_as_service(
        native_layout,
        _VALIDATION_PROBE,
        str(native_layout.database),
        native_layout.volume_id,
        str(native_layout.administrator_uid),
        str(native_layout.service_gid),
        capabilities=True,
    )
    if result.returncode not in {0, 23}:
        pytest.skip(
            "host cannot grant ambient CAP_NET_RAW to the numeric service identity: "
            f"{result.stderr.strip()}"
        )
    assert result.returncode == 23
    assert "without effective Linux capabilities" in result.stdout


_LOCK_OWNER_PROBE = r"""
import os
import sys
from pathlib import Path
from butterbot.infrastructure.persistence.process_lock import DatabaseProcessLock

lock = DatabaseProcessLock(Path(sys.argv[1]))
lock.acquire()
print(f'READY uid={os.geteuid()} gid={os.getegid()}', flush=True)
sys.stdin.readline()
lock.release()
"""


def test_native_abstract_socket_lock_excludes_other_identity(
    native_layout: NativeLayout,
) -> None:
    owner = subprocess.Popen(
        _setpriv_command(
            native_layout,
            _LOCK_OWNER_PROBE,
            str(native_layout.approved_root / ".butterbot-process.lock"),
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=REPOSITORY_ROOT,
    )
    try:
        assert owner.stdout is not None
        ready = owner.stdout.readline().strip()
        assert ready == f"READY uid={native_layout.service_uid} gid={native_layout.service_gid}"
        contender = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "from butterbot.infrastructure.persistence.process_lock import "
                "DatabaseProcessLock, ProcessLockUnavailable; "
                "lock=DatabaseProcessLock(Path('unused')); "
                "\ntry: lock.acquire()\nexcept ProcessLockUnavailable: raise SystemExit(23)",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPOSITORY_ROOT,
        )
        assert contender.returncode == 23, contender.stderr
    finally:
        if owner.stdin is not None:
            owner.stdin.close()
        owner.wait(timeout=5)


_NAMESPACE_PROBE = r"""
print('NAMESPACE_CHILD_STARTED', flush=True)
from butterbot.infrastructure.persistence.storage import (
    UnsafeDatabaseStorage,
    validate_linux_network_namespace,
)
try:
    validate_linux_network_namespace()
except UnsafeDatabaseStorage:
    print('NAMESPACE_REJECTED')
    raise SystemExit(23)
raise SystemExit(0)
"""


def test_native_separate_network_namespace_is_rejected(native_layout: NativeLayout) -> None:
    del native_layout
    unshare = shutil.which("unshare")
    if unshare is None:
        pytest.fail("util-linux unshare is required for namespace coverage")
    result = subprocess.run(
        [unshare, "--net", "--", sys.executable, "-c", _NAMESPACE_PROBE],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "LC_ALL": "C"},
    )
    if namespace_host_denied(result):
        pytest.skip(NAMESPACE_SKIP_REASON)
    assert result.returncode == 23, result.stderr
    assert result.stdout.splitlines() == ["NAMESPACE_CHILD_STARTED", "NAMESPACE_REJECTED"]
