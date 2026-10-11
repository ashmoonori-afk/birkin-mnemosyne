"""Canonical Markdown encoding for immutable, exactly scoped handoff records."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from typing import Final, TypeAlias

from .handoff_models import (
    HandoffConfig, HandoffError, HandoffFields, HandoffNote, HandoffReceipt,
    HandoffRecord, HandoffScope, require_type,
)

__all__ = [
    "HandoffError", "HandoffFields", "HandoffNote", "HandoffReceipt", "HandoffRecord",
    "HandoffScope", "decode_record", "encode_record", "record_filename", "scope_directory",
]
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
_load: Callable[[str], JsonValue] = json.loads
_RECORD_KEYS: Final = {
    "version", "scope", "fields", "kind", "capture_id", "recorded_at",
    "event", "session_id", "source", "provenance",
}
_FIELDS_KEYS: Final = {"work", "next_step", "decisions", "open_items", "open_questions", "links"}


def decode_config(raw: bytes) -> HandoffConfig:
    """Parse versioned opt-in settings without accepting unknown fields."""
    try:
        payload = _load(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise HandoffError("handoff config is not valid JSON") from exc
    match payload:
        case {"version": 1, "enabled": bool() as enabled, "max_tokens": int() as maximum} \
                if set(payload) == {"version", "enabled", "max_tokens"} and \
                type(payload["version"]) is int:
            return HandoffConfig(enabled, maximum)
        case _:
            raise HandoffError("handoff config must have version, enabled and max_tokens")


def _strings(values: list[JsonValue]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise HandoffError("handoff field entries must be strings")
        result.append(value)
    return tuple(result)


def _provenance(values: list[JsonValue]) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for value in values:
        match value:
            case [str() as path, str() as digest]:
                result.append((path, digest))
            case _:
                raise HandoffError("provenance must contain path/hash pairs")
    return tuple(result)


def _record(payload: JsonValue) -> HandoffRecord:
    match payload:
        case {
            "version": 1,
            "scope": {"project_key": str() as project, "task_key": (str() | None) as task} as scope,
            "fields": {
                "work": str() as work, "next_step": str() as next_step,
                "decisions": list() as decisions, "open_items": list() as open_items,
                "open_questions": list() as open_questions, "links": list() as links,
            } as fields,
            "kind": ("capture" | "summary") as kind,
            "capture_id": (str() | None) as capture_id,
            "recorded_at": str() as recorded_at,
            "event": ("explicit" | "pre-compress" | "session-end" | "fold") as event,
            "session_id": str() as session_id, "source": str() as source,
            "provenance": list() as provenance,
        }:
            if type(payload["version"]) is not int or set(payload) != _RECORD_KEYS or \
                    set(scope) != {"project_key", "task_key"} or set(fields) != _FIELDS_KEYS:
                raise HandoffError("handoff body does not match its versioned schema")
            return HandoffRecord(
                HandoffScope(project, task),
                HandoffFields(work, next_step, _strings(decisions), _strings(open_items),
                              _strings(open_questions), _strings(links)),
                kind, capture_id, recorded_at, event, session_id, source,
                _provenance(provenance),
            )
        case _:
            raise HandoffError("handoff body does not match its versioned schema")


def _base32(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=").lower()


def _label(key: str, fallback: str) -> str:
    readable = "".join(char for char in key if char.isascii() and (char.isalnum() or char in "-_"))
    return readable.lower()[:6].strip("-_") or fallback


def scope_directory(scope: HandoffScope) -> str:
    """Readable labels plus the full hash of the exact opaque scope."""
    identity = json.dumps([scope.project_key, scope.task_key], ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
    labels = _label(scope.project_key, "proj")
    if scope.task_key is not None:
        labels += "--" + _label(scope.task_key, "task")
    return labels + "--" + _base32(hashlib.sha256(identity).digest())


def encode_record(record: HandoffRecord) -> str:
    """Render readable JSON in a fence that cannot be closed by its payload."""
    body = json.dumps({"version": 1, **asdict(record)}, indent=2,
                      ensure_ascii=False, allow_nan=False)
    fence = "`" * max(3, max(map(len, re.findall(r"`+", body)), default=0) + 1)
    return "\n".join((
        "---", "type: handoff", f"created: {record.recorded_at}",
        f"updated: {record.recorded_at}", "tags: []", "---", "",
        f"{fence}json", body, fence, "",
    ))


def record_filename(record: HandoffRecord, raw: bytes) -> str:
    """Bind the Windows-safe name to kind, UTC timestamp and every raw byte."""
    stamp = record.recorded_at.replace("-", "").replace(":", "").replace(".", "")
    return f"{stamp}--{record.kind}--{_base32(hashlib.sha256(raw).digest())}.md"


def decode_record(raw: bytes, filename: str) -> HandoffNote:
    """Reject unknown, altered or noncanonical images before returning a note."""
    _ = require_type(raw, bytes, "raw")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise HandoffError("handoff bytes are not valid UTF-8") from exc
    # Only ASCII LF separates our format. splitlines() would alter valid JSON
    # string content containing NEL or Unicode line/paragraph separators.
    _, _, fenced = text.partition("\n\n")
    opening, _, body = fenced.partition("\n")
    match = re.fullmatch(r"(`{3,})json", opening)
    if match is None or not body.endswith("\n" + match[1] + "\n"):
        raise HandoffError("handoff body must have a complete JSON fence")
    try:
        payload = _load(body[:-len(match[1]) - 2])
    except ValueError as exc:
        raise HandoffError("handoff body is not valid JSON") from exc
    record = _record(payload)
    # Re-encoding also rejects duplicate keys, altered headers and extra bytes.
    if text != encode_record(record) or filename != record_filename(record, raw):
        raise HandoffError("handoff image or filename is not canonical")
    return HandoffNote(record, filename, raw, hashlib.sha256(raw).hexdigest())
