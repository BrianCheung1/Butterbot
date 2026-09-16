from __future__ import annotations

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


class ExactIntegerOutOfRange(ValueError):
    """An exact-count value cannot be represented as a signed 64-bit integer."""


def require_int64(
    value: int,
    name: str,
    *,
    minimum: int = INT64_MIN,
    maximum: int = INT64_MAX,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ExactIntegerOutOfRange(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def checked_add_int64(left: int, right: int, name: str) -> int:
    require_int64(left, f"{name} left operand")
    require_int64(right, f"{name} right operand")
    return require_int64(left + right, name)


__all__ = [
    "INT64_MAX",
    "INT64_MIN",
    "ExactIntegerOutOfRange",
    "checked_add_int64",
    "require_int64",
]
