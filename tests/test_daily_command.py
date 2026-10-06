import asyncio
from collections.abc import Awaitable, Callable
from typing import cast
from unittest.mock import AsyncMock

import pytest
from tests.test_daily import service as daily_service
from tests.test_grants import reconcile
from tests.test_join import service as joins
from tests.test_ping import RecordingTelemetry

from butterbot.application.economy.daily import DAY_MS, DailyResult
from butterbot.discord_app.extensions.daily import Daily
from butterbot.infrastructure.persistence.database import DatabaseRuntime


@pytest.mark.parametrize("claim", [False, True])
async def test_private_self_only_defer_and_immutable_period(claim: bool) -> None:
    interaction, service = AsyncMock(), AsyncMock()
    interaction.user.id = 123
    interaction.id = (1800000000000 - 1420070400000) << 22

    async def execute(**kwargs: object) -> DailyResult:
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert kwargs["discord_user_id"] == 123
        if claim:
            assert kwargs == {
                "discord_user_id": 123,
                "interaction_id": interaction.id,
                "claim_period": 1800000000000 // DAY_MS,
            }
        else:
            assert kwargs == {"discord_user_id": 123}
        return DailyResult("available", 1800000000000 // DAY_MS)

    service.claim.side_effect = execute
    service.inspect.side_effect = execute
    command = Daily.claim if claim else Daily.status
    assert command.parameters == []
    await cast(Callable[..., Awaitable[None]], command.callback)(
        Daily(service, RecordingTelemetry()), interaction
    )
    assert interaction.followup.send.await_args.kwargs == {"ephemeral": True}
    assert "15-coin" in interaction.followup.send.await_args.args[0]


async def test_errors_sanitized_and_cancellation_propagated() -> None:
    interaction, service = AsyncMock(), AsyncMock()
    interaction.user.id, interaction.id = 123, 123
    service.claim.side_effect = RuntimeError("private database data")
    cog = Daily(service, RecordingTelemetry())
    await cast(Callable[..., Awaitable[None]], Daily.claim.callback)(cog, interaction)
    assert "private database" not in interaction.followup.send.await_args.args[0]
    service.claim.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await cast(Callable[..., Awaitable[None]], Daily.claim.callback)(cog, interaction)


async def test_response_loss_after_commit(database_runtime: DatabaseRuntime) -> None:
    r = database_runtime
    await joins(r).join(discord_user_id=123, interaction_id=1)
    now = 1800000000000
    service = daily_service(r, clock=lambda: now)
    cog = Daily(service, RecordingTelemetry())
    interaction = AsyncMock()
    interaction.user.id = 123
    interaction.id = (now - 1420070400000) << 22
    interaction.followup.send.side_effect = RuntimeError("response lost")
    with pytest.raises(RuntimeError):
        await cast(Callable[..., Awaitable[None]], Daily.claim.callback)(cog, interaction)
    result = await service.claim(
        discord_user_id=123, interaction_id=interaction.id, claim_period=now // DAY_MS
    )
    assert result.replayed and result.balance == 15
    result = await service.claim(
        discord_user_id=123, interaction_id=interaction.id + 1, claim_period=now // DAY_MS
    )
    assert result.status == "already_claimed"
    reconcile(r)
