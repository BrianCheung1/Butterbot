from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MutationEligibilityDecision:
    allowed: bool
    reason: str


class MutationEligibility(Protocol):
    def evaluate(self) -> MutationEligibilityDecision: ...


class RuntimeSafety(Protocol):
    def is_safe(self) -> bool: ...


class GlobalMutationEligibility:
    """Fail-closed pre-Slice-1.3 mutation policy."""

    def __init__(
        self,
        *,
        configured_enabled: bool,
        database_ready: bool,
        runtime_safety: RuntimeSafety | None = None,
    ) -> None:
        self._configured_enabled = configured_enabled
        self._database_ready = database_ready
        self._runtime_safety = runtime_safety

    def evaluate(self) -> MutationEligibilityDecision:
        if not self._database_ready:
            return MutationEligibilityDecision(False, "database_not_ready")
        if self._runtime_safety is not None and not self._runtime_safety.is_safe():
            return MutationEligibilityDecision(False, "runtime_storage_unsafe")
        if not self._configured_enabled:
            return MutationEligibilityDecision(False, "globally_disabled")
        return MutationEligibilityDecision(True, "enabled")
