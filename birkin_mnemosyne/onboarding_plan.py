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
from .handoff_models import HandoffConfig, HandoffError, require_type
from .handoffs import HandoffStore
from .import_candidates import destination_name, scan_import
from .label_frontmatter import without_label_field
from .label_values import LabelError
from .memory_index import (
    NOTICE_PREFIX,
    JsonValue,
    MemoryIndex,
    MemoryIndexError,
    validate_index_budget,
)
from .memory_index_views import IndexView, render_index_view
from .memory_triggers import IndexEntry
from .onboarding_labels import index_topics, label_counts, normalize_namespace
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
    root: Path
    source: Path
    preimage: bytes
    destination: SourceBytes
    existing: bytes | None
    source_label: str
    format: str
    warning: str | None


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
    label_counts: tuple[tuple[str, int], ...]
    import_root: Path | None = None


def plan_init(
    root: str | Path, *, import_dir: str | Path | None = None,
    max_tokens: int | None = None, enable_handoff: bool = False,
    group_by_label: str | None = None,
) -> InitPlan:
    """Capture an offline plan without creating a vault, lock, cache or journal."""
    try:
        _ = require_type(enable_handoff, bool, "enable_handoff")
    except HandoffError as exc:
        raise MemoryIndexError("enable_handoff must be a boolean") from exc
    if group_by_label is not None:
        try:
            _ = require_type(group_by_label, str, "group_by_label")
            group_by_label = normalize_namespace(group_by_label)
        except (HandoffError, LabelError) as exc:
            raise MemoryIndexError("group_by_label must be a label namespace") from exc
    index = MemoryIndex(root)
    originals = inventory(index.root)
    handoff_config = HandoffStore(index.root).settings()
    state = existing_state(index)
    maximum = state.view.max_tokens if max_tokens is None else validate_index_budget(max_tokens)
    cached_topics: dict[str, tuple[str, ...]] = {}

    def topics_for(document: str) -> tuple[str, ...]:
        topics = cached_topics.get(document)
        if topics is None:
            topics = index_topics(state.view.entries, document)
            cached_topics[document] = topics
        return topics

    sources = {source.path: source for source in originals}
    copies: list[ImportCopy] = []
    warnings: list[str] = []
    import_root: Path | None = None
    if import_dir is not None:
        requested = Path(import_dir)
        import_root = requested.absolute()
        external = requested.resolve()
        vault_root = index.root.resolve()
        if external.is_relative_to(vault_root) or (
                external.is_dir() and vault_root.is_relative_to(external)):
            raise MemoryIndexError("import path must exist outside the vault without overlap")
        candidates = scan_import(requested)
        identity = unicodedata.normalize("NFC", os.path.normcase(str(external))).encode("utf-8")
        namespace = f"imports/init-{digest(identity)}"
        for candidate in candidates:
            destination = SourceBytes(
                f"{namespace}/{destination_name(candidate.relative)}", candidate.raw)
            previous = sources.get(destination.path)
            expected = describe_note(
                destination, index_topics=topics_for(destination.path),
                label_source=candidate.relative, label_format=candidate.format)
            if previous is not None and previous.raw not in {candidate.raw, expected.normalized}:
                if without_label_field(previous.raw) != without_label_field(expected.normalized):
                    raise MemoryIndexError(f"import destination changed: {destination.path}")
            source = external if external.is_file() else external / candidate.relative
            copies.append(ImportCopy(external, source, candidate.preimage, destination,
                                     previous.raw if previous is not None else None,
                                     candidate.relative, candidate.format, candidate.warning))
            if previous is None:
                sources[destination.path] = destination
            if candidate.warning is not None:
                warnings.append(candidate.warning)
    identities: set[str] = set()
    notes: list[Note] = []
    import_by_path: dict[str, ImportCopy] = {copy.destination.path: copy for copy in copies}
    for source in sorted(sources.values(), key=lambda item: item.path):
        _ = index.document_path(source.path)
        identity = unicodedata.normalize("NFC", source.path).casefold()
        if identity in identities:
            raise MemoryIndexError(f"ambiguous destination identity: {source.path}")
        identities.add(identity)
        if generated_catalogue(source) or source.raw.startswith(NOTICE_PREFIX.encode()):
            continue
        import_copy = import_by_path.get(source.path)
        note = describe_note(
            source, protected=source.path in state.protected,
            index_topics=topics_for(source.path), group_by_label=group_by_label,
            label_source=import_copy.source_label if import_copy is not None else None,
            label_format=import_copy.format if import_copy is not None else None,
        )
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
        if note.warning is not None:
            continue
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
        enable_handoff, handoff_config, label_counts(notes), import_root,
    )
