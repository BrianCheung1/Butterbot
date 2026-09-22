import logging
from time import perf_counter
from typing import Protocol, cast

import discord
from discord import app_commands
from discord.ext import commands

from butterbot.application.economy.balance import BalanceUseCase
from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.operations.telemetry import emit_operational_telemetry

logger = logging.getLogger(__name__)


class Balance(commands.Cog):
    def __init__(self, service: BalanceUseCase, telemetry: OperationsTelemetry) -> None:
        self._service = service
        self._telemetry = telemetry

    @app_commands.command(name="balance", description="Privately view your Butterbot wallet.")
    async def balance(self, interaction: discord.Interaction) -> None:
        started = perf_counter()
        outcome = "failed"
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await self._service.balance(discord_user_id=interaction.user.id)
                outcome = result.status
                if result.status == "available" and result.amount is not None:
                    message = f"Your wallet: {result.amount:,} coins."
                elif result.status == "unjoined":
                    message = "You haven't joined Butterbot yet. Use /join to create your wallet."
                elif result.status == "inactive":
                    message = "This player account is unavailable."
                else:
                    message = "Your wallet is unavailable. Please try again later."
            except Exception as error:
                logger.error("Balance query failed with %s", type(error).__name__)
                message = "Could not read your wallet. Please try again later."
            await interaction.followup.send(message, ephemeral=True)
        except BaseException:
            outcome = "failed"
            raise
        finally:
            emit_operational_telemetry(
                "discord.command_completed",
                lambda: self._telemetry.discord_command_completed(
                    command="balance",
                    outcome=outcome,
                    duration_ms=(perf_counter() - started) * 1_000,
                ),
            )


class _BalanceBot(Protocol):
    balance_service: BalanceUseCase | None
    operations_telemetry: OperationsTelemetry


async def setup(bot: commands.Bot) -> None:
    dependencies = cast("_BalanceBot", bot)
    if dependencies.balance_service is None:
        raise RuntimeError("balance application service was not composed")
    await bot.add_cog(Balance(dependencies.balance_service, dependencies.operations_telemetry))
