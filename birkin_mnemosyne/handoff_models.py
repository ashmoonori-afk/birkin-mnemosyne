"""Immutable handoff values and their boundary validation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

Kind = Literal["capture", "summary"]
Event = Literal["explicit", "pre-compress", "session-end", "fold"]
_HEX: Final = re.compile(r"[0-9a-fA-F]{64}")
_STAMP: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z",
)


class HandoffError(ValueError):
    """A handoff value or file violates its contract."""


def _key(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{name} must be a nonblank string")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise HandoffError(f"{name} must not contain control characters")


def _strings(values: tuple[str, ...], name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise HandoffError(f"{name} must be a tuple of nonblank strings")


def _hash(value: str) -> None:
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise HandoffError("expected a full SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class HandoffScope:
    """Exact project/task identity; keys are data, never filesystem paths."""

    project_key: str
    task_key: str | None = None

    def __post_init__(self) -> None:
        _key(self.project_key, "project_key")
        if self.task_key is not None:
            _key(self.task_key, "task_key")


@dataclass(frozen=True, slots=True)
class HandoffFields:
    """Verbatim captured fields; only work is required."""

    work: str
    next_step: str = ""
    decisions: tuple[str, ...] = ()
    open_items: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    links: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.work, str) or not self.work.strip():
            raise HandoffError("work must be a nonblank string")
        if not isinstance(self.next_step, str):
            raise HandoffError("next_step must be a string")
        for name, values in (
            ("decisions", self.decisions), ("open_items", self.open_items),
            ("open_questions", self.open_questions), ("links", self.links),
        ):
            _strings(values, name)


@dataclass(frozen=True, slots=True)
class HandoffRecord:
    """A capture or dated summary, independent of its disk location."""

    scope: HandoffScope
    fields: HandoffFields
    kind: Kind
    capture_id: str | None
    recorded_at: str
    event: Event
    session_id: str = ""
    source: str = "api"
    provenance: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.scope, HandoffScope) or not isinstance(self.fields, HandoffFields):
            raise HandoffError("record requires a handoff scope and fields")
        if not isinstance(self.recorded_at, str) or _STAMP.fullmatch(self.recorded_at) is None:
            raise HandoffError("recorded_at must be a fixed-width UTC timestamp")
        try:
            _ = datetime.strptime(self.recorded_at, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError as exc:
            raise HandoffError("recorded_at is not a valid date and time") from exc
        match self.kind, self.event:
            case "capture", ("explicit" | "pre-compress" | "session-end"):
                _key(self.capture_id, "capture_id")
            case "summary", "fold" if self.capture_id is None:
                pass
            case _:
                raise HandoffError("invalid record kind, event or capture identity")
        if not isinstance(self.session_id, str):
            raise HandoffError("session_id must be a string")
        if self.session_id:
            _key(self.session_id, "session_id")
        _key(self.source, "source")
        if not isinstance(self.provenance, tuple):
            raise HandoffError("provenance must be a tuple of path/hash pairs")
        for pair in self.provenance:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise HandoffError("provenance entries must be path/hash pairs")
            _key(pair[0], "provenance path")
            _hash(pair[1])


@dataclass(frozen=True, slots=True)
class HandoffNote:
    """A verified record together with its immutable file image."""

    record: HandoffRecord
    path: str
    raw: bytes
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, HandoffRecord) or not isinstance(self.raw, bytes):
            raise HandoffError("note requires a record and raw bytes")
        _key(self.path, "path")
        _hash(self.sha256)
        if self.sha256 != hashlib.sha256(self.raw).hexdigest():
            raise HandoffError("sha256 does not match the raw bytes")


@dataclass(frozen=True, slots=True)
class HandoffReceipt:
    """Result of an exclusive capture or an identical retry."""

    path: str
    created: bool
    archived: bool
    sha256: str
    capture_id: str
    estimated_tokens: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _key(self.path, "path")
        _hash(self.sha256)
        if type(self.created) is not bool or type(self.archived) is not bool:
            raise HandoffError("receipt flags must be booleans")
        if not isinstance(self.capture_id, str):
            raise HandoffError("capture_id must be a string")
        if self.capture_id:
            _key(self.capture_id, "capture_id")
        if type(self.estimated_tokens) is not int or self.estimated_tokens < 0:
            raise HandoffError("estimated_tokens must be a non-negative integer")
        _strings(self.warnings, "warnings")
