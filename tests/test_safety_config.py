from pathlib import Path

import pytest

from butterbot.application.safety.service import SafetyPolicy
from butterbot.discord_app.config import ConfigurationError
from butterbot.discord_app.safety_bootstrap import bootstrap_local
from butterbot.discord_app.safety_config import load_development_operators, load_safety_policy

POLICY_NAMES = (
    "BUTTERBOT_SAFETY_APPROVAL_THRESHOLD",
    "BUTTERBOT_SAFETY_OPERATION_CEILING",
    "BUTTERBOT_SAFETY_24H_CEILING",
    "BUTTERBOT_SAFETY_ALERT_DESTINATION",
)


@pytest.fixture(autouse=True)
def isolated_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*POLICY_NAMES, "BUTTERBOT_DEV_SAFETY_BOOTSTRAP_IDS"):
        monkeypatch.delenv(name, raising=False)


def test_missing_policy_is_unconfigured() -> None:
    assert load_safety_policy() is None
    assert load_development_operators() == ()


@pytest.mark.parametrize(
    "values", [("100", "1000", "10000", "local_log"), ("0", "1", "1", "local_log")]
)
def test_explicit_local_policy_loads(
    values: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in zip(POLICY_NAMES, values, strict=True):
        monkeypatch.setenv(name, value)
    assert load_safety_policy() == SafetyPolicy(*(int(v) for v in values[:3]))


@pytest.mark.parametrize(
    "values",
    [
        ("100", "", "10000", "local_log"),
        ("1001", "1000", "10000", "local_log"),
        ("100", "1000", "999", "local_log"),
        ("100", "1000", "10000", "discord"),
        ("-1", "1", "1", "local_log"),
        ("１", "1", "1", "local_log"),
        ("0", "1", str(2**63), "local_log"),
    ],
)
def test_invalid_or_partial_policy_fails(
    values: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in zip(POLICY_NAMES, values, strict=True):
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError):
        load_safety_policy()


@pytest.mark.parametrize("value", ["0", "1,1", "-1", "123,", "1, 2", "１２３", str(2**63)])
def test_bootstrap_operator_input_is_explicit_and_bounded(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUTTERBOT_DEV_SAFETY_BOOTSTRAP_IDS", value)
    with pytest.raises(ConfigurationError):
        load_development_operators()


async def test_local_bootstrap_refuses_arbitrary_storage_before_open(tmp_path: Path) -> None:
    path = tmp_path / "not-opened.sqlite3"
    with pytest.raises(ValueError, match="disposable"):
        await bootstrap_local(path, (111,), SafetyPolicy(1, 10, 100))
    assert not path.exists()
