from __future__ import annotations


def is_permanent_reference(value: str, *, maximum: int = 255) -> bool:
    """Return whether a permanent identity is visible ASCII with no whitespace or controls."""
    return 1 <= len(value) <= maximum and all("!" <= character <= "~" for character in value)


def require_permanent_reference(value: str, field: str, *, maximum: int = 255) -> str:
    if not is_permanent_reference(value, maximum=maximum):
        raise ValueError(
            f"{field} must be a non-empty visible-ASCII reference without whitespace or controls"
        )
    return value


__all__ = ["is_permanent_reference", "require_permanent_reference"]
