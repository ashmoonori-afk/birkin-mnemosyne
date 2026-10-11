"""Capture existing INDEX and recovery authority without writing any state."""

from __future__ import annotations

from dataclasses import dataclass

from .memory_index import MemoryIndex, MemoryIndexError, decode_index_json
from .memory_index_integrity import check_index
from .memory_index_views import IndexView
from .onboarding_notes import SourceBytes
from .review_journal import _decode_manifest


@dataclass(frozen=True, slots=True)
class ExistingState:
    view: IndexView
    files: tuple[SourceBytes, ...]
    protected: frozenset[str]
    recovery: tuple[str, ...]


def existing_state(index: MemoryIndex) -> ExistingState:
    """Validate coverage and retain all receipt-bound source byte identities."""
    view = index.read()
    files: list[SourceBytes] = []
    protected: set[str] = set()
    recovery: list[str] = []
    if view.enabled:
        checked = check_index(index.root)
        if checked.errors:
            raise MemoryIndexError("; ".join(checked.errors))
        files.append(SourceBytes(index.path.relative_to(index.root).as_posix(),
                                 index.path.read_bytes()))
        receipts = index.directory / "splits"
        for path in sorted(receipts.glob("*.json")):
            raw = path.read_bytes()
            files.append(SourceBytes(path.relative_to(index.root).as_posix(), raw))
            match decode_index_json(raw.decode("utf-8")):
                case {"source": str() as source, "topics": list() as topics}:
                    protected.add(source)
                    for topic in topics:
                        match topic:
                            case {"document": str() as document}:
                                protected.add(document)
                            case _:
                                raise MemoryIndexError("invalid split topic authority")
                case _:
                    raise MemoryIndexError("invalid split receipt authority")
    journals = index.root / ".mnemosyne-reviews"
    if journals.is_symlink():
        raise MemoryIndexError("review journal directory must not be a symlink")
    for path in sorted(journals.glob("*.json")):
        if path.is_symlink():
            raise MemoryIndexError("review journal must not be a symlink")
        raw = path.read_bytes()
        files.append(SourceBytes(path.relative_to(index.root).as_posix(), raw))
        record = _decode_manifest(raw.decode("utf-8"))
        if record["state"] in {"prepared", "recovery-required"}:
            recovery.append(path.relative_to(index.root).as_posix())
    return ExistingState(view, tuple(files), frozenset(protected), tuple(recovery))
