from time import perf_counter
from typing import Protocol, cast

import discord
from discord import app_commands
from discord.ext import commands

from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.operations.telemetry import emit_operational_telemetry


class Ping(commands.Cog):
    def __init__(self, telemetry: OperationsTelemetry) -> None:
        self._telemetry = telemetry

    @app_commands.command(name="ping", description="Check whether Butterbot is running.")
    async def ping(self, interaction: discord.Interaction) -> None:
        started = perf_counter()
        outcome = "completed"
        try:
            await interaction.response.send_message("Pong!")
        except BaseException:
            outcome = "failed"
            raise
        finally:
            emit_operational_telemetry(
                "discord.command_completed",
                lambda: self._telemetry.discord_command_completed(
                    command="ping",
                    outcome=outcome,
                    duration_ms=(perf_counter() - started) * 1_000,
                ),
            )


class _TelemetryBot(Protocol):
    operations_telemetry: OperationsTelemetry


async def setup(bot: commands.Bot) -> None:
    telemetry = cast("_TelemetryBot", bot).operations_telemetry
    await bot.add_cog(Ping(telemetry))
