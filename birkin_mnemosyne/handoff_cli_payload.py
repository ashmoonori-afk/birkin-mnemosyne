"""Structured ``--json-stdin`` payload parsing for the handoff capture command.

Every value is type-checked here and every key is bounded to the capture
schema, so an unknown or malformed payload raises :class:`HandoffError` before
the store is touched; absent list families mean empty, never an error.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import TypeAlias

from .handoff_context import required_scope
from .handoff_records import HandoffError, HandoffFields, HandoffScope

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | \
    dict[str, "JsonValue"]
_load: Callable[[str], JsonValue] = json.loads

_JSON_KEYS = frozenset({
    "project_key", "task_key", "capture_id", "work", "next_step",
    "decisions", "open_items", "open_questions", "links",
    "event", "session_id", "source",
})


def payload_capture() -> tuple[HandoffScope, HandoffFields, str, str, str, str]:
    """Return the validated capture request read from standard input."""
    try:
        payload = _load(sys.stdin.read())
    except (ValueError, UnicodeError) as exc:
        raise HandoffError(f"--json-stdin is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HandoffError("--json-stdin payload must be a JSON object")
    unknown = sorted(set(payload) - _JSON_KEYS)
    if unknown:
        raise HandoffError(f"unknown --json-stdin field: {unknown[0]!r}")
    for name in ("capture_id", "work"):
        if name not in payload:
            raise HandoffError(f"--json-stdin payload requires {name!r}")

    def text(name: str, default: str = "") -> str:
        value = payload.get(name, default)
        if not isinstance(value, str):
            raise HandoffError(f"--json-stdin {name} must be a string")
        return value

    def entries(name: str) -> tuple[str, ...]:
        value = payload.get(name, [])
        if not isinstance(value, list):
            raise HandoffError(f"--json-stdin {name} must be a list of strings")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise HandoffError(
                    f"--json-stdin {name} must be a list of strings")
            result.append(item)
        return tuple(result)

    def key(name: str) -> str | None:
        value = payload.get(name)
        if value is not None and not isinstance(value, str):
            raise HandoffError(f"--json-stdin {name} must be a string or null")
        return value

    scope = required_scope(key("project_key"), key("task_key"))
    fields = HandoffFields(
        work=text("work"), next_step=text("next_step"),
        decisions=entries("decisions"), open_items=entries("open_items"),
        open_questions=entries("open_questions"), links=entries("links"),
    )
    return (scope, fields, text("capture_id"), text("event", "explicit"),
            text("session_id"), text("source", "api"))