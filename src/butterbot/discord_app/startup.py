import asyncio
import logging

from butterbot.discord_app.bot import create_bot
from butterbot.discord_app.config import ConfigurationError, load_settings

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def run() -> None:
    settings = load_settings()
    bot = create_bot()

    logger.info("Starting Butterbot")
    try:
        async with bot:
            await bot.start(settings.discord_token)
    finally:
        logger.info("Butterbot shutdown complete")


def main() -> None:
    configure_logging()
    try:
        asyncio.run(run())
    except ConfigurationError as error:
        logger.error("Configuration error: %s", error)
        raise SystemExit(2) from error
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
