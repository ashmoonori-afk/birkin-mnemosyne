"""Immutable handoff values and their boundary validation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, TypeGuard, TypeVar

Kind = Literal["capture", "summary"]
Event = Literal["explicit", "pre-compress", "session-end", "fold"]
_HEX: Final = re.compile(r"[0-9a-fA-F]{64}")
_STAMP: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z",
)
_T = TypeVar("_T")


class HandoffError(ValueError):
    """A handoff value or file violates its contract."""


def require_type(value: object, expected: type[_T], name: str) -> _T:
    """Narrow dynamically supplied constructor/decoder input at the boundary."""
    if not isinstance(value, expected):
        raise HandoffError(f"{name} must be {expected.__name__}")
    return value


def _tuple(value: object) -> TypeGuard[tuple[object, ...]]:
    return isinstance(value, tuple)


@dataclass(frozen=True, slots=True)
class HandoffConfig:
    """Vault opt-in and soft budget, independent of any active scope."""

    enabled: bool
    max_tokens: int
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise HandoffError("handoff config enabled must be a bool")
        if type(self.max_tokens) is not int or self.max_tokens < 1:
            raise HandoffError("handoff config max_tokens must be a positive integer")
        if type(self.version) is not int or self.version != 1:
            raise HandoffError("handoff config version must be the integer 1")


def _key(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{name} must be a nonblank string")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise HandoffError(f"{name} must not contain control characters")


def _strings(values: object, name: str) -> None:
    if not _tuple(values) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise HandoffError(f"{name} must be a tuple of nonblank strings")


def _hash(value: object) -> None:
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
        work = require_type(self.work, str, "work")
        if not work.strip():
            raise HandoffError("work must be a nonblank string")
        _ = require_type(self.next_step, str, "next_step")
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
        _ = require_type(self.scope, HandoffScope, "scope")
        _ = require_type(self.fields, HandoffFields, "fields")
        stamp = require_type(self.recorded_at, str, "recorded_at")
        if _STAMP.fullmatch(stamp) is None:
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
        _ = require_type(self.session_id, str, "session_id")
        if self.session_id:
            _key(self.session_id, "session_id")
        _key(self.source, "source")
        if not _tuple(self.provenance):
            raise HandoffError("provenance must be a tuple of path/hash pairs")
        for pair in self.provenance:
            if not _tuple(pair) or len(pair) != 2:
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
        _ = require_type(self.record, HandoffRecord, "record")
        _ = require_type(self.raw, bytes, "raw")
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
        _ = require_type(self.capture_id, str, "capture_id")
        if self.capture_id:
            _key(self.capture_id, "capture_id")
        if type(self.estimated_tokens) is not int or self.estimated_tokens < 0:
            raise HandoffError("estimated_tokens must be a non-negative integer")
        _strings(self.warnings, "warnings")


@dataclass(frozen=True, slots=True)
class FoldSource:
    """A retained source image and any reason it was excluded."""

    path: str
    sha256: str
    recorded_at: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FoldResult:
    """A deterministic fold preview or its journaled application receipt."""

    plan_id: str
    accepted: tuple[FoldSource, ...]
    rejected: tuple[FoldSource, ...]
    pinned: FoldSource | None
    summary: str
    summary_sha256: str
    plan_archive_cap: int
    transaction_id: str | None
    state: Literal["preview", "committed", "idempotent", "noop"]
    journal_path: str
