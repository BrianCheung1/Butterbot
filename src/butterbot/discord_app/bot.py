import logging
from collections.abc import Iterable

import discord
from discord.ext import commands

from butterbot.application.economy.balance import BalanceUseCase
from butterbot.application.operations.idempotency import NullOperationsTelemetry
from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.players.join import JoinUseCase
from butterbot.application.safety.service import SafetyService

DEFAULT_EXTENSIONS = (
    "butterbot.discord_app.extensions.ping",
    "butterbot.discord_app.extensions.join",
    "butterbot.discord_app.extensions.balance",
    "butterbot.discord_app.extensions.safety",
)

logger = logging.getLogger(__name__)


class ButterBot(commands.Bot):
    def __init__(
        self,
        *,
        extensions: Iterable[str] = DEFAULT_EXTENSIONS,
        telemetry: OperationsTelemetry | None = None,
        join_service: JoinUseCase | None = None,
        balance_service: BalanceUseCase | None = None,
        safety_service: SafetyService | None = None,
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self._startup_extensions = tuple(extensions)
        self.operations_telemetry = telemetry or NullOperationsTelemetry()
        self.join_service = join_service
        self.balance_service = balance_service
        self.safety_service = safety_service

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
    join_service: JoinUseCase | None = None,
    balance_service: BalanceUseCase | None = None,
    safety_service: SafetyService | None = None,
) -> ButterBot:
    return ButterBot(
        extensions=extensions,
        telemetry=telemetry,
        join_service=join_service,
        balance_service=balance_service,
        safety_service=safety_service,
    )
