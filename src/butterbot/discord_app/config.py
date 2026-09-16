import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PRODUCTION_DATABASE_PATH = "/var/lib/butterbot/butterbot.sqlite3"
PRODUCTION_DATABASE_ROOT = "/var/lib/butterbot"


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing."""


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    release_id: str
    database_path: Path
    database_root: Path
    database_volume_id: str | None
    economy_mutations_enabled: bool
    database_administrator_uid: int | None = None
    database_service_group_gid: int | None = None


def _strict_bool(name: str, value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    if value == "true":
        return True
    if value == "false":
        return False
    raise ConfigurationError(f"{name} must be exactly 'true' or 'false'.")


def _optional_identity(name: str, value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    if not value.isascii() or not value.isdecimal():
        raise ConfigurationError(f"{name} must be a non-negative decimal integer.")
    return int(value)


def load_settings() -> Settings:
    """Load local development values without overriding the process environment."""
    load_dotenv(override=False)
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "your-discord-bot-token":
        raise ConfigurationError(
            "DISCORD_TOKEN is not configured. Copy .env.example to .env and set the token."
        )
    release_id = os.getenv("BUTTERBOT_RELEASE_ID", "").strip()
    if not release_id:
        raise ConfigurationError("BUTTERBOT_RELEASE_ID is not configured.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,99}", release_id):
        raise ConfigurationError(
            "BUTTERBOT_RELEASE_ID must be a 1-100 character immutable build identifier."
        )
    database_value = os.getenv("BUTTERBOT_DATABASE_PATH", "").strip()
    if not database_value:
        raise ConfigurationError("BUTTERBOT_DATABASE_PATH is not configured.")
    database_path = Path(database_value)
    if not database_path.is_absolute():
        raise ConfigurationError("BUTTERBOT_DATABASE_PATH must be an absolute path.")
    database_root_value = os.getenv("BUTTERBOT_DATABASE_ROOT", "").strip()
    if not database_root_value:
        raise ConfigurationError("BUTTERBOT_DATABASE_ROOT is not configured.")
    database_root = Path(database_root_value)
    if not database_root.is_absolute():
        raise ConfigurationError("BUTTERBOT_DATABASE_ROOT must be an absolute path.")
    mutations_enabled = _strict_bool(
        "BUTTERBOT_ECONOMY_MUTATIONS_ENABLED",
        os.getenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED"),
        default=False,
    )
    database_volume_id = os.getenv("BUTTERBOT_DATABASE_VOLUME_ID", "").strip() or None
    database_administrator_uid = _optional_identity(
        "BUTTERBOT_DATABASE_ADMINISTRATOR_UID",
        os.getenv("BUTTERBOT_DATABASE_ADMINISTRATOR_UID"),
    )
    database_service_group_gid = _optional_identity(
        "BUTTERBOT_DATABASE_SERVICE_GROUP_GID",
        os.getenv("BUTTERBOT_DATABASE_SERVICE_GROUP_GID"),
    )
    if mutations_enabled and (
        database_path.as_posix() != PRODUCTION_DATABASE_PATH
        or database_root.as_posix() != PRODUCTION_DATABASE_ROOT
    ):
        raise ConfigurationError(
            "enabled economy mutations require the approved production database path and root."
        )
    if mutations_enabled and database_volume_id is None:
        raise ConfigurationError(
            "BUTTERBOT_DATABASE_VOLUME_ID is required when economy mutations are enabled."
        )
    if database_volume_id is not None and (
        database_administrator_uid is None or database_service_group_gid is None
    ):
        raise ConfigurationError(
            "production database storage requires BUTTERBOT_DATABASE_ADMINISTRATOR_UID and "
            "BUTTERBOT_DATABASE_SERVICE_GROUP_GID."
        )
    return Settings(
        discord_token=token,
        release_id=release_id,
        database_path=database_path,
        database_root=database_root,
        database_volume_id=database_volume_id,
        economy_mutations_enabled=mutations_enabled,
        database_administrator_uid=database_administrator_uid,
        database_service_group_gid=database_service_group_gid,
    )
