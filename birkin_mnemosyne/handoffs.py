"""Immutable disk-backed handoff store: capture, scope reads and latest lookup.

Task 3 of the mn-070 handoff feature. This module owns the durable store
layout on top of the frozen record codec (``handoff_records``):

* ``.mnemosyne-handoffs/config.json`` — version-1 opt-in settings with an
  enabled flag and a ``max_tokens`` soft budget (default 2000), never a
  mutable active-scope pointer.
* One directory per scope, named by ``scope_directory()``, holding active
  ``.md`` records at its root and retained originals under ``archive/``.
  Private staging (``.mnemosyne-reviews/`` and other dot-directories) is
  ignored; malformed owned Markdown is refused, never silently skipped.

``capture`` publishes one immutable ``HandoffRecord`` exclusively via
``atomic_create_bytes`` under the vault lock. A repeat of the same request at
the same ``capture_id`` is idempotent and returns the original receipt without
changing bytes or mtimes; a different request at that id conflicts. The server
timestamp is excluded from request identity and is always raised one
microsecond beyond every retained capture timestamp, even after a clock
rollback. Summaries never become ``latest``. Enabling the store on capture is
additive: an existing INDEX keeps every route and budget. Complete record
bytes are capped at 1 MiB before publication.

``records`` and ``latest`` are pure read-only scans: they validate scope
metadata, hashes, canonical bytes and safe non-symlink paths, and create
neither cache nor lock files.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path

from .atomic import atomic_create_bytes, atomic_write
from .handoff_records import (
    HandoffError,
    HandoffFields,
    HandoffNote,
    HandoffReceipt,
    HandoffRecord,
    HandoffScope,
    decode_record,
    encode_record,
    record_filename,
    scope_directory,
)
from .memory_index import DEFAULT_INDEX_TOKENS, MemoryIndex
from .memory_index_views import estimated_tokens
from .vault_lock import VaultLock

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "HANDOFFS_DIRECTORY",
    "LARGE_HISTORY_WARNING",
    "MAX_RECORD_BYTES",
    "SOFT_BUDGET_WARNING",
    "HandoffConfig",
    "HandoffStore",
]

HANDOFFS_DIRECTORY: str = ".mnemosyne-handoffs"
_CONFIG_FILE: str = "config.json"
_ARCHIVE_DIRECTORY: str = "archive"
_SOFT_BUDGET_WARNING: str = (
    "estimated_tokens {estimated} exceed the max_tokens budget {maximum}; "
    "run retention or raise the threshold"
)
_LARGE_HISTORY_WARNING: str = (
    "active history has grown to {count} captures; run retention to fold "
    "older records"
)

SOFT_BUDGET_WARNING: str = _SOFT_BUDGET_WARNING
LARGE_HISTORY_WARNING: str = _LARGE_HISTORY_WARNING
DEFAULT_MAX_TOKENS: int = DEFAULT_INDEX_TOKENS
MAX_RECORD_BYTES: int = 1024 * 1024
# Arbitrary stable threshold: once a scope holds this many active captures the
# receipt warns to run retention rather than silently growing the active set.
_LARGE_HISTORY: int = 20

_STAMP_FORMAT: str = "%Y-%m-%dT%H:%M:%S.%fZ"


class Config:
    """Stored opt-in settings; enabled is never a statement about a scope."""

    __slots__ = ("enabled", "max_tokens", "version")

    def __init__(self, enabled: bool, max_tokens: int, version: int = 1) -> None:
        if type(enabled) is not bool:
            raise HandoffError("handoff config enabled must be a bool")
        if type(max_tokens) is not int or max_tokens < 1:
            raise HandoffError(
                "handoff config max_tokens must be a positive integer")
        if type(version) is not int or version != 1:
            raise HandoffError("handoff config version must be the integer 1")
        self.enabled: bool = enabled
        self.max_tokens: int = max_tokens
        self.version: int = version

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Config):
            return NotImplemented
        return (self.enabled, self.max_tokens, self.version) == \
            (other.enabled, other.max_tokens, other.version)

    def __repr__(self) -> str:
        return (f"Config(enabled={self.enabled!r}, "
                f"max_tokens={self.max_tokens!r}, version={self.version!r})")


# Public alias so ``birkin_mnemosyne.HandoffConfig`` selects the same class
# that ``handoffs.py`` documents as ``Config``.
HandoffConfig = Config


def _format_timestamp(when: _dt.datetime) -> str:
    return when.astimezone(_dt.timezone.utc).strftime(_STAMP_FORMAT)


def _parse_timestamp(value: str) -> _dt.datetime:
    """Parse the fixed-width UTC stamp without silently accepting variants."""
    try:
        return _dt.datetime.strptime(value, _STAMP_FORMAT).replace(
            tzinfo=_dt.timezone.utc)
    except ValueError as exc:
        raise HandoffError(
            "recorded_at must be UTC ISO 'YYYY-MM-DDTHH:MM:SS.ffffffZ'"
        ) from exc


def _coerce_now(now: _dt.datetime | str | None) -> str:
    if now is None:
        return _format_timestamp(_dt.datetime.now(_dt.timezone.utc))
    if isinstance(now, str):
        return _parse_timestamp(now).strftime(_STAMP_FORMAT)
    if isinstance(now, _dt.datetime):
        if now.tzinfo is None:
            raise HandoffError("capture now must be timezone-aware")
        return _format_timestamp(now)
    raise HandoffError("capture now must be a timezone-aware datetime or stamp")


@dataclass(frozen=True, slots=True)
class _ScopeBatch:
    active: tuple[HandoffNote, ...]
    archived: tuple[HandoffNote, ...]


def _parse_config(raw: bytes) -> Config:
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise HandoffError("handoff config must be a JSON object")
        if set(payload) != {"version", "enabled", "max_tokens"}:
            raise HandoffError("handoff config has unknown or missing fields")
        return Config(payload["enabled"], payload["max_tokens"], payload["version"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError("handoff config is not valid JSON") from exc


class HandoffStore:
    """Disk-backed immutable handoff store rooted at ``vault``."""

    def __init__(self, vault: str | Path) -> None:
        self.vault: Path = Path(vault).resolve()
        self.managed_root: Path = self.vault / HANDOFFS_DIRECTORY
        self.config_path: Path = self.vault / HANDOFFS_DIRECTORY / _CONFIG_FILE
        self._lock: VaultLock = VaultLock(self.vault)

    def settings(self) -> Config:
        """Typed settings surface for startup/init; reads never write."""
        config = self._read_config()
        if config is not None:
            return config
        return Config(False, DEFAULT_MAX_TOKENS)

    def enable(self, *, max_tokens: int | None = None) -> Config:
        """Additively enable the store; an existing INDEX keeps its budget."""
        if max_tokens is not None and (
                type(max_tokens) is not int or max_tokens < 1):
            raise HandoffError("max_tokens must be a positive integer")
        with self._lock.hold():
            current = self._read_config()
            if current is None:
                current = Config(False, DEFAULT_MAX_TOKENS)
            target = Config(True, max_tokens if max_tokens is not None
                            else current.max_tokens)
            if current != target:
                self._write_config(target)
            MemoryIndex(self.vault).enable()
            return target

    def records(
        self, scope: HandoffScope, *, include_archive: bool = False,
    ) -> tuple[HandoffNote, ...]:
        """Active (root) records, plus archived originals when requested.

        Read-only; sorted by recorded_at then full hash. Raises on malformed
        owned Markdown or unsafe (symlinked) paths.
        """
        batch = self._read_scope(scope, include_archive=include_archive)
        notes: tuple[HandoffNote, ...] = batch.active
        if include_archive:
            notes = notes + batch.archived
        return tuple(sorted(notes, key=_note_order))

    def latest(self, scope: HandoffScope) -> HandoffNote | None:
        """Greatest active capture by recorded_at/hash; summaries excluded."""
        active = self._read_scope(scope, include_archive=False).active
        captures = [note for note in active
                    if note.record.kind == "capture"]
        if not captures:
            return None
        return max(captures, key=_note_order)

    def warnings_for(self, fields: HandoffFields, *,
                     max_tokens: int | None = None) -> tuple[str, ...]:
        """Prospective capture warnings; ``max_tokens`` defaults to the soft
        budget when omitted."""
        if max_tokens is None:
            max_tokens = self.settings().max_tokens
        estimated = estimated_tokens(encode_record(HandoffRecord(
            HandoffScope("__probe__"), fields, "capture", "__probe__",
            "2026-10-11T00:00:00.000000Z", "explicit",
        )))
        return self._warnings_for(estimated, max_tokens, 0)

    # -- capture -------------------------------------------------------------

    def capture(
        self, scope: HandoffScope, fields: HandoffFields, *,
        capture_id: str, event: str = "explicit", session_id: str = "",
        source: str = "api", now: _dt.datetime | str | None = None,
    ) -> HandoffReceipt:
        """Publish one immutable capture; idempotent for the same request."""
        match event:
            case "explicit" | "pre-compress" | "session-end":
                pass
            case _:
                raise HandoffError("capture requires an explicit or session checkpoint event")
        request_stamp = _coerce_now(now)
        request_time = _parse_timestamp(request_stamp)
        _ = HandoffRecord(
            scope=scope, fields=fields, kind="capture",
            capture_id=capture_id, recorded_at=request_stamp, event=event,
            session_id=session_id, source=source,
        )
        with self._lock.hold():
            self._ensure_enable_write()
            batch = self._read_scope(scope)
            for note in (batch.active + batch.archived):
                if note.record.capture_id == capture_id:
                    stored = note.record
                    if (
                        stored.scope, stored.fields, stored.event,
                        stored.session_id, stored.source,
                    ) != (scope, fields, event, session_id, source):
                        raise HandoffError(
                            f"capture_id {capture_id!r} already holds different "
                            "content for this scope")
                    return self._existing_receipt(scope, note, batch)
            greatest = _greatest_capture_stamp(batch)
            if greatest is not None and request_time <= greatest:
                request_time = greatest + _dt.timedelta(microseconds=1)
            recorded_at = _format_timestamp(request_time)
            record = HandoffRecord(
                scope=scope, fields=fields, kind="capture",
                capture_id=capture_id, recorded_at=recorded_at, event=event,
                session_id=session_id, source=source,
            )
            raw = encode_record(record).encode("utf-8")
            if len(raw) > MAX_RECORD_BYTES:
                raise HandoffError(
                    f"handoff record exceeds the {MAX_RECORD_BYTES}-byte limit")
            note = HandoffNote(
                record=record,
                path=f"{HANDOFFS_DIRECTORY}/{scope_directory(scope)}/"
                f"{record_filename(record, raw)}",
                raw=raw, sha256=hashlib.sha256(raw).hexdigest(),
            )
            self._publish(scope, note)
            active = batch.active + (note,)
            return self._receipt_for(scope, note, True, active,
                                     self.settings().max_tokens)

    def _read_config(self) -> Config | None:
        """None when absent or disabled; fail closed on malformed/symlinked."""
        self._safe_path(self.managed_root)
        self._safe_path(self.config_path)
        if not self.managed_root.exists():
            return None
        try:
            raw = self.config_path.read_bytes()
        except FileNotFoundError:
            return None
        return _parse_config(raw)

    def _write_config(self, config: Config) -> None:
        self._safe_path(self.managed_root)
        self._safe_path(self.config_path)
        self.managed_root.mkdir(parents=True, exist_ok=True)
        atomic_write(self.config_path, json.dumps(
            {"version": config.version, "enabled": config.enabled,
             "max_tokens": config.max_tokens},
            ensure_ascii=False, separators=(",", ":"),
        ) + "\n")

    def _ensure_enable_write(self) -> Path:
        """Opt in additively and prepare the managed root, under VaultLock."""
        self._safe_path(self.managed_root)
        current = self._read_config()
        if current is None:
            current = Config(False, DEFAULT_MAX_TOKENS)
        if not current.enabled or current != Config(
                True, current.max_tokens):
            self._write_config(Config(True, current.max_tokens))
        MemoryIndex(self.vault).enable()
        return self.managed_root

    def _scope_directory(self, scope: HandoffScope) -> Path:
        return self.managed_root / scope_directory(scope)

    def _scope_location(self, scope: HandoffScope) -> Path:
        path = self._scope_directory(scope)
        for directory in (self.managed_root, path):
            self._safe_path(directory)
            if directory.exists() and not directory.is_dir():
                raise HandoffError(f"handoff directory is not a directory: {directory}")
        return path

    def _safe_path(self, path: Path) -> None:
        if path.is_symlink() or not path.resolve().is_relative_to(self.vault):
            raise HandoffError(f"unsafe handoff path: {path}")
        try:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            return
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise HandoffError(f"unsafe handoff reparse point: {path}")

    def _decode_file(self, path: Path) -> HandoffNote:
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                raise HandoffError("handoff record exceeds its complete-read limit")
            note = decode_record(raw, path.name)
        except HandoffError as exc:
            raise HandoffError(f"cannot read handoff record {path}: {exc}") from exc
        return note

    def _read_scope(
        self, scope: HandoffScope, *, include_archive: bool = True,
    ) -> _ScopeBatch:
        directory = self._scope_location(scope)
        if not directory.exists():
            return _ScopeBatch((), ())
        active: list[HandoffNote] = []
        archived: list[HandoffNote] = []
        archive = directory / _ARCHIVE_DIRECTORY
        self._safe_path(archive)
        locations = [(directory, active)]
        if include_archive:
            locations.append((archive, archived))
        identities: dict[str, HandoffNote] = {}
        for location, notes in locations:
            if not location.exists():
                continue
            for path in sorted(location.iterdir()):
                if path.name.startswith("."):
                    continue
                self._safe_path(path)
                if path.is_dir():
                    if location == directory and path == archive:
                        continue
                    raise HandoffError(f"unexpected handoff directory: {path}")
                if path.suffix != ".md":
                    continue
                note = self._decode_file(path)
                if note.record.scope != scope:
                    raise HandoffError(f"handoff record belongs to another scope: {path}")
                identity = note.record.capture_id
                if identity is not None:
                    previous = identities.get(identity)
                    if previous is not None and previous.record != note.record:
                        raise HandoffError(f"conflicting handoff capture identity: {identity}")
                    identities[identity] = note
                notes.append(self._with_note_path(
                    note, path.relative_to(self.vault).as_posix(),
                ))
        return _ScopeBatch(tuple(active), tuple(archived))

    def _with_note_path(self, note: HandoffNote, relative: str) -> HandoffNote:
        return HandoffNote(record=note.record, path=relative, raw=note.raw,
                           sha256=note.sha256)

    def _publish(self, scope: HandoffScope, note: HandoffNote) -> None:
        directory = self._scope_directory(scope)
        directory.mkdir(parents=True, exist_ok=True)
        atomic_create_bytes(directory / Path(note.path).name, note.raw)

    def _existing_receipt(
        self, scope: HandoffScope, note: HandoffNote, batch: _ScopeBatch,
    ) -> HandoffReceipt:
        archived = Path(note.path).parent.name == _ARCHIVE_DIRECTORY
        return self._receipt_for(scope, note, False, batch.active,
                                 self.settings().max_tokens, archived=archived)

    def _receipt_for(
        self, scope: HandoffScope, note: HandoffNote, created: bool,
        active: tuple[HandoffNote, ...], maximum: int,
        *, archived: bool = False,
    ) -> HandoffReceipt:
        warnings = self._warnings_for(
            estimated_tokens(note.raw.decode("utf-8")), maximum, len(active))
        capture_id = note.record.capture_id
        assert capture_id is not None
        return HandoffReceipt(
            path=note.path, created=created, archived=archived,
            sha256=note.sha256, capture_id=capture_id,
            estimated_tokens=estimated_tokens(note.raw.decode("utf-8")),
            warnings=warnings,
        )

    def _warnings_for(
        self, estimated: int, maximum: int, active_count: int,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if estimated > maximum:
            warnings.append(_SOFT_BUDGET_WARNING.format(
                estimated=estimated, maximum=maximum))
        if active_count > _LARGE_HISTORY:
            warnings.append(_LARGE_HISTORY_WARNING.format(count=active_count))
        return tuple(warnings)


def _note_order(note: HandoffNote) -> tuple[str, str]:
    return (note.record.recorded_at, note.sha256)


def _greatest_capture_stamp(batch: _ScopeBatch) -> _dt.datetime | None:
    greatest: _dt.datetime | None = None
    for note in (batch.active + batch.archived):
        if note.record.kind != "capture":
            continue
        stamp = _parse_timestamp(note.record.recorded_at)
        if greatest is None or stamp > greatest:
            greatest = stamp
    return greatest
