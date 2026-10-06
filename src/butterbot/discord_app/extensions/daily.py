import logging
from time import perf_counter
from typing import Protocol, cast

import discord
from discord import app_commands
from discord.ext import commands

from butterbot.application.economy.daily import DAILY_COINS, DAY_MS, DailyResult, DailyUseCase
from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.operations.telemetry import emit_operational_telemetry

logger = logging.getLogger(__name__)


def message(result: DailyResult) -> str:
    reset = (result.period + 1) * DAY_MS // 1000
    if result.status == "claimed":
        return (
            f"Daily reward: +{DAILY_COINS} coins. Balance after this claim: {result.balance}."
            f"\nReference: `{result.transaction_id}`\nNext daily reset: <t:{reset}:f>."
        )
    if result.status == "available":
        return (
            f"Your {DAILY_COINS}-coin daily reward is available. Use /daily claim."
            f"\nResets <t:{reset}:f> (midnight UTC). No streak bonus or catch-up."
        )
    if result.status == "already_claimed":
        return f"You already claimed this day's reward. Next reset: <t:{reset}:f>."
    return {
        "unjoined": "Use /join before claiming your daily reward.",
        "inactive": "This player account cannot claim daily rewards.",
        "disabled": "Daily claims are currently unavailable.",
        "expired": "The UTC day changed. Please run /daily claim again.",
        "unavailable": "Your wallet is unavailable. Please contact an operator.",
    }[result.status]


class Daily(commands.Cog):
    daily = app_commands.Group(name="daily", description="Inspect or claim your daily reward.")

    def __init__(self, service: DailyUseCase, telemetry: OperationsTelemetry) -> None:
        self._service = service
        self._telemetry = telemetry

    @daily.command(name="status", description="Check your daily reward and next UTC reset.")
    async def status(self, interaction: discord.Interaction) -> None:
        await self._respond(interaction, claim=False)

    @daily.command(name="claim", description="Claim 15 coins once per UTC calendar day.")
    async def claim(self, interaction: discord.Interaction) -> None:
        await self._respond(interaction, claim=True)

    async def _respond(self, interaction: discord.Interaction, *, claim: bool) -> None:
        started = perf_counter()
        outcome = "failed"
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                if claim:
                    # Snowflake time is immutable request intent, never a user-supplied option.
                    period = ((interaction.id >> 22) + 1420070400000) // DAY_MS
                    result = await self._service.claim(
                        discord_user_id=interaction.user.id,
                        interaction_id=interaction.id,
                        claim_period=period,
                    )
                else:
                    result = await self._service.inspect(discord_user_id=interaction.user.id)
                response = message(result)
                outcome = "replay" if result.replayed else result.status
            except Exception as error:
                logger.error("Daily failed with %s", type(error).__name__)
                response = (
                    "Could not confirm your daily reward. "
                    "Check /daily status or try /daily claim again."
                )
            await interaction.followup.send(response, ephemeral=True)
        except BaseException:
            outcome = "failed"
            raise
        finally:
            emit_operational_telemetry(
                "discord.command_completed",
                lambda: self._telemetry.discord_command_completed(
                    command="daily.claim" if claim else "daily.status",
                    outcome=outcome,
                    duration_ms=(perf_counter() - started) * 1000,
                ),
            )


class _DailyBot(Protocol):
    daily_service: DailyUseCase | None
    operations_telemetry: OperationsTelemetry


async def setup(bot: commands.Bot) -> None:
    dependencies = cast("_DailyBot", bot)
    if dependencies.daily_service is None:
        raise RuntimeError("daily application service was not composed")
    await bot.add_cog(Daily(dependencies.daily_service, dependencies.operations_telemetry))
