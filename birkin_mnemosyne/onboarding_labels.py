"""Label helpers for first-run onboarding plans and their reports.

This module keeps the label-specific seam of onboarding together without
touching the pure label boundary: namespace validation, existing INDEX
trigger lookup, opt-in topic grouping and the label histogram.  It never
mutates bytes, never consults the clock and never calls a provider.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING

from .label_values import LabelError, is_valid_label, normalize_labels

if TYPE_CHECKING:
    from .memory_triggers import IndexEntry
    from .onboarding_notes import Note


def normalize_namespace(namespace: str) -> str:
    """NFC-trim-lower a label namespace, rejecting non-conforming values."""
    normalized = unicodedata.normalize("NFC", namespace).strip().casefold()
    if ":" in normalized or not is_valid_label(f"{normalized}:init"):
        raise LabelError(f"invalid label namespace: {namespace!r}")
    return normalized


def index_topics(entries: tuple[IndexEntry, ...], document: str) -> tuple[str, ...]:
    """Exact existing INDEX triggers routed to one note path, sorted."""
    return tuple(
        sorted({entry.trigger for entry in entries if entry.document == document})
    )


def label_counts(notes: Iterable[Note]) -> tuple[tuple[str, int], ...]:
    """Count each normalized label once per note, preserving value case."""
    counts: Counter[str] = Counter()
    for note in notes:
        counts.update(normalize_labels(note.labels))
    return tuple(sorted(counts.items()))
