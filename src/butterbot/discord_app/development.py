"""Explicit, disposable, single-server/user launcher for interactive join testing."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import time_ns
from typing import Protocol, cast
from uuid import uuid4

import discord
from alembic import command
from alembic.config import Config
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from sqlalchemy import URL

from butterbot.application.exact_integer import INT64_MAX
from butterbot.application.operations.idempotency import (
    TransportIdempotencyCoordinator,
    discord_retention_registry,
)
from butterbot.application.operations.mutation_eligibility import GlobalMutationEligibility
from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.players.join import JOIN_NAMESPACE, JoinService, JoinUseCase
from butterbot.application.transactions import ApplicationTransactionRunner
from butterbot.discord_app.config import ConfigurationError
from butterbot.discord_app.startup import configure_logging, serve_until_shutdown
from butterbot.infrastructure.persistence.database import create_database_runtime, is_sqlite_busy
from butterbot.infrastructure.persistence.readiness import DatabaseReadinessError
from butterbot.infrastructure.telemetry import StructuredLoggingTelemetry

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DevelopmentSettings:
    discord_token: str = field(repr=False)
    guild_id: int
    user_id: int
    channel_id: int


def _discord_id(name: str) -> int:
    value = os.getenv(name, "").strip()
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= INT64_MAX:
        raise ConfigurationError(f"{name} must be a positive Discord ID.")
    return int(value)


def load_development_settings() -> DevelopmentSettings:
    load_dotenv(override=False)
    token = os.getenv("BUTTERBOT_DEV_DISCORD_TOKEN", "").strip()
    if not token or token in {"your-discord-bot-token", "replace-with-development-bot-token"}:
        raise ConfigurationError("BUTTERBOT_DEV_DISCORD_TOKEN is not configured.")
    if token == os.getenv("DISCORD_TOKEN", "").strip():
        raise ConfigurationError("Use a separate development bot token, not DISCORD_TOKEN.")
    return DevelopmentSettings(
        discord_token=token,
        guild_id=_discord_id("BUTTERBOT_DEV_GUILD_ID"),
        user_id=_discord_id("BUTTERBOT_DEV_USER_ID"),
        channel_id=_discord_id("BUTTERBOT_DEV_CHANNEL_ID"),
    )


class _DevelopmentScope(Protocol):
    development_guild_id: int
    development_user_id: int
    development_channel_id: int


class DevelopmentCommandTree(app_commands.CommandTree[commands.Bot]):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        scope = cast("_DevelopmentScope", self.client)
        if (
            interaction.guild_id != scope.development_guild_id
            or interaction.user.id != scope.development_user_id
            or interaction.channel_id != scope.development_channel_id
        ):
            await interaction.response.send_message(
                "This development bot is restricted to its configured tester, server, and channel.",
                ephemeral=True,
            )
            return False
        return True


class DevelopmentBot(commands.Bot):
    def __init__(
        self, settings: DevelopmentSettings, service: JoinUseCase, telemetry: OperationsTelemetry
    ) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            help_command=None,
            intents=discord.Intents.default(),
            tree_cls=DevelopmentCommandTree,
            activity=discord.Game("Disposable /join testing"),
        )
        self.development_guild_id = settings.guild_id
        self.development_user_id = settings.user_id
        self.development_channel_id = settings.channel_id
        self.join_service = service
        self.operations_telemetry = telemetry

    async def setup_hook(self) -> None:
        # Keep this explicit: future production extensions are not enabled automatically.
        await self.load_extension("butterbot.discord_app.extensions.ping")
        await self.load_extension("butterbot.discord_app.extensions.join")
        guild = discord.Object(id=self.development_guild_id)
        self.tree.copy_global_to(guild=guild)
        self.tree.clear_commands(guild=None)
        await self.tree.sync(guild=guild)
        logger.info("Development commands synchronized to the configured test server only")


def create_disposable_database() -> Path:
    """Allocate a new database; never consume a configured or caller-supplied data path."""
    parent = REPOSITORY_ROOT / "data" / "discord-development"
    # Reject symlink/junction redirection before creating anything below the checkout.
    if parent.resolve() != parent:
        raise ConfigurationError("Development storage must not traverse a symlink or junction.")
    parent.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="join-", dir=parent))
    database = session / "butterbot.sqlite3"
    config = Config()
    config.set_main_option(
        "script_location", str(REPOSITORY_ROOT / "migrations").replace("%", "%%")
    )
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(database))
        .render_as_string(hide_password=False)
        .replace("%", "%%"),
    )
    command.upgrade(config, "head")
    return database


async def run_development(settings: DevelopmentSettings) -> None:
    database_path = create_disposable_database()
    telemetry = StructuredLoggingTelemetry(release=f"development-{database_path.parent.name}")
    database = await create_database_runtime(
        database_path, telemetry=telemetry, configured_mutations_enabled=True
    )
    try:
        eligibility = GlobalMutationEligibility(
            configured_enabled=True, database_ready=True, runtime_safety=database.storage_monitor
        )
        service = JoinService(
            ApplicationTransactionRunner(
                database.unit_of_work_factory, is_retryable=is_sqlite_busy, telemetry=telemetry
            ),
            TransportIdempotencyCoordinator(
                discord_retention_registry(JOIN_NAMESPACE), telemetry=telemetry
            ),
            eligibility,
            clock_ms=lambda: time_ns() // 1_000_000,
            id_factory=uuid4,
        )
        logger.warning(
            "DISPOSABLE DEVELOPMENT SESSION %s: joins are enabled only for the configured tester; "
            "each launch starts empty. Not production or native acceptance evidence.",
            database_path.parent.name,
        )
        bot = DevelopmentBot(settings, service, telemetry)
        await serve_until_shutdown(bot, settings.discord_token)
    finally:
        await database.close()
        # Keep disposable files for diagnosis. A later launch always allocates a new directory.
        logger.info(
            "Development session stopped; disposable files retained under data/discord-development"
        )


def main() -> None:
    configure_logging(release="development-join")
    try:
        asyncio.run(run_development(load_development_settings()))
    except ConfigurationError as error:
        logger.error("Development configuration error: %s", error)
        raise SystemExit(2) from error
    except DatabaseReadinessError as error:
        logger.error("Development readiness error [%s]: %s", error.category, error)
        raise SystemExit(3) from error
    except KeyboardInterrupt:
        logger.info("Development shutdown requested")


if __name__ == "__main__":
    main()
