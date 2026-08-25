import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing."""


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str


def load_settings() -> Settings:
    """Load local development values without overriding the process environment."""
    load_dotenv(override=False)
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "your-discord-bot-token":
        raise ConfigurationError(
            "DISCORD_TOKEN is not configured. Copy .env.example to .env and set the token."
        )
    return Settings(discord_token=token)
