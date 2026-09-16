import asyncio
from unittest.mock import AsyncMock

import pytest
from tests.test_join import counts
from tests.test_join import service as real_join_service
from tests.test_ping import RecordingTelemetry

from butterbot.application.operations.idempotency import FingerprintConflict
from butterbot.application.players.join import JoinResult, JoinStatus
from butterbot.discord_app.extensions.join import Join
from butterbot.infrastructure.persistence.database import DatabaseRuntime


@pytest.mark.parametrize("status", ["created", "already_joined", "disabled", "inactive"])
async def test_join_responses_are_private_and_deferred_before_application(
    status: JoinStatus,
) -> None:
    interaction = AsyncMock()
    interaction.id = 456
    interaction.user.id = 123
    service = AsyncMock()

    async def execute(*, discord_user_id: int, interaction_id: int) -> JoinResult:
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert (discord_user_id, interaction_id) == (123, 456)
        return JoinResult(status, False)

    service.join.side_effect = execute
    telemetry = RecordingTelemetry()
    await Join.join.callback(Join(service, telemetry), interaction)  # pyright: ignore[reportCallIssue]
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.await_args.kwargs == {"ephemeral": True}
    message = interaction.followup.send.await_args.args[0]
    assert isinstance(message, str) and "123" not in message and "456" not in message
    interaction.response.send_message.assert_not_awaited()
    assert telemetry.events[0][:2] == ("join", status)


@pytest.mark.parametrize("error", [RuntimeError("sensitive database path"), FingerprintConflict()])
async def test_join_failures_are_private_and_do_not_expose_internal_details(
    error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    interaction = AsyncMock()
    service = AsyncMock()
    service.join.side_effect = error
    telemetry = RecordingTelemetry()
    await Join.join.callback(Join(service, telemetry), interaction)  # pyright: ignore[reportCallIssue]
    assert interaction.followup.send.await_args.kwargs == {"ephemeral": True}
    assert "sensitive database path" not in interaction.followup.send.await_args.args[0]
    assert "sensitive database path" not in caplog.text
    assert telemetry.events[0][1] == (
        "conflict" if isinstance(error, FingerprintConflict) else "failed"
    )


async def test_join_response_failure_does_not_repeat_application_operation() -> None:
    interaction = AsyncMock()
    interaction.followup.send.side_effect = RuntimeError("response timeout")
    service = AsyncMock()
    service.join.return_value = JoinResult("created", False)
    telemetry = RecordingTelemetry()
    with pytest.raises(RuntimeError, match="response timeout"):
        await Join.join.callback(Join(service, telemetry), interaction)  # pyright: ignore[reportCallIssue]
    service.join.assert_awaited_once()
    assert telemetry.events[0][:2] == ("join", "failed")


async def test_join_does_not_mutate_if_private_acknowledgement_fails() -> None:
    interaction = AsyncMock()
    interaction.response.defer.side_effect = RuntimeError("defer failed")
    service = AsyncMock()
    with pytest.raises(RuntimeError, match="defer failed"):
        await Join.join.callback(Join(service, RecordingTelemetry()), interaction)  # pyright: ignore[reportCallIssue]
    service.join.assert_not_awaited()


async def test_join_cancellation_is_not_converted_to_an_ordinary_error() -> None:
    interaction = AsyncMock()
    service = AsyncMock()
    service.join.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await Join.join.callback(Join(service, RecordingTelemetry()), interaction)  # pyright: ignore[reportCallIssue]
    interaction.followup.send.assert_not_awaited()


async def test_response_timeout_after_real_commit_can_be_retried_without_duplicate_state(
    database_runtime: DatabaseRuntime,
) -> None:
    joins = real_join_service(database_runtime)
    cog = Join(joins, RecordingTelemetry())
    interaction = AsyncMock()
    interaction.user.id = 123
    interaction.id = 456

    async def fail_response(message: str, *, ephemeral: bool) -> None:
        assert ephemeral and "joined" in message
        # Separate SQLite connection can see the commit before Discord sends anything.
        assert counts(database_runtime.database_path) == (1, 1, 1, 1, 0, 0, 0)
        raise RuntimeError("lost response")

    interaction.followup.send.side_effect = fail_response
    with pytest.raises(RuntimeError, match="lost response"):
        await Join.join.callback(cog, interaction)  # pyright: ignore[reportCallIssue]
    interaction.followup.send.side_effect = None
    await Join.join.callback(cog, interaction)  # pyright: ignore[reportCallIssue]
    assert counts(database_runtime.database_path) == (1, 1, 1, 1, 0, 0, 0)
    interaction.id = 457
    await Join.join.callback(cog, interaction)  # pyright: ignore[reportCallIssue]
    assert "already joined" in interaction.followup.send.await_args.args[0]
    assert counts(database_runtime.database_path) == (1, 1, 1, 2, 0, 0, 0)
