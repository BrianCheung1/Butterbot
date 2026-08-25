import logging
from collections.abc import Iterable

import discord
from discord.ext import commands

DEFAULT_EXTENSIONS = ("butterbot.discord_app.extensions.ping",)

logger = logging.getLogger(__name__)


class ButterBot(commands.Bot):
    def __init__(self, *, extensions: Iterable[str] = DEFAULT_EXTENSIONS) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self._startup_extensions = tuple(extensions)

    async def setup_hook(self) -> None:
        for extension in self._startup_extensions:
            await self.load_extension(extension)
            logger.info("Loaded extension %s", extension)
        synced_commands = await self.tree.sync()
        logger.info("Synchronized %d global application command(s)", len(synced_commands))

    async def on_ready(self) -> None:
        if self.user is not None:
            logger.info("Connected to Discord as %s (ID: %s)", self.user, self.user.id)


def create_bot(*, extensions: Iterable[str] = DEFAULT_EXTENSIONS) -> ButterBot:
    return ButterBot(extensions=extensions)
