from __future__ import annotations

import json
import math
import re
from typing import cast

from butterbot.application.operations.ports import JsonValue, StableOutcome

_STABLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class InvalidStableOutcome(ValueError):
    """A transport outcome cannot be represented by the stable JSON contract."""


def canonicalize_stable_outcome(outcome: StableOutcome) -> tuple[StableOutcome, str]:
    if type(outcome.kind) is not str or outcome.kind not in {"success", "typed_rejection"}:
        raise InvalidStableOutcome("transport outcome must be success or typed_rejection")
    if (
        type(outcome.code) is not str
        or len(outcome.code) > 100
        or not _STABLE_CODE_PATTERN.fullmatch(outcome.code)
    ):
        raise InvalidStableOutcome("transport outcome code must be a stable lowercase name")
    try:
        payload = _canonical_json_value(outcome.payload, active_containers=set())
    except RecursionError as error:
        raise InvalidStableOutcome("transport outcome payload is nested too deeply") from error
    if not isinstance(payload, dict):
        raise InvalidStableOutcome("transport outcome payload must be a JSON object")
    serialized = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        serialized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidStableOutcome("transport outcome contains invalid Unicode") from error
    return StableOutcome(kind=outcome.kind, code=outcome.code, payload=payload), serialized


def decode_canonical_stable_outcome(
    *,
    kind: str,
    code: str,
    payload_text: str,
) -> StableOutcome:
    if type(payload_text) is not str:
        raise InvalidStableOutcome("stored transport outcome payload must be text")
    try:
        raw_payload = json.loads(
            payload_text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise InvalidStableOutcome("stored transport outcome payload is invalid JSON") from error
    canonical, serialized = canonicalize_stable_outcome(
        StableOutcome(kind=kind, code=code, payload=cast("dict[str, JsonValue]", raw_payload))
    )
    if serialized != payload_text:
        raise InvalidStableOutcome("stored transport outcome payload is not canonical JSON")
    return canonical


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidStableOutcome("stored transport outcome contains duplicate object keys")
        result[key] = value
    return result


def _reject_non_finite_constant(value: str) -> object:
    raise InvalidStableOutcome(f"non-finite JSON number {value!r} is not permitted")


def _canonical_json_value(value: object, *, active_containers: set[int]) -> JsonValue:
    value_type = type(value)
    if value is None or value_type is bool or value_type is int:
        return cast("JsonValue", value)
    if value_type is float:
        if not math.isfinite(cast("float", value)):
            raise InvalidStableOutcome("transport outcome numbers must be finite")
        return cast("float", value)
    if value_type is str:
        try:
            cast("str", value).encode("utf-8")
        except UnicodeEncodeError as error:
            raise InvalidStableOutcome("transport outcome contains invalid Unicode") from error
        return cast("str", value)
    if value_type is list:
        identity = id(value)
        if identity in active_containers:
            raise InvalidStableOutcome("transport outcome payload must not contain cycles")
        active_containers.add(identity)
        try:
            return [
                _canonical_json_value(item, active_containers=active_containers)
                for item in cast("list[object]", value)
            ]
        finally:
            active_containers.remove(identity)
    if value_type is dict:
        identity = id(value)
        if identity in active_containers:
            raise InvalidStableOutcome("transport outcome payload must not contain cycles")
        active_containers.add(identity)
        try:
            result: dict[str, JsonValue] = {}
            for key, item in cast("dict[object, object]", value).items():
                if type(key) is not str:
                    raise InvalidStableOutcome("transport outcome object keys must be strings")
                result[key] = _canonical_json_value(
                    item,
                    active_containers=active_containers,
                )
            return result
        finally:
            active_containers.remove(identity)
    raise InvalidStableOutcome(
        f"transport outcome contains unsupported JSON value {value_type.__name__}"
    )


__all__ = [
    "InvalidStableOutcome",
    "canonicalize_stable_outcome",
    "decode_canonical_stable_outcome",
]
