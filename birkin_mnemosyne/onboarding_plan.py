"""Read-only, path-keyed plans for explicit first-run onboarding."""

from __future__ import annotations

import os
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from . import frontmatter
from .consolidation import NoteSnapshot, Question, questions_from_snapshots
from .handoff_models import HandoffConfig
from .handoffs import HandoffStore
from .memory_index import (
    NOTICE_PREFIX,
    JsonValue,
    MemoryIndex,
    MemoryIndexError,
    validate_index_budget,
)
from .memory_index_views import IndexView, render_index_view
from .memory_triggers import IndexEntry
from .onboarding_notes import (
    Note,
    SourceBytes,
    catalogue,
    describe_note,
    generated_catalogue,
    inventory,
)
from .onboarding_state import ExistingState, existing_state
from .startup_coverage import digest


@dataclass(frozen=True, slots=True)
class ImportCopy:
    source: Path
    destination: SourceBytes
    existing: bytes | None


@dataclass(frozen=True, slots=True)
class InitPlan:
    root: Path
    originals: tuple[SourceBytes, ...]
    notes: tuple[Note, ...]
    imports: tuple[ImportCopy, ...]
    catalogues: tuple[SourceBytes, ...]
    routes: tuple[IndexEntry, ...]
    state: ExistingState
    projected: IndexView
    questions: tuple[Question, ...]
    questions_truncated: bool
    warnings: tuple[str, ...]
    enable_handoff: bool
    handoff_config: HandoffConfig


def plan_init(
    root: str | Path, *, import_dir: str | Path | None = None,
    max_tokens: int | None = None, enable_handoff: bool = False,
) -> InitPlan:
    """Capture an offline plan without creating a vault, lock, cache or journal."""
    if type(enable_handoff) is not bool:
        raise MemoryIndexError("enable_handoff must be a boolean")
    index = MemoryIndex(root)
    originals = inventory(index.root)
    handoff_config = HandoffStore(index.root).settings()
    state = existing_state(index)
    maximum = state.view.max_tokens if max_tokens is None else validate_index_budget(max_tokens)
    sources = {source.path: source for source in originals}
    copies: list[ImportCopy] = []
    if import_dir is not None:
        external = Path(import_dir).resolve()
        if not external.is_dir() or external.is_relative_to(index.root) or \
                index.root.is_relative_to(external):
            raise MemoryIndexError("import directory must exist outside the vault without overlap")
        identity = unicodedata.normalize("NFC", os.path.normcase(str(external))).encode("utf-8")
        namespace = f"imports/init-{digest(identity)}"
        for source in inventory(external):
            destination = SourceBytes(f"{namespace}/{source.path}", source.raw)
            previous = sources.get(destination.path)
            expected = describe_note(destination)
            if previous is not None and previous.raw not in {source.raw, expected.normalized}:
                raise MemoryIndexError(f"import destination changed: {destination.path}")
            copies.append(ImportCopy(external / source.path, destination,
                                     previous.raw if previous is not None else None))
            if previous is None:
                sources[destination.path] = destination
    identities: set[str] = set()
    notes: list[Note] = []
    warnings: list[str] = []
    for source in sorted(sources.values(), key=lambda item: item.path):
        _ = index.document_path(source.path)
        identity = unicodedata.normalize("NFC", source.path).casefold()
        if identity in identities:
            raise MemoryIndexError(f"ambiguous destination identity: {source.path}")
        identities.add(identity)
        if generated_catalogue(source) or source.raw.startswith(NOTICE_PREFIX.encode()):
            continue
        note = describe_note(source, protected=source.path in state.protected)
        notes.append(note)
        if note.warning is not None:
            warnings.append(f"{note.path}: {note.warning}")
    groups: dict[str, list[Note]] = defaultdict(list)
    for note in notes:
        groups[note.topic].append(note)
    catalogues = tuple(catalogue(topic, tuple(members)) for topic, members in sorted(groups.items()))
    routes: list[IndexEntry] = []
    for (topic, members), document in zip(sorted(groups.items()), catalogues):
        previous = sources.get(document.path)
        if previous is not None and previous.raw != document.raw:
            raise MemoryIndexError(f"catalogue destination changed: {document.path}")
        routes.append(IndexEntry(topic, document.path))
        for note in members:
            routes.extend((IndexEntry(topic, note.path), IndexEntry(note.title, note.path)))
    routes = list(dict.fromkeys(routes))
    entries = tuple(dict.fromkeys((*state.view.entries, *routes)))
    projected = render_index_view(maximum, entries)
    snapshots: list[NoteSnapshot] = []
    today = datetime.now(timezone.utc).date()
    for note in notes:
        meta: dict[str, JsonValue]
        meta, body = frontmatter.parse(note.raw.decode("utf-8-sig"))
        expiry = meta.get("expires_at")
        if expiry:
            try:
                expires = date.fromisoformat(str(expiry))
            except ValueError:
                warnings.append(f"{note.path}: invalid expiry retained")
            else:
                if expires < today:
                    continue
        sources_meta = meta.get("sources")
        match sources_meta:
            case list() as values:
                references = tuple(str(value) for value in values)
            case _:
                references = ()
        snapshots.append(NoteSnapshot(note.path, note.title, digest(note.raw), body.strip(), references))
    candidates = questions_from_snapshots(snapshots, limit=21)
    warnings.extend(f"checked recovery required before apply: {path}" for path in state.recovery)
    warnings.extend(projected.warnings)
    return InitPlan(
        index.root, originals, tuple(notes), tuple(copies), catalogues, tuple(routes),
        state, projected, candidates[:20], len(candidates) > 20, tuple(warnings),
        enable_handoff, handoff_config,
    )
