"""Immutable captures, idempotent retries and additive handoff enablement."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path

from .atomic import atomic_create_bytes, atomic_write
from .handoff_records import (
    HandoffError,
    HandoffFields,
    HandoffNote,
    HandoffReceipt,
    HandoffRecord,
    HandoffScope,
    decode_config,
    encode_record,
    record_filename,
    scope_directory,
)
from .handoff_models import HandoffConfig
from .handoff_files import HANDOFFS_DIRECTORY, MAX_RECORD_BYTES, ScopeBatch, read_scope, safe_path
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
# Arbitrary stable threshold: once a scope holds this many active captures the
# receipt warns to run retention rather than silently growing the active set.
_LARGE_HISTORY: int = 20

_STAMP_FORMAT: str = "%Y-%m-%dT%H:%M:%S.%fZ"


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


class HandoffStore:
    """Disk-backed immutable handoff store rooted at ``vault``."""

    def __init__(self, vault: str | Path) -> None:
        self.vault: Path = Path(vault).resolve()
        self.managed_root: Path = self.vault / HANDOFFS_DIRECTORY
        self.config_path: Path = self.vault / HANDOFFS_DIRECTORY / _CONFIG_FILE
        self._lock: VaultLock = VaultLock(self.vault)

    def settings(self) -> HandoffConfig:
        """Typed settings surface for startup/init; reads never write."""
        config = self._read_config()
        if config is not None:
            return config
        return HandoffConfig(False, DEFAULT_MAX_TOKENS)

    def enable(self, *, max_tokens: int | None = None) -> HandoffConfig:
        """Additively enable the store; an existing INDEX keeps its budget."""
        if max_tokens is not None and (
                type(max_tokens) is not int or max_tokens < 1):
            raise HandoffError("max_tokens must be a positive integer")
        with self._lock.hold():
            current = self._read_config()
            if current is None:
                current = HandoffConfig(False, DEFAULT_MAX_TOKENS)
            target = HandoffConfig(True, max_tokens if max_tokens is not None
                            else current.max_tokens)
            if current != target:
                self._write_config(target)
            _ = MemoryIndex(self.vault).enable()
            return target

    def records(
        self, scope: HandoffScope, *, include_archive: bool = False,
    ) -> tuple[HandoffNote, ...]:
        """Active (root) records, plus archived originals when requested.

        Read-only; sorted by recorded_at then full hash. Raises on malformed
        owned Markdown or unsafe (symlinked) paths.
        """
        batch = read_scope(self.vault, scope, include_archive=include_archive)
        notes: tuple[HandoffNote, ...] = batch.active
        if include_archive:
            notes = notes + batch.archived
        return tuple(sorted(notes, key=_note_order))

    def latest(self, scope: HandoffScope) -> HandoffNote | None:
        """Greatest active capture by recorded_at/hash; summaries excluded."""
        active = read_scope(self.vault, scope, include_archive=False).active
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
            _ = self.enable()
            batch = read_scope(self.vault, scope)
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
                    return self._existing_receipt(note, batch)
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
            return self._receipt_for(note, True, active,
                                     self.settings().max_tokens)

    def _read_config(self) -> HandoffConfig | None:
        """None when absent or disabled; fail closed on malformed/symlinked."""
        safe_path(self.vault, self.managed_root)
        safe_path(self.vault, self.config_path)
        if not self.managed_root.exists():
            return None
        try:
            raw = self.config_path.read_bytes()
        except FileNotFoundError:
            return None
        return decode_config(raw)

    def _write_config(self, config: HandoffConfig) -> None:
        safe_path(self.vault, self.managed_root)
        safe_path(self.vault, self.config_path)
        self.managed_root.mkdir(parents=True, exist_ok=True)
        atomic_write(self.config_path, json.dumps(
            {"version": config.version, "enabled": config.enabled,
             "max_tokens": config.max_tokens},
            ensure_ascii=False, separators=(",", ":"),
        ) + "\n")

    def _publish(self, scope: HandoffScope, note: HandoffNote) -> None:
        directory = self.managed_root / scope_directory(scope)
        directory.mkdir(parents=True, exist_ok=True)
        atomic_create_bytes(directory / Path(note.path).name, note.raw)

    def _existing_receipt(
        self, note: HandoffNote, batch: ScopeBatch,
    ) -> HandoffReceipt:
        archived = Path(note.path).parent.name == _ARCHIVE_DIRECTORY
        return self._receipt_for(note, False, batch.active,
                                 self.settings().max_tokens, archived=archived)

    def _receipt_for(
        self, note: HandoffNote, created: bool,
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


def _greatest_capture_stamp(batch: ScopeBatch) -> _dt.datetime | None:
    greatest: _dt.datetime | None = None
    for note in (batch.active + batch.archived):
        if note.record.kind != "capture":
            continue
        stamp = _parse_timestamp(note.record.recorded_at)
        if greatest is None or stamp > greatest:
            greatest = stamp
    return greatest
