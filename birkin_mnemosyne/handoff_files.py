"""Read-only validation of scoped handoff files, including Windows reparse paths."""

from __future__ import annotations

import stat
from dataclasses import dataclass, replace
from pathlib import Path

from .handoff_records import (
    HandoffError, HandoffNote, HandoffScope, decode_record, scope_directory,
)

HANDOFFS_DIRECTORY = ".mnemosyne-handoffs"
MAX_RECORD_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ScopeBatch:
    active: tuple[HandoffNote, ...]
    archived: tuple[HandoffNote, ...]


def safe_path(vault: Path, path: Path) -> None:
    if path.is_symlink() or not path.resolve().is_relative_to(vault):
        raise HandoffError(f"unsafe handoff path: {path}")
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return
    if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise HandoffError(f"unsafe handoff reparse point: {path}")


def read_scope(
    vault: Path, scope: HandoffScope, *, include_archive: bool = True,
) -> ScopeBatch:
    """Decode the exact requested scope; never create directories or caches."""
    managed = vault / HANDOFFS_DIRECTORY
    directory = managed / scope_directory(scope)
    for location in (managed, directory):
        safe_path(vault, location)
        if location.exists() and not location.is_dir():
            raise HandoffError(f"handoff directory is not a directory: {location}")
    if not directory.exists():
        return ScopeBatch((), ())
    active: list[HandoffNote] = []
    archived: list[HandoffNote] = []
    archive = directory / "archive"
    safe_path(vault, archive)
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
            safe_path(vault, path)
            if path.is_dir():
                if location == directory and path == archive:
                    continue
                raise HandoffError(f"unexpected handoff directory: {path}")
            if path.suffix != ".md":
                continue
            try:
                with path.open("rb") as stream:
                    raw = stream.read(MAX_RECORD_BYTES + 1)
                if len(raw) > MAX_RECORD_BYTES:
                    raise HandoffError("handoff record exceeds its complete-read limit")
                note = decode_record(raw, path.name)
            except HandoffError as exc:
                raise HandoffError(f"cannot read handoff record {path}: {exc}") from exc
            if note.record.scope != scope:
                raise HandoffError(f"handoff record belongs to another scope: {path}")
            identity = note.record.capture_id
            if identity is not None:
                previous = identities.get(identity)
                if previous is not None and previous.record != note.record:
                    raise HandoffError(f"conflicting handoff capture identity: {identity}")
                identities[identity] = note
            notes.append(replace(note, path=path.relative_to(vault).as_posix()))
    return ScopeBatch(tuple(active), tuple(archived))
