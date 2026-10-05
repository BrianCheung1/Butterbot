import logging
from time import perf_counter
from typing import Protocol, cast
from uuid import UUID

import discord
from discord import app_commands
from discord.ext import commands

from butterbot.application.economy.balance import BalanceUseCase
from butterbot.application.economy.history import HistoryCursor
from butterbot.application.operations.ports import OperationsTelemetry
from butterbot.application.operations.telemetry import emit_operational_telemetry

logger = logging.getLogger(__name__)


class Balance(commands.Cog):
    def __init__(self, service: BalanceUseCase, telemetry: OperationsTelemetry) -> None:
        self._service = service
        self._telemetry = telemetry

    @app_commands.command(name="history", description="Privately view your wallet history.")
    async def history(self, interaction: discord.Interaction, before: str | None = None) -> None:
        started = perf_counter()
        outcome = "failed"
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                cursor = None
                if before is not None:
                    if len(before) > 60:
                        raise ValueError("invalid cursor")
                    timestamp, identity = before.split(":")
                    if not timestamp.isascii() or not timestamp.isdecimal():
                        raise ValueError("invalid cursor")
                    cursor = HistoryCursor(int(timestamp), UUID(identity))
                page = await self._service.history(
                    discord_user_id=interaction.user.id, cursor=cursor
                )
                outcome = page.status
                if page.status == "unjoined":
                    message = "Use /join to create your wallet first."
                elif page.status != "available":
                    message = "Your wallet history is unavailable."
                elif not page.entries:
                    message = "No wallet transactions on this page."
                else:
                    lines = ["Your wallet history (newest first):"]
                    for entry in page.entries:
                        result = (
                            ""
                            if entry.resulting_balance is None
                            else f" | Balance: {entry.resulting_balance:,}"
                        )
                        lines.append(
                            f"<t:{entry.committed_at_ms // 1000}:f> | {entry.kind} | "
                            f"{entry.amount:+,} coins{result}\nReference: `{entry.transaction_id}`"
                        )
                    if page.next_cursor is not None:
                        next_page = page.next_cursor
                        lines.append(
                            f"Next page: `/history before:{next_page.committed_at_ms}:"
                            f"{next_page.transaction_id}`"
                        )
                    message = "\n".join(lines)
            except (ValueError, TypeError):
                outcome = "invalid"
                message = "Invalid history cursor. Copy the next-page value from /history."
            except Exception as error:
                logger.error("History query failed with %s", type(error).__name__)
                message = "Could not read your wallet history. Please try again later."
            await interaction.followup.send(
                message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        finally:
            emit_operational_telemetry(
                "discord.command_completed",
                lambda: self._telemetry.discord_command_completed(
                    command="history",
                    outcome=outcome,
                    duration_ms=(perf_counter() - started) * 1000,
                ),
            )

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
