import logging
from uuid import UUID

logger = logging.getLogger("butterbot.safety")


def local_safety_alert(action: str, audit_id: UUID) -> None:
    """Local-only approved sink; durable audit is authoritative if log delivery fails."""
    logger.warning(
        "Safety/access event",
        extra={
            "event_data": {"event": "safety.access", "action": action, "audit_id": str(audit_id)}
        },
    )
