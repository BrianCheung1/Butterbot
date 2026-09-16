# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from benchmarks import native_linux_gate as gate


def write_junit(path: Path, outcomes: dict[str, str]) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root,
        "testsuite",
        {
            "tests": str(len(outcomes)),
            "failures": str(sum(value == "failure" for value in outcomes.values())),
            "errors": str(sum(value == "error" for value in outcomes.values())),
            "skipped": str(sum(value == "skipped" for value in outcomes.values())),
        },
    )
    for node, outcome in outcomes.items():
        classname, name = node.split("::")
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
        if outcome != "passed":
            ET.SubElement(case, outcome, message="unrelated reason")
    ET.ElementTree(root).write(path, encoding="unicode")


@pytest.mark.parametrize("node", sorted(gate.REQUIRED_JUNIT_CASES))
@pytest.mark.parametrize("outcome", ["passed", "failure", "error", "skipped", "missing"])
def test_every_required_native_case_must_be_present_and_pass(
    tmp_path: Path,
    node: str,
    outcome: str,
) -> None:
    outcomes = dict.fromkeys(gate.REQUIRED_JUNIT_CASES, "passed")
    if outcome == "missing":
        del outcomes[node]
    else:
        outcomes[node] = outcome
    path = tmp_path / "junit.xml"
    write_junit(path, outcomes)
    report = gate._parse_junit(path)
    assert report["required_test_accounting_passed"] is (outcome == "passed")
    if outcome == "missing":
        assert report["missing_tests"] == [node]


@pytest.mark.parametrize(
    "mutation",
    [
        "capability_only",
        "wrong_module",
        "duplicate",
        "counts",
        "empty",
        "invalid_xml",
        "unknown_status",
        "ambiguous_status",
        "nested_suite",
        "extra_case",
        "missing_counts",
    ],
)
def test_partial_or_malformed_junit_cannot_pass(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "junit.xml"
    outcomes = dict.fromkeys(gate.REQUIRED_JUNIT_CASES, "passed")
    if mutation == "capability_only":
        outcomes = {gate.CAPABILITY_CASE: "passed"}
    elif mutation == "wrong_module":
        del outcomes[gate.CAPABILITY_CASE]
        outcomes["unrelated::" + gate.CAPABILITY_CASE.split("::")[1]] = "passed"
    elif mutation == "extra_case":
        outcomes["unrelated::test_extra"] = "passed"
    write_junit(path, outcomes)
    root = ET.parse(path).getroot()
    suite = root[0]
    if mutation == "duplicate":
        suite.append(ET.fromstring(ET.tostring(suite[0])))
        suite.set("tests", str(len(suite)))
    elif mutation == "counts":
        suite.set("tests", "0")
    elif mutation == "missing_counts":
        suite.attrib.clear()
    elif mutation == "empty":
        suite.clear()
    elif mutation == "unknown_status":
        ET.SubElement(suite[0], "unknown")
    elif mutation == "ambiguous_status":
        ET.SubElement(suite[0], "failure")
        ET.SubElement(suite[0], "skipped")
    elif mutation == "nested_suite":
        ET.SubElement(suite, "testsuite")
    ET.ElementTree(root).write(path, encoding="unicode")
    if mutation == "invalid_xml":
        path.write_text("<broken")
    assert gate._parse_junit(path)["required_test_accounting_passed"] is False


@pytest.mark.parametrize(
    "reason",
    [
        gate.NAMESPACE_SKIP_REASON,
        gate.NAMESPACE_SKIP_REASON + "; unrelated",
        "unshare unavailable",
        "permission denied",
        "namespace not available",
    ],
)
def test_only_exact_namespace_skip_is_permitted(tmp_path: Path, reason: str) -> None:
    path = tmp_path / "junit.xml"
    outcomes = dict.fromkeys(gate.REQUIRED_JUNIT_CASES, "passed")
    outcomes[gate.NAMESPACE_CASE] = "skipped"
    write_junit(path, outcomes)
    root = ET.parse(path).getroot()
    skip = root.find(".//skipped")
    assert skip is not None
    skip.set("message", reason)
    ET.ElementTree(root).write(path, encoding="unicode")
    assert gate._parse_junit(path)["required_test_accounting_passed"] is (
        reason == gate.NAMESPACE_SKIP_REASON
    )


@pytest.mark.parametrize(
    ("code", "stdout", "stderr", "denied"),
    [
        (1, "", "unshare: unshare failed: Operation not permitted\n", True),
        (1, "", "unshare: unshare failed: Permission denied\n", True),
        (1, "", "Traceback: application import failed", False),
        (1, "", "unshare: unshare failed: Invalid argument\n", False),
        (127, "", "unshare: command not found", False),
        (
            1,
            "NAMESPACE_CHILD_STARTED\n",
            "unshare: unshare failed: Operation not permitted\n",
            False,
        ),
        (1, "", "unshare: unshare failed: Operation not permitted\nTraceback", False),
        (23, "NAMESPACE_CHILD_STARTED\nNAMESPACE_REJECTED\n", "", False),
    ],
)
def test_namespace_denial_requires_exact_pre_child_host_failure(
    code: int,
    stdout: str,
    stderr: str,
    denied: bool,
) -> None:
    assert (
        gate.namespace_host_denied(subprocess.CompletedProcess([], code, stdout, stderr)) is denied
    )


def test_pytest_environment_cannot_inherit_selection_or_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k capability")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted")
    environment = gate._pytest_environment()
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTEST_PLUGINS" not in environment
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert environment["LC_ALL"] == "C"


def test_native_inventory_matches_actual_marker_collection() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            "native_linux_kernel",
            "-o",
            "addopts=",
            "-p",
            "pytest_asyncio.plugin",
            "tests",
        ],
        cwd=gate.REPOSITORY_ROOT,
        env=gate._pytest_environment(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    nodes = {line.replace("\\", "/") for line in completed.stdout.splitlines() if "::test_" in line}
    assert nodes == set(gate.NATIVE_TEST_NODES)


@pytest.mark.parametrize(
    "scenario", ["passed", "missing", "malformed", "source_changed", "no_layout", "nonzero"]
)
def test_runner_preserves_evidence_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    monkeypatch.setattr(gate.platform, "system", lambda: "Linux")
    monkeypatch.setattr(gate.platform, "platform", lambda: "simulated Linux policy test")
    monkeypatch.setattr(gate.platform, "release", lambda: "6.0")
    monkeypatch.setattr(gate.platform, "freedesktop_os_release", lambda: {"ID": "policy-test"})

    def identity_function(name: str) -> Callable[[], int]:
        del name
        return lambda: 0

    monkeypatch.setattr(gate, "_optional_posix_call", identity_function)
    for key in ("WSL_INTEROP", "WSL_DISTRO_NAME"):
        monkeypatch.delenv(key, raising=False)
    source_calls = 0

    def source() -> dict[str, str]:
        nonlocal source_calls
        source_calls += 1
        return {"source_sha256": str(source_calls) if scenario == "source_changed" else "same"}

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        path = Path(
            next(value.split("=", 1)[1] for value in command if value.startswith("--junitxml="))
        )
        outcomes = dict.fromkeys(gate.REQUIRED_JUNIT_CASES, "passed")
        if scenario == "missing":
            outcomes = {gate.CAPABILITY_CASE: "passed"}
        write_junit(path, outcomes)
        if scenario == "malformed":
            path.write_text("<broken")
        if scenario != "no_layout":
            Path(kwargs["env"]["BUTTERBOT_NATIVE_GATE_EVIDENCE"]).write_text('{"fixture":true}')
        assert set(gate.NATIVE_TEST_NODES) <= set(command)
        assert "PYTEST_ADDOPTS" not in kwargs["env"]
        return subprocess.CompletedProcess(
            command, 1 if scenario == "nonzero" else 0, "raw stdout", "raw stderr"
        )

    monkeypatch.setattr(gate, "_source_identity", source)
    monkeypatch.setattr(gate.subprocess, "run", run)
    report_path = tmp_path / "report.json"
    result = gate.main(["--parent", str(tmp_path), "--report", str(report_path)])
    report = json.loads(report_path.read_text())
    assert result == (0 if scenario == "passed" else 1)
    assert report["result"] == ("passed" if scenario == "passed" else "failed")
    artifacts = Path(report["artifacts_directory"])
    assert (artifacts / "junit.xml").exists()
    assert (artifacts / "pytest.stdout.txt").read_text() == "raw stdout"
    assert (artifacts / "pytest.stderr.txt").read_text() == "raw stderr"


def test_windows_cannot_emit_native_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate.platform, "system", lambda: "Windows")
    path = tmp_path / "not-run.json"
    assert gate.main(["--parent", str(tmp_path), "--report", str(path)]) == 2
    assert json.loads(path.read_text())["result"] == "not_run"
