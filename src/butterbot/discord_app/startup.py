from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from types import TracebackType
from typing import Protocol

from butterbot.bootstrap import compose_application
from butterbot.discord_app.bot import create_bot
from butterbot.discord_app.config import ConfigurationError, load_settings
from butterbot.infrastructure.persistence.readiness import DatabaseReadinessError
from butterbot.infrastructure.telemetry import JsonLogFormatter

logger = logging.getLogger(__name__)


class _DiscordService(Protocol):
    async def __aenter__(self) -> _DiscordService: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def start(self, token: str) -> None: ...

    async def close(self) -> None: ...


def configure_logging(*, release: str = "bootstrap") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter(default_release=release))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


@asynccontextmanager
async def _sigterm_event() -> AsyncGenerator[asyncio.Event]:
    """Translate the production stop signal into an orderly async service stop."""
    requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = False
    if os.name == "posix":
        loop.add_signal_handler(signal.SIGTERM, requested.set)
        installed = True
    try:
        yield requested
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGTERM)


async def serve_until_shutdown(bot: _DiscordService, token: str) -> None:
    """Run Discord until it exits or POSIX SIGTERM requests graceful shutdown."""
    async with _sigterm_event() as shutdown_requested, bot:
        discord_task = asyncio.create_task(bot.start(token), name="discord-service")
        signal_task = asyncio.create_task(shutdown_requested.wait(), name="sigterm-waiter")
        try:
            done, _ = await asyncio.wait(
                {discord_task, signal_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if signal_task in done and not discord_task.done():
                logger.info("SIGTERM received; beginning orderly shutdown")
                await bot.close()
            await discord_task
        finally:
            signal_task.cancel()
            with suppress(asyncio.CancelledError):
                await signal_task


async def run() -> None:
    settings = load_settings()
    configure_logging(release=settings.release_id)
    application = await compose_application(settings)

    logger.info("Starting Butterbot")
    try:
        bot = create_bot(
            telemetry=application.telemetry,
            join_service=application.join_service,
            balance_service=application.balance_service,
        )
        await serve_until_shutdown(bot, settings.discord_token)
    finally:
        await application.close()
        logger.info("Butterbot shutdown complete")


def main() -> None:
    configure_logging()
    try:
        asyncio.run(run())
    except ConfigurationError as error:
        logger.error("Configuration error: %s", error)
        raise SystemExit(2) from error
    except DatabaseReadinessError as error:
        logger.critical("Database readiness error [%s]: %s", error.category, error)
        raise SystemExit(3) from error
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
