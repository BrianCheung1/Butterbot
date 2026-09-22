import asyncio
from unittest.mock import AsyncMock

import pytest
from tests.test_ping import RecordingTelemetry

from butterbot.application.economy.balance import BalanceResult
from butterbot.discord_app.extensions.balance import Balance


@pytest.mark.parametrize(
    "result,expected",
    [
        (BalanceResult("available", 0), "0 coins"),
        (BalanceResult("available", 1234567), "1,234,567 coins"),
        (BalanceResult("unjoined"), "/join"),
        (BalanceResult("inactive"), "unavailable"),
        (BalanceResult("unavailable"), "unavailable"),
    ],
)
async def test_balance_is_private_self_only_and_deferred(
    result: BalanceResult, expected: str
) -> None:
    interaction = AsyncMock()
    interaction.user.id = 123
    service = AsyncMock()

    async def execute(*, discord_user_id: int) -> BalanceResult:
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        assert discord_user_id == 123
        return result

    service.balance.side_effect = execute
    telemetry = RecordingTelemetry()
    await Balance.balance.callback(Balance(service, telemetry), interaction)  # pyright: ignore[reportCallIssue]
    assert expected in interaction.followup.send.await_args.args[0]
    assert interaction.followup.send.await_args.kwargs == {"ephemeral": True}
    assert telemetry.events[0][:2] == ("balance", result.status)
    assert Balance.balance.parameters == []


async def test_balance_error_is_private_and_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    service = AsyncMock()
    service.balance.side_effect = RuntimeError("secret path and balance 98765")
    interaction = AsyncMock()
    telemetry = RecordingTelemetry()
    await Balance.balance.callback(Balance(service, telemetry), interaction)  # pyright: ignore[reportCallIssue]
    assert "98765" not in caplog.text
    assert "98765" not in interaction.followup.send.await_args.args[0]
    assert interaction.followup.send.await_args.kwargs == {"ephemeral": True}
    assert telemetry.events[0][:2] == ("balance", "failed")


@pytest.mark.parametrize("phase", ["defer", "query", "response"])
async def test_balance_failure_does_not_retry_or_hide_cancellation(phase: str) -> None:
    interaction = AsyncMock()
    service = AsyncMock()
    service.balance.return_value = BalanceResult("available", 0)
    if phase == "defer":
        interaction.response.defer.side_effect = RuntimeError("defer failed")
    elif phase == "query":
        service.balance.side_effect = asyncio.CancelledError()
    else:
        interaction.followup.send.side_effect = RuntimeError("response failed")
    with pytest.raises(asyncio.CancelledError if phase == "query" else RuntimeError):
        await Balance.balance.callback(Balance(service, RecordingTelemetry()), interaction)  # pyright: ignore[reportCallIssue]
    assert service.balance.await_count == (0 if phase == "defer" else 1)
    if phase != "response":
        interaction.followup.send.assert_not_awaited()
