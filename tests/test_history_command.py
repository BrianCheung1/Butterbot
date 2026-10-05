import asyncio
from collections.abc import Awaitable, Callable
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from tests.test_corrections import funded, reconcile
from tests.test_join import Eligibility
from tests.test_ping import RecordingTelemetry
from tests.test_safety import service as safety_service

from butterbot.application.economy.history import HistoryCursor, HistoryEntry, HistoryPage
from butterbot.application.safety.service import SafetyResult
from butterbot.discord_app.extensions.balance import Balance
from butterbot.discord_app.extensions.safety import Safety
from butterbot.infrastructure.persistence.database import DatabaseRuntime


async def test_history_command_private_bounded_self_only() -> None:
    interaction = AsyncMock()
    interaction.user.id = 123
    service = AsyncMock()
    entry = HistoryEntry(UUID(int=1), 2**63 - 1, "Grant correction", -(2**63 - 1), 2**63 - 1)

    async def query(*, discord_user_id: int, cursor: HistoryCursor | None) -> HistoryPage:
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert discord_user_id == 123 and cursor is None
        return HistoryPage("available", (entry,) * 5, HistoryCursor(1000, entry.transaction_id))

    service.history.side_effect = query
    await cast(Callable[..., Awaitable[None]], Balance.history.callback)(
        Balance(service, RecordingTelemetry()), interaction
    )  # pyright: ignore[reportCallIssue]
    sent = interaction.followup.send.await_args
    assert sent.kwargs["ephemeral"] is True
    assert len(sent.args[0]) <= 2000
    assert "Next page:" in sent.args[0]
    assert [p.name for p in Balance.history.parameters] == ["before"]


@pytest.mark.parametrize("cursor", ["bad", "-1:bad", "x" * 100, "1:bad", "1:2:3"])
async def test_history_invalid_cursor_never_queries(cursor: str) -> None:
    interaction, service = AsyncMock(), AsyncMock()
    await cast(Callable[..., Awaitable[None]], Balance.history.callback)(
        Balance(service, RecordingTelemetry()), interaction, cursor
    )  # pyright: ignore[reportCallIssue]
    service.history.assert_not_awaited()
    assert "Invalid" in interaction.followup.send.await_args.args[0]


async def test_history_error_sanitized_and_cancel_not_swallowed() -> None:
    interaction, service = AsyncMock(), AsyncMock()
    service.history.side_effect = RuntimeError("private operator information")
    await cast(Callable[..., Awaitable[None]], Balance.history.callback)(
        Balance(service, RecordingTelemetry()), interaction
    )  # pyright: ignore[reportCallIssue]
    assert "private operator" not in interaction.followup.send.await_args.args[0]
    service.history.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await cast(Callable[..., Awaitable[None]], Balance.history.callback)(
            Balance(service, RecordingTelemetry()), interaction
        )  # pyright: ignore[reportCallIssue]


async def test_correction_adapter_defers_and_uses_actor_privately() -> None:
    interaction, service, target = AsyncMock(), AsyncMock(), AsyncMock()
    interaction.user.id, interaction.id, target.id = 111, 222, 333

    async def execute(**kwargs: object) -> SafetyResult:
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert kwargs == dict(
            actor_id=111,
            target_id=333,
            original_transaction_id=UUID(int=1),
            amount=10,
            reason="mistake",
            bypass_freeze=False,
            interaction_id=222,
        )
        return SafetyResult("corrected")

    service.correct_grant.side_effect = execute
    await cast(Callable[..., Awaitable[None]], Safety.correct_grant.callback)(
        Safety(service, RecordingTelemetry()),
        interaction,
        str(UUID(int=1)),
        target,
        "10",
        "mistake",
    )  # pyright: ignore[reportCallIssue]
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True
    assert "corrected" in interaction.followup.send.await_args.args[0]


async def test_correction_response_loss_after_real_commit(
    database_runtime: DatabaseRuntime,
) -> None:
    original = await funded(database_runtime)
    interaction, target = AsyncMock(), AsyncMock()
    interaction.user.id, interaction.id, target.id = 111, 10, 123
    interaction.followup.send.side_effect = RuntimeError("response lost")
    cog = Safety(
        safety_service(database_runtime, grant_eligibility=Eligibility()), RecordingTelemetry()
    )
    callback = cast(Callable[..., Awaitable[None]], Safety.correct_grant.callback)
    with pytest.raises(RuntimeError, match="response lost"):
        await callback(cog, interaction, str(original), target, "10", "mistake")
    interaction.followup.send.side_effect = None
    interaction.id = 11
    await callback(cog, interaction, str(original), target, "10", "mistake")
    assert "already_corrected" in interaction.followup.send.await_args.args[0]
    reconcile(database_runtime)
