from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as element_tree
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).parents[1]
# Release-bound inventory. Parameterized phases are separate mandatory outcomes.
NATIVE_TEST_NODES = (
    (
        "tests/test_native_linux_gate.py::"
        "test_native_service_identity_accepts_exact_production_storage"
    ),
    (
        "tests/test_native_linux_gate.py::"
        "test_native_group_membership_controls_database_and_directory_access"
    ),
    "tests/test_native_linux_gate.py::test_native_sticky_root_blocks_service_database_replacement",
    "tests/test_native_linux_gate.py::test_native_symlink_and_hardlink_aliases_are_rejected",
    "tests/test_native_linux_gate.py::test_native_unexpected_effective_capability_is_rejected",
    "tests/test_native_linux_gate.py::test_native_abstract_socket_lock_excludes_other_identity",
    "tests/test_native_linux_gate.py::test_native_separate_network_namespace_is_rejected",
    (
        "tests/test_process_lock_linux.py::"
        "test_linux_process_ownership_survives_lock_path_unlink_and_recreate"
    ),
    (
        "tests/test_process_lock_linux.py::"
        "test_linux_process_ownership_survives_root_rename_and_recreation"
    ),
    (
        "tests/test_process_lock_linux.py::"
        "test_linux_database_replacement_during_active_transaction_fails_before_commit"
    ),
    (
        "tests/test_process_lock_linux.py::"
        "test_linux_approved_root_replacement_during_active_transaction_fails_before_commit"
    ),
    (
        "tests/test_process_lock_linux.py::"
        "test_linux_process_ownership_requires_deployment_init_network_namespace"
    ),
    (
        "tests/test_sigterm_linux.py::"
        "test_native_sigterm_drains_transactions_and_releases_process_lock[active]"
    ),
    (
        "tests/test_sigterm_linux.py::"
        "test_native_sigterm_drains_transactions_and_releases_process_lock[waiting]"
    ),
    (
        "tests/test_sigterm_linux.py::"
        "test_native_sigterm_drains_transactions_and_releases_process_lock[committing]"
    ),
    (
        "tests/test_sigterm_linux.py::"
        "test_native_sigterm_fail_stops_while_transaction_owner_is_unresolved"
    ),
)
REQUIRED_JUNIT_CASES = frozenset(
    node.replace(".py::", "::").replace("/", ".") for node in NATIVE_TEST_NODES
)
CAPABILITY_CASE = (
    "tests.test_native_linux_gate::test_native_unexpected_effective_capability_is_rejected"
)
NAMESPACE_CASE = "tests.test_native_linux_gate::test_native_separate_network_namespace_is_rejected"
NAMESPACE_SKIP_REASON = (
    "kernel/host denies unshare --net (EPERM/EACCES); "
    "production must keep PrivateNetwork=false and share init netns"
)


def _allowed_skip(test: str, reason: str) -> bool:
    return test == NAMESPACE_CASE and reason == NAMESPACE_SKIP_REASON


def namespace_host_denied(result: subprocess.CompletedProcess[str]) -> bool:
    """Accept only util-linux's C-locale denial before the child started."""
    return (
        result.returncode == 1
        and result.stdout == ""
        and result.stderr.rstrip("\n")
        in {
            "unshare: unshare failed: Operation not permitted",
            "unshare: unshare failed: Permission denied",
        }
    )


def _optional_posix_call(name: str) -> Callable[[], Any] | None:
    return cast("Callable[[], Any] | None", os.__dict__.get(name))


def _capability_state() -> str | None:
    try:
        lines = Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return next(
        (line.partition(":")[2].strip() for line in lines if line.startswith("CapEff:")), None
    )


def _namespace_identity(path: str) -> list[int] | None:
    try:
        observed = Path(path).stat()
    except OSError:
        return None
    return [observed.st_dev, observed.st_ino]


def _parse_junit(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    outcomes: dict[str, str] = {}
    skipped_tests: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    try:
        root = element_tree.parse(path).getroot()
        if root.tag == "testsuite":
            suites = [root]
        elif root.tag == "testsuites" and all(node.tag == "testsuite" for node in root):
            suites = list(root)
        else:
            raise ValueError("unexpected JUnit root/children")
        if not suites:
            raise ValueError("empty JUnit results")
        for suite in suites:
            suite_counts: Counter[str] = Counter()
            for case in suite:
                if case.tag in {"properties", "system-out", "system-err"}:
                    continue
                if case.tag != "testcase":
                    raise ValueError("unexpected JUnit suite child")
                name = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
                if name in outcomes:
                    errors.append(f"duplicate testcase: {name}")
                status = [
                    child.tag for child in case if child.tag in {"failure", "error", "skipped"}
                ]
                if len(status) > 1 or any(
                    child.tag
                    not in {"failure", "error", "skipped", "properties", "system-out", "system-err"}
                    for child in case
                ):
                    raise ValueError("ambiguous/unknown testcase outcome")
                outcome = status[0] if status else "passed"
                outcomes[name] = outcome
                counts[outcome] += 1
                suite_counts[outcome] += 1
                if outcome == "skipped":
                    skip = case.find("skipped")
                    assert skip is not None
                    skipped_tests.append({"test": name, "reason": skip.attrib.get("message", "")})
            expected_counts = {
                "tests": sum(suite_counts.values()),
                "failures": suite_counts["failure"],
                "errors": suite_counts["error"],
                "skipped": suite_counts["skipped"],
            }
            for key, value in expected_counts.items():
                if int(suite.attrib.get(key, "-1")) != value:
                    errors.append(f"inconsistent JUnit {key} count")
    except (OSError, element_tree.ParseError, ValueError) as error:
        errors.append(f"invalid JUnit: {error}")
    missing = sorted(REQUIRED_JUNIT_CASES - outcomes.keys())
    unexpected = sorted(outcomes.keys() - REQUIRED_JUNIT_CASES)
    if missing:
        errors.append("required testcases missing")
    if unexpected:
        errors.append("unexpected testcases collected")
    unexpected_skips = [
        item for item in skipped_tests if not _allowed_skip(item["test"], item["reason"])
    ]
    failed = counts["failure"] + counts["error"]
    return {
        "capability_test_passed": outcomes.get(CAPABILITY_CASE) == "passed",
        "required_test_accounting_passed": not errors and not unexpected_skips and failed == 0,
        "required_test_outcomes": outcomes,
        "missing_tests": missing,
        "unexpected_tests": unexpected,
        "report_errors": errors,
        "total_tests_collected": sum(counts.values()),
        "tests_run": counts["passed"] + failed,
        "tests_passed": counts["passed"],
        "tests_failed": failed,
        "tests_skipped": counts["skipped"],
        "skipped_tests": skipped_tests,
        "unexpected_skipped_tests": unexpected_skips,
    }


def _source_identity() -> dict[str, Any]:
    files: dict[str, str] = {}
    for directory in ("src", "tests", "migrations", "benchmarks"):
        for path in sorted((REPOSITORY_ROOT / directory).rglob("*.py")):
            files[path.relative_to(REPOSITORY_ROOT).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    for name in ("pyproject.toml", "alembic.ini", "tests/baseline_schema_snapshot.json"):
        files[name] = hashlib.sha256((REPOSITORY_ROOT / name).read_bytes()).hexdigest()
    serialized = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()

    def git(*arguments: str) -> str:
        return subprocess.check_output(
            ["git", *arguments], cwd=REPOSITORY_ROOT, text=True, timeout=10
        ).strip()

    return {
        "git_head": git("rev-parse", "HEAD"),
        "git_status": git("status", "--short"),
        "source_sha256": hashlib.sha256(serialized).hexdigest(),
        "files": files,
    }


def _pytest_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(REPOSITORY_ROOT / "src"), str(REPOSITORY_ROOT))
    )
    environment["LC_ALL"] = "C"
    return environment


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the genuine Butterbot native-Linux gate.")
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--service-uid", type=int, default=61001)
    parser.add_argument("--service-gid", type=int, default=61002)
    parser.add_argument("--administrator-uid", type=int, default=0)
    args = parser.parse_args(argv)
    get_uid = _optional_posix_call("geteuid")
    get_gid = _optional_posix_call("getegid")
    get_groups = _optional_posix_call("getgroups")
    report: dict[str, Any] = {
        "gate": "butterbot_slice_1_0_native_linux_kernel",
        "mocked_unit_tests_counted_as_kernel_proof": False,
        "selected_tests": list(NATIVE_TEST_NODES),
        "host": {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "kernel": platform.release(),
            "machine": platform.machine(),
            "controller_uid": get_uid() if get_uid else None,
            "controller_gid": get_gid() if get_gid else None,
            "controller_groups": get_groups() if get_groups else None,
            "controller_cap_eff": _capability_state(),
            "controller_net_namespace": _namespace_identity("/proc/self/ns/net"),
            "init_net_namespace": _namespace_identity("/proc/1/ns/net"),
            "configured_parent": str(args.parent.resolve()),
            "configured_service_uid": args.service_uid,
            "configured_service_gid": args.service_gid,
            "configured_administrator_uid": args.administrator_uid,
        },
    }
    errors: list[str] = []
    if (
        platform.system() != "Linux"
        or "microsoft" in platform.release().lower()
        or any(os.getenv(key) for key in ("WSL_INTEROP", "WSL_DISTRO_NAME"))
    ):
        errors.append("gate requires native Linux, not Windows/WSL")
    if sys.version_info[:2] != (3, 13):
        errors.append("gate requires Python 3.13")
    if get_uid is None or get_uid() != 0:
        errors.append("gate controller must run as root")
    if not args.parent.is_absolute() or not args.parent.is_dir():
        errors.append("--parent must be an existing absolute directory")
    if errors:
        report.update(preflight_errors=errors, result="not_run")
        _write_report(args.report, report)
        return 2

    report_path = cast("Path", args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts = Path(
        tempfile.mkdtemp(prefix=report_path.stem + "-", dir=report_path.parent)
    ).resolve()
    report["artifacts_directory"] = str(artifacts)
    junit = artifacts / "junit.xml"
    layout = artifacts / "layout.json"
    environment = _pytest_environment()
    environment.update(
        {
            "BUTTERBOT_NATIVE_GATE_PARENT": str(args.parent.resolve()),
            "BUTTERBOT_NATIVE_SERVICE_UID": str(args.service_uid),
            "BUTTERBOT_NATIVE_SERVICE_GID": str(args.service_gid),
            "BUTTERBOT_NATIVE_ADMIN_UID": str(args.administrator_uid),
            "BUTTERBOT_NATIVE_GATE_EVIDENCE": str(layout),
        }
    )
    command_line = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "pytest_asyncio.plugin",
        "-o",
        "addopts=",
        "-o",
        "junit_family=xunit2",
        "-m",
        "native_linux_kernel",
        "-ra",
        f"--junitxml={junit}",
        *NATIVE_TEST_NODES,
    ]
    report["command"] = command_line
    try:
        report["source_before"] = _source_identity()
        report["host"]["distro"] = platform.freedesktop_os_release()
        report["dependencies"] = {
            name: importlib.metadata.version(name)
            for name in (
                "pytest",
                "pytest-asyncio",
                "sqlalchemy",
                "aiosqlite",
                "alembic",
            )
        }
        completed = subprocess.run(
            command_line,
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        (artifacts / "pytest.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (artifacts / "pytest.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        report["pytest_exit_code"] = completed.returncode
        report.update(_parse_junit(junit))
        report["tested_storage_contract"] = json.loads(layout.read_text(encoding="utf-8"))
        if (
            not isinstance(report["tested_storage_contract"], dict)
            or not report["tested_storage_contract"]
        ):
            raise ValueError("missing native storage evidence")
        report["source_after"] = _source_identity()
        source_unchanged = (
            report["source_before"]["source_sha256"] == report["source_after"]["source_sha256"]
        )
        report["source_unchanged"] = source_unchanged
        report["result"] = (
            "passed"
            if completed.returncode == 0
            and report["required_test_accounting_passed"] is True
            and source_unchanged
            else "failed"
        )
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        importlib.metadata.PackageNotFoundError,
    ) as error:
        report.update(result="failed", report_error=str(error))
        if isinstance(error, subprocess.TimeoutExpired):
            (artifacts / "pytest.stdout.txt").write_text(str(error.stdout or ""), encoding="utf-8")
            (artifacts / "pytest.stderr.txt").write_text(str(error.stderr or ""), encoding="utf-8")
    _write_report(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
