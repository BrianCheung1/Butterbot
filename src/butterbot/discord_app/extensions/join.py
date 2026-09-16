import logging
from time import perf_counter
from typing import Protocol, cast

import discord
from discord import app_commands
from discord.ext import commands

from butterbot.application.operations.idempotency import FingerprintConflict
from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.operations.telemetry import emit_operational_telemetry
from butterbot.application.players.join import JoinStatus, JoinUseCase

logger = logging.getLogger(__name__)

_MESSAGES: dict[JoinStatus, str] = {
    "created": "You joined Butterbot! Your wallet is ready.",
    "already_joined": "You have already joined Butterbot. Your existing wallet is ready.",
    "disabled": "Joining is currently unavailable. Please try again later.",
    "inactive": "This player account cannot join Butterbot.",
}


class Join(commands.Cog):
    def __init__(self, service: JoinUseCase, telemetry: OperationsTelemetry) -> None:
        self._service = service
        self._telemetry = telemetry

    @app_commands.command(name="join", description="Create your Butterbot player and wallet.")
    async def join(self, interaction: discord.Interaction) -> None:
        started = perf_counter()
        outcome = "failed"
        try:
            # Acknowledge privately before opening a transaction or waiting for a writer.
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await self._service.join(
                    discord_user_id=interaction.user.id, interaction_id=interaction.id
                )
                message = _MESSAGES[result.status]
                outcome = "replay" if result.replayed else result.status
            except FingerprintConflict:
                message = "This request could not be verified. Please run /join again."
                outcome = "conflict"
            except Exception as error:
                # Never log interaction keys, actor IDs, database URLs, or raw error text.
                logger.error("Join failed with %s", type(error).__name__)
                message = "Could not confirm your join. Please run /join again."
            await interaction.followup.send(message, ephemeral=True)
        except BaseException:
            outcome = "failed"
            raise
        finally:
            emit_operational_telemetry(
                "discord.command_completed",
                lambda: self._telemetry.discord_command_completed(
                    command="join", outcome=outcome, duration_ms=(perf_counter() - started) * 1_000
                ),
            )


class _JoinBot(Protocol):
    join_service: JoinUseCase | None
    operations_telemetry: OperationsTelemetry


async def setup(bot: commands.Bot) -> None:
    dependencies = cast("_JoinBot", bot)
    if dependencies.join_service is None:
        raise RuntimeError("join application service was not composed")
    await bot.add_cog(Join(dependencies.join_service, dependencies.operations_telemetry))
