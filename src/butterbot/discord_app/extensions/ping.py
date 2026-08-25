import discord
from discord import app_commands
from discord.ext import commands


class Ping(commands.Cog):
    @app_commands.command(name="ping", description="Check whether Butterbot is running.")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ping())
