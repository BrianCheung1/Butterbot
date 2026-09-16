from unittest.mock import AsyncMock

import discord
import pytest

from butterbot.application.players.join import JoinResult
from butterbot.discord_app.bot import create_bot


def test_create_bot_uses_only_default_intents() -> None:
    bot = create_bot(extensions=())

    assert bot.intents.value == discord.Intents.default().value


@pytest.mark.asyncio
async def test_setup_hook_loads_each_configured_extension() -> None:
    bot = create_bot(extensions=("example.first", "example.second"))
    load_extension = AsyncMock()
    sync = AsyncMock(return_value=[])
    bot.load_extension = load_extension
    bot.tree.sync = sync

    await bot.setup_hook()

    assert load_extension.await_args_list[0].args == ("example.first",)
    assert load_extension.await_args_list[1].args == ("example.second",)
    sync.assert_awaited_once_with()


async def test_default_extensions_register_private_join_without_privileged_intents() -> None:
    service = AsyncMock()
    service.join.return_value = JoinResult("disabled", False)
    bot = create_bot(join_service=service)
    bot.tree.sync = AsyncMock(return_value=[])
    try:
        await bot.setup_hook()
        assert {command.name for command in bot.tree.get_commands()} == {"ping", "join"}
        assert bot.intents.message_content is False
        assert bot.intents.members is False
        assert bot.intents.presences is False
    finally:
        await bot.close()
