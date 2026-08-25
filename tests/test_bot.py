from unittest.mock import AsyncMock

import discord
import pytest

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
