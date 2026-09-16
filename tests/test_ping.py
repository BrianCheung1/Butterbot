from unittest.mock import AsyncMock

import pytest

from butterbot.application.operations.idempotency import NullOperationsTelemetry
from butterbot.discord_app.extensions.ping import Ping


class RecordingTelemetry(NullOperationsTelemetry):
    def __init__(self) -> None:
        self.events: list[tuple[str, str, float]] = []

    def discord_command_completed(self, *, command: str, outcome: str, duration_ms: float) -> None:
        self.events.append((command, outcome, duration_ms))


@pytest.mark.asyncio
async def test_ping_responds_with_pong() -> None:
    interaction = AsyncMock()
    telemetry = RecordingTelemetry()

    await Ping.ping.callback(Ping(telemetry), interaction)  # pyright: ignore[reportCallIssue]

    interaction.response.send_message.assert_awaited_once_with("Pong!")
    assert len(telemetry.events) == 1
    assert telemetry.events[0][:2] == ("ping", "completed")
    assert telemetry.events[0][2] >= 0


@pytest.mark.asyncio
async def test_ping_emits_failed_completion_without_masking_response_error() -> None:
    interaction = AsyncMock()
    interaction.response.send_message.side_effect = RuntimeError("discord unavailable")
    telemetry = RecordingTelemetry()

    with pytest.raises(RuntimeError, match="discord unavailable"):
        await Ping.ping.callback(Ping(telemetry), interaction)  # pyright: ignore[reportCallIssue]

    assert telemetry.events[0][:2] == ("ping", "failed")
