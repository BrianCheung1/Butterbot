import logging
from collections.abc import Iterable

import discord
from discord.ext import commands

from butterbot.application.operations.idempotency import NullOperationsTelemetry
from butterbot.application.operations.ports import OperationsTelemetry

DEFAULT_EXTENSIONS = ("butterbot.discord_app.extensions.ping",)

logger = logging.getLogger(__name__)


class ButterBot(commands.Bot):
    def __init__(
        self,
        *,
        extensions: Iterable[str] = DEFAULT_EXTENSIONS,
        telemetry: OperationsTelemetry | None = None,
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self._startup_extensions = tuple(extensions)
        self.operations_telemetry = telemetry or NullOperationsTelemetry()

    async def setup_hook(self) -> None:
        for extension in self._startup_extensions:
            await self.load_extension(extension)
            logger.info("Loaded extension %s", extension)
        synced_commands = await self.tree.sync()
        logger.info("Synchronized %d global application command(s)", len(synced_commands))

    async def on_ready(self) -> None:
        if self.user is not None:
            logger.info("Connected to Discord")


def create_bot(
    *,
    extensions: Iterable[str] = DEFAULT_EXTENSIONS,
    telemetry: OperationsTelemetry | None = None,
) -> ButterBot:
    return ButterBot(extensions=extensions, telemetry=telemetry)
