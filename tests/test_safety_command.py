import asyncio
from collections.abc import Awaitable, Callable
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from tests.test_ping import RecordingTelemetry

from butterbot.application.safety.ports import Proposal
from butterbot.application.safety.service import InspectionResult, ProposalView, SafetyResult
from butterbot.discord_app.extensions.safety import Safety


async def test_inspection_private_and_uses_interaction_actor_not_discord_roles() -> None:
    interaction = AsyncMock()
    interaction.user.id = 111
    interaction.user.guild_permissions.administrator = True
    user = AsyncMock()
    user.id = 222
    service = AsyncMock()

    async def inspect(*, actor_id: int, target_id: int, reason: str) -> InspectionResult:
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert (actor_id, target_id, reason) == (111, 222, "support")
        return InspectionResult("denied")

    service.inspect.side_effect = inspect
    telemetry = RecordingTelemetry()
    await cast(Callable[..., Awaitable[None]], Safety.inspect.callback)(
        Safety(service, telemetry), interaction, user, "support"
    )
    assert interaction.followup.send.await_args.kwargs["ephemeral"]
    assert "denied" in interaction.followup.send.await_args.args[0]
    assert "coins" not in interaction.followup.send.await_args.args[0]
    assert not interaction.followup.send.await_args.kwargs["allowed_mentions"].everyone


async def test_preview_contains_exact_bounded_proposal_privately_without_mentions() -> None:
    identity = uuid4()
    proposal = Proposal(
        identity,
        111,
        "grant",
        (123, 456),
        7,
        "@everyone **reason**",
        1000,
        86401000,
        True,
        "pending",
    )
    service = AsyncMock()
    service.view_proposal.return_value = ProposalView("available", proposal)
    interaction = AsyncMock()
    interaction.user.id = 222
    await cast(Callable[..., Awaitable[None]], Safety.proposal.callback)(
        Safety(service, RecordingTelemetry()), interaction, str(identity)
    )
    message = interaction.followup.send.await_args.args[0]
    assert str(identity) in message and "123, 456" in message and "Total coins: 14" in message
    assert "Proposer: 111" in message and "pending" in message
    assert interaction.followup.send.await_args.kwargs["ephemeral"]
    assert not interaction.followup.send.await_args.kwargs["allowed_mentions"].everyone
    service.view_proposal.assert_awaited_once_with(actor_id=222, proposal_id=identity)


@pytest.mark.parametrize("targets,amount", [("global", "0"), ("123,456", "7")])
async def test_propose_parses_only_explicit_targets(targets: str, amount: str) -> None:
    interaction = AsyncMock()
    interaction.user.id = 111
    interaction.id = 999
    service = AsyncMock()
    service.propose.return_value = SafetyResult("pending", uuid4())
    await cast(Callable[..., Awaitable[None]], Safety.propose.callback)(
        Safety(service, RecordingTelemetry()), interaction, "freeze", targets, "reason", amount
    )
    assert service.propose.await_args.kwargs["targets"] == (
        (0,) if targets == "global" else (123, 456)
    )
    assert service.propose.await_args.kwargs["actor_id"] == 111
    assert interaction.followup.send.await_args.kwargs["ephemeral"]


@pytest.mark.parametrize(
    "targets,amount",
    [
        ("@everyone", "0"),
        ("1,2,", "0"),
        ("123", "-1"),
        ("123", "1.5"),
        ("123", "９"),
        ("123", "1" * 20),
        ("1," * 26, "0"),
    ],
)
async def test_invalid_input_does_not_reach_service(targets: str, amount: str) -> None:
    interaction = AsyncMock()
    service = AsyncMock()
    await cast(Callable[..., Awaitable[None]], Safety.propose.callback)(
        Safety(service, RecordingTelemetry()), interaction, "grant", targets, "reason", amount
    )
    service.propose.assert_not_awaited()
    assert "Invalid" in interaction.followup.send.await_args.args[0]


@pytest.mark.parametrize("phase", ["defer", "query", "response"])
async def test_command_failure_does_not_retry_and_cancellation_propagates(phase: str) -> None:
    interaction = AsyncMock()
    service = AsyncMock()
    service.approve.return_value = SafetyResult("approved")
    if phase == "defer":
        interaction.response.defer.side_effect = RuntimeError("defer")
    elif phase == "query":
        service.approve.side_effect = asyncio.CancelledError()
    else:
        interaction.followup.send.side_effect = RuntimeError("response")
    with pytest.raises(asyncio.CancelledError if phase == "query" else RuntimeError):
        await cast(Callable[..., Awaitable[None]], Safety.approve.callback)(
            Safety(service, RecordingTelemetry()), interaction, str(uuid4())
        )
    assert service.approve.await_count == (0 if phase == "defer" else 1)


async def test_command_errors_do_not_expose_internal_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    interaction = AsyncMock()
    service = AsyncMock()
    service.approve.side_effect = RuntimeError("secret-path 987654321")
    await cast(Callable[..., Awaitable[None]], Safety.approve.callback)(
        Safety(service, RecordingTelemetry()), interaction, str(uuid4())
    )
    assert "987654321" not in caplog.text
    assert "987654321" not in interaction.followup.send.await_args.args[0]
    assert interaction.followup.send.await_args.kwargs["ephemeral"]
