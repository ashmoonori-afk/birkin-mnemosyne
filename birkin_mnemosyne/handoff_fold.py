"""Fresh full-vault snapshots and deterministic summaries for handoff retention."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .handoff_files import HANDOFFS_DIRECTORY, MAX_RECORD_BYTES, read_scope, safe_path
from .handoff_records import (
    HandoffError, HandoffFields, HandoffNote, HandoffRecord, HandoffScope,
    decode_record, encode_record, scope_directory,
)
from .handoffs import _note_order
from .mnemosyne import ARCHIVE_ZONE, Mnemosyne, _note_entry

_HANDOFF_ZONE = "_handoff"
_ARCHIVE_DIRECTORY = "archive"
_FOLD_SOURCE = "retention"
_RECORD_TYPE = "handoff"

def _snapshot(vault: Path, dex: Mnemosyne,
              managed: tuple[HandoffNote, ...]) -> dict[str, dict[str, Any]]:
    """Fresh shallow normal-note snapshot plus every managed active record."""
    snap: dict[str, dict[str, Any]] = {}
    for _slug, (rel, _mtime, _size) in dex._scan().items():
        entry = _note_entry(vault / rel, rel)
        if entry is None or (entry["zone"] or "") == ARCHIVE_ZONE:
            continue
        snap[_slug] = {key: entry[key]
                       for key in ("zone", "type", "polarity", "links")}
    for note in managed:
        entry = _note_entry(vault / note.path, note.path)
        if entry is None:
            raise HandoffError(f"cannot read handoff metadata: {note.path}")
        snap[note.path] = {
            "zone": _HANDOFF_ZONE,
            "type": _RECORD_TYPE,
            "polarity": "positive",
            "links": tuple(sorted(set(note.record.fields.links) | set(entry["links"]))),
        }
    return snap


def _managed_active_notes(vault: Path) -> tuple[HandoffNote, ...]:
    """Every validated active managed record, across all scopes, oldest first.

    Each scope directory is identified from a record it owns and the whole
    directory is then re-validated through the store's public read path, so
    malformed owned Markdown, misplaced or conflicting records and unsafe
    (symlinked) paths fail closed exactly like the store.
    """
    root = vault / HANDOFFS_DIRECTORY
    safe_path(vault, root)
    if not root.exists():
        return ()
    notes: list[HandoffNote] = []
    for directory in sorted(root.iterdir()):
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        safe_path(vault, directory)
        scope = _scope_of_directory(vault, directory)
        if scope is not None:
            notes.extend(read_scope(vault, scope,
                                    include_archive=False).active)
    return tuple(sorted(notes, key=_note_order))


def _scope_of_directory(vault: Path, directory: Path) -> HandoffScope | None:
    """Learn a directory's scope from a record it owns; None when empty."""
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            if path.name == _ARCHIVE_DIRECTORY:
                continue
            raise HandoffError(f"unexpected handoff directory: {path}")
        if path.suffix != ".md":
            continue
        safe_path(vault, path)
        with path.open("rb") as stream:
            raw = stream.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise HandoffError(
                f"handoff record exceeds its complete-read limit: {path}")
        note = decode_record(raw, path.name)
        if scope_directory(note.record.scope) != directory.name:
            raise HandoffError(f"handoff record belongs to another scope: {path}")
        return note.record.scope
    return None


def _fold_summary(
    scope: HandoffScope, accepted: tuple[HandoffNote, ...],
) -> tuple[HandoffRecord | None, bytes]:
    """Deterministic summary over the accepted sources; empty set yields nothing.

    All six field families are preserved with exact values deduplicated in
    first-seen order, dated by the newest included source, and provenanced to
    every accepted path/full hash so the bytes are canonical.
    """
    if not accepted:
        return None, b""

    def _lines(values: list[str]) -> str:
        return "\n".join(dict.fromkeys(value for value in values if value))

    def _values(family: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            value for note in accepted
            for value in getattr(note.record.fields, family)))

    newest = max(accepted, key=_note_order)
    record = HandoffRecord(
        scope=scope,
        fields=HandoffFields(
            work=_lines([note.record.fields.work for note in accepted]),
            next_step=_lines([note.record.fields.next_step
                              for note in accepted]),
            decisions=_values("decisions"),
            open_items=_values("open_items"),
            open_questions=_values("open_questions"),
            links=_values("links"),
        ),
        kind="summary", capture_id=None, recorded_at=newest.record.recorded_at,
        event="fold", session_id="", source=_FOLD_SOURCE,
        provenance=tuple((note.path, note.sha256) for note in accepted),
    )
    raw = encode_record(record).encode("utf-8")
    if len(raw) > MAX_RECORD_BYTES:
        raise HandoffError("fold summary exceeds the complete-read byte limit; fold fewer records")
    return record, raw
