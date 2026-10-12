"""Read-only label preview and checked, journaled annotation/replacement.

``plan_labels`` scans the vault without creating a directory, lock, cache or
journal, and captures the exact input bytes, the INDEX routing state and the
planned :class:`LabelEdit` per note.  ``run_labeling`` reports the plan by
default; with ``apply=True`` it holds the shared vault lock, re-checks every
captured image, route and selection against the live vault, and journals only
the actual byte changes with the existing Review change/commit seam, so the
returned transaction is undone with ``Consolidation.undo``.

Generated catalogues, receipt-bound split sources/topics, archives and immutable
managed handoffs are excluded; existing manual labels (including ``[]``) are
user-owned and survive unless an explicit replacement is supplied.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .label_values import normalize_labels
from .labels import LabelContext, LabelEdit, annotate_labels
from .memory_index import NOTICE_PREFIX, IndexEntry, MemoryIndex
from .onboarding_notes import generated_catalogue, inventory
from .onboarding_state import existing_state
from .review_journal import Change, ReviewError, commit
from .vault_lock import VaultLock

Mode = Literal["preview", "applied"]


@dataclass(frozen=True, slots=True)
class LabelPlanNote:
    """One selected note: exact input image, routing state and planned edit."""

    path: str
    raw: bytes
    index_topics: tuple[str, ...]
    edit: LabelEdit


@dataclass(frozen=True, slots=True)
class LabelPlan:
    """Immutable captured plan for a requested label operation."""

    root: Path
    paths: tuple[str, ...] | None
    labels: tuple[str, ...] | None
    notes: tuple[LabelPlanNote, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabelReport:
    """Outcome of previewing or applying a captured :class:`LabelPlan`."""

    mode: Mode
    ok: bool
    notes: int
    changed: int
    warnings: tuple[str, ...]
    label_counts: tuple[tuple[str, int], ...]
    undo_transaction: str | None


def plan_labels(
    root: str | Path,
    *,
    paths: tuple[str, ...] | None = None,
    labels: tuple[str, ...] | None = None,
) -> LabelPlan:
    """Scan and annotate every eligible note without any write.

    ``paths`` restricts selection to those vault-relative note paths;
    ``labels`` supplies an explicit replacement (``()`` clears), while
    ``None`` only annotates notes that have no labels field yet.
    """
    replacement = None if labels is None else normalize_labels(labels)
    resolved = Path(root).resolve()
    index = MemoryIndex(resolved)
    state = existing_state(index)
    entries = state.view.entries
    requested = _validate_paths(index, paths)
    notes: list[LabelPlanNote] = []
    warnings: list[str] = []
    for source in inventory(resolved):
        if (source.path in state.protected or generated_catalogue(source)
                or source.raw.startswith(NOTICE_PREFIX.encode())):
            continue
        if requested is not None and source.path not in requested:
            continue
        topics = _index_topics(entries, source.path)
        edit = annotate_labels(
            source.raw, LabelContext(source.path, topics), labels=replacement
        )
        if edit.warning is not None:
            warnings.append(f"{source.path}: {edit.warning}")
        notes.append(LabelPlanNote(source.path, source.raw, topics, edit))
    if requested is not None:
        found = {note.path for note in notes}
        for path in requested:
            if path not in found:
                warnings.append(f"no eligible note at requested path: {path}")
    return LabelPlan(resolved, requested, replacement, tuple(notes), tuple(warnings))


def run_labeling(plan: LabelPlan, *, apply: bool = False) -> LabelReport:
    """Report the plan, or apply it as one checked, journaled transaction."""
    additions = tuple(note for note in plan.notes if note.edit.raw != note.raw)
    counts = _label_counts(plan)
    mode: Mode = "applied" if apply else "preview"
    if not apply or not additions:
        return LabelReport(
            mode, True, len(plan.notes), len(additions), plan.warnings, counts, None
        )
    with VaultLock(plan.root).hold():
        _check_plan(plan)
        changes = tuple(
            Change(note.path, note.path, note.raw, note.edit.raw) for note in additions
        )
        receipt = commit(
            plan.root, _question_id(additions), "mnemosyne-label", "", "", changes
        )
    return LabelReport(
        mode,
        True,
        len(plan.notes),
        len(changes),
        plan.warnings,
        counts,
        receipt.transaction_id,
    )


def _validate_paths(
    index: MemoryIndex,
    paths: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if paths is None:
        return None
    checked: list[str] = []
    for path in paths:
        _ = index.document_path(path)
        checked.append(path)
    return tuple(checked)


def _index_topics(entries: tuple[IndexEntry, ...], document: str) -> tuple[str, ...]:
    return tuple(
        sorted({entry.trigger for entry in entries if entry.document == document})
    )


def _label_counts(plan: LabelPlan) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for note in plan.notes:
        counts.update(normalize_labels(note.edit.labels))
    return tuple(sorted(counts.items()))


def _question_id(notes: Iterable[LabelPlanNote]) -> str:
    material = b"".join(
        note.path.encode("utf-8") + b"\0" + note.raw + b"\0" + note.edit.raw
        for note in notes
    )
    return "label:" + hashlib.sha256(material).hexdigest()


def _check_plan(plan: LabelPlan) -> None:
    index = MemoryIndex(plan.root)
    state = existing_state(index)
    entries = state.view.entries
    eligible = {
        source.path
        for source in inventory(plan.root)
        if source.path not in state.protected
        and not generated_catalogue(source)
        and not source.raw.startswith(NOTICE_PREFIX.encode())
    }
    planned = {note.path for note in plan.notes}
    if plan.paths is None:
        if eligible != planned:
            raise ReviewError("label selection changed; preview a fresh plan")
    elif eligible & set(plan.paths) != planned:
        raise ReviewError("label selection changed; preview a fresh plan")
    for note in plan.notes:
        path = index.document_path(note.path)
        if not path.is_file() or path.read_bytes() != note.raw:
            raise ReviewError(f"label input changed; preview a fresh plan: {note.path}")
        if _index_topics(entries, note.path) != note.index_topics:
            raise ReviewError(
                f"routing state changed; preview a fresh plan: {note.path}"
            )
