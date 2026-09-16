from pathlib import Path

import pytest

from butterbot.discord_app.config import ConfigurationError, load_settings


@pytest.fixture(autouse=True)
def release_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUTTERBOT_RELEASE_ID", "test-build")


def test_load_settings_reads_token_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.delenv("BUTTERBOT_DATABASE_VOLUME_ID", raising=False)
    monkeypatch.delenv("BUTTERBOT_DATABASE_ADMINISTRATOR_UID", raising=False)
    monkeypatch.delenv("BUTTERBOT_DATABASE_SERVICE_GROUP_GID", raising=False)
    monkeypatch.delenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", raising=False)

    settings = load_settings()

    assert settings.discord_token == "test-token"
    assert settings.release_id == "test-build"
    assert settings.database_path == Path.cwd() / "test.sqlite3"
    assert settings.database_root == Path.cwd()
    assert settings.database_volume_id is None
    assert settings.database_administrator_uid is None
    assert settings.database_service_group_gid is None
    assert settings.economy_mutations_enabled is False


@pytest.mark.parametrize("token", ["", "   ", "your-discord-bot-token"])
def test_load_settings_rejects_missing_or_placeholder_token(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", token)
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))

    with pytest.raises(ConfigurationError, match="DISCORD_TOKEN is not configured"):
        load_settings()


@pytest.mark.parametrize("release", ["", " ", "bad release", ".leading", "x" * 101])
def test_load_settings_rejects_missing_or_malformed_release_identity(
    monkeypatch: pytest.MonkeyPatch, release: str
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_RELEASE_ID", release)
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))

    with pytest.raises(ConfigurationError, match="BUTTERBOT_RELEASE_ID"):
        load_settings()


def test_load_settings_requires_absolute_database_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", "relative.sqlite3")
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))

    with pytest.raises(ConfigurationError, match="must be an absolute path"):
        load_settings()


def test_load_settings_requires_absolute_database_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", "relative-data")

    with pytest.raises(ConfigurationError, match="DATABASE_ROOT must be an absolute path"):
        load_settings()


@pytest.mark.parametrize("value", ["TRUE", "1", "yes", " false "])
def test_load_settings_strictly_parses_mutation_switch(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", value)

    with pytest.raises(ConfigurationError, match="must be exactly 'true' or 'false'"):
        load_settings()


@pytest.mark.parametrize(("value", "expected"), [("false", False)])
def test_load_settings_accepts_explicit_mutation_switch(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", value)
    assert load_settings().economy_mutations_enabled is expected


def test_load_settings_requires_approved_storage_for_enabled_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", "true")
    monkeypatch.delenv("BUTTERBOT_DATABASE_VOLUME_ID", raising=False)

    with pytest.raises(ConfigurationError, match="approved production database path"):
        load_settings()


def test_load_settings_rejects_enabled_mutations_on_unapproved_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BUTTERBOT_DATABASE_VOLUME_ID", "8:1")
    monkeypatch.setenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", "true")

    with pytest.raises(ConfigurationError, match="approved production database path"):
        load_settings()


def test_load_settings_requires_reviewed_owner_and_group_with_production_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BUTTERBOT_DATABASE_VOLUME_ID", "8:1")
    monkeypatch.setenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", "false")
    monkeypatch.delenv("BUTTERBOT_DATABASE_ADMINISTRATOR_UID", raising=False)
    monkeypatch.delenv("BUTTERBOT_DATABASE_SERVICE_GROUP_GID", raising=False)

    with pytest.raises(ConfigurationError, match="ADMINISTRATOR_UID"):
        load_settings()


@pytest.mark.parametrize("value", ["-1", "+1", "1.0", "admin"])
def test_load_settings_rejects_malformed_storage_identity(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ADMINISTRATOR_UID", value)

    with pytest.raises(ConfigurationError, match="non-negative decimal integer"):
        load_settings()


def test_load_settings_accepts_reviewed_owner_and_group_for_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(Path.cwd() / "test.sqlite3"))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(Path.cwd()))
    monkeypatch.setenv("BUTTERBOT_DATABASE_VOLUME_ID", "8:1")
    monkeypatch.setenv("BUTTERBOT_DATABASE_ADMINISTRATOR_UID", "0")
    monkeypatch.setenv("BUTTERBOT_DATABASE_SERVICE_GROUP_GID", "1002")
    monkeypatch.setenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", "false")

    settings = load_settings()
    assert settings.database_administrator_uid == 0
    assert settings.database_service_group_gid == 1002
