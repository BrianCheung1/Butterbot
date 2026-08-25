from unittest.mock import AsyncMock

import pytest

from butterbot.discord_app.extensions.ping import Ping


@pytest.mark.asyncio
async def test_ping_responds_with_pong() -> None:
    interaction = AsyncMock()

    await Ping.ping.callback(Ping(), interaction)  # pyright: ignore[reportCallIssue]

    interaction.response.send_message.assert_awaited_once_with("Pong!")
