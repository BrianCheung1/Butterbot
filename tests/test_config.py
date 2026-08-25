import pytest

from butterbot.discord_app.config import ConfigurationError, load_settings


def test_load_settings_reads_token_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    settings = load_settings()

    assert settings.discord_token == "test-token"


@pytest.mark.parametrize("token", ["", "   ", "your-discord-bot-token"])
def test_load_settings_rejects_missing_or_placeholder_token(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", token)

    with pytest.raises(ConfigurationError, match="DISCORD_TOKEN is not configured"):
        load_settings()
