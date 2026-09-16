from __future__ import annotations

import re
from dataclasses import dataclass

from butterbot.application.identity import require_permanent_reference

_STABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_NAMESPACED_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _require_name(value: str, field: str, *, maximum: int, namespaced: bool = False) -> str:
    pattern = _NAMESPACED_NAME if namespaced else _STABLE_NAME
    if len(value) > maximum or pattern.fullmatch(value) is None:
        qualifier = "namespaced " if namespaced else ""
        raise ValueError(f"{field} must be a non-empty {qualifier}stable name")
    return value


@dataclass(frozen=True, slots=True)
class LedgerAuditIdentity:
    transaction_kind: str
    actor_kind: str
    actor_reference: str
    reason_code: str
    domain_reference: str | None = None
    content_version: str | None = None

    def __post_init__(self) -> None:
        _require_name(self.transaction_kind, "transaction_kind", maximum=64)
        _require_name(self.actor_kind, "actor_kind", maximum=32)
        require_permanent_reference(self.actor_reference, "actor_reference")
        _require_name(self.reason_code, "reason_code", maximum=100, namespaced=True)
        if self.domain_reference is not None:
            require_permanent_reference(self.domain_reference, "domain_reference")
        if self.content_version is not None:
            require_permanent_reference(self.content_version, "content_version", maximum=100)


def validate_system_account_key(system_key: str) -> str:
    return _require_name(system_key, "system_key", maximum=100, namespaced=True)
