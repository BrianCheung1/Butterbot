import os

from butterbot.application.safety.service import SafetyPolicy
from butterbot.discord_app.config import ConfigurationError


def load_safety_policy() -> SafetyPolicy | None:
    names = (
        "BUTTERBOT_SAFETY_APPROVAL_THRESHOLD",
        "BUTTERBOT_SAFETY_OPERATION_CEILING",
        "BUTTERBOT_SAFETY_24H_CEILING",
        "BUTTERBOT_SAFETY_ALERT_DESTINATION",
    )
    values = [os.getenv(name, "").strip() for name in names]
    if not any(values):
        return None
    if (
        not all(values)
        or values[3] != "local_log"
        or any(not value.isascii() or not value.isdecimal() for value in values[:3])
    ):
        raise ConfigurationError(
            "Safety requires all three integer limits and local_log alert destination."
        )
    try:
        return SafetyPolicy(*(int(value) for value in values[:3]))
    except ValueError as error:
        raise ConfigurationError("Safety limits must be ordered signed-64-bit integers.") from error


def load_development_operators() -> tuple[int, ...]:
    value = os.getenv("BUTTERBOT_DEV_SAFETY_BOOTSTRAP_IDS", "").strip()
    if not value:
        return ()
    parts = value.split(",")
    if not 1 <= len(parts) <= 10 or any(not p.isascii() or not p.isdecimal() for p in parts):
        raise ConfigurationError(
            "Development bootstrap requires explicit comma-separated user IDs."
        )
    operators = tuple(int(p) for p in parts)
    if len(set(operators)) != len(operators) or any(not 0 < actor < 2**63 for actor in operators):
        raise ConfigurationError("Development bootstrap IDs must be distinct positive snowflakes.")
    return operators
