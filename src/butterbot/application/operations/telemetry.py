from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress

logger = logging.getLogger(__name__)


def emit_operational_telemetry(event: str, emit: Callable[[], None]) -> bool:
    """Emit observational telemetry without changing the owning operation's outcome."""
    try:
        emit()
    except BaseException as error:
        with suppress(BaseException):
            logger.error(
                "Operational telemetry emission failed for %s",
                event,
                exc_info=(type(error), error, error.__traceback__),
            )
        return False
    return True


__all__ = ["emit_operational_telemetry"]
