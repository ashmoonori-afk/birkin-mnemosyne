"""Lossless resident/topic views derived from one authoritative routing snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Final, Literal

from .memory_triggers import IndexEntry, MemoryIndexError, index_revision

_FLAT_GUIDE: Final = (
    "Always retain every entry, including after compaction. "
    "When a trigger applies, open its document with memory_open_trigger; "
    "use memory_search if no trigger matches."
)
_GROUP_GUIDE: Final = (
    "Retain every topic after compaction. Read matched documents before acting "
    "with memory_startup_read; expand a complete topic with memory_index_read(topic=...)."
)


@dataclass(frozen=True, slots=True)
class TopicSummary:
    """A commitment to all original route pairs in one structural topic."""

    topic: str
    routes: int
    documents: int
    sha256: str


@dataclass(frozen=True, slots=True)
class IndexView:
    enabled: bool
    entries: tuple[IndexEntry, ...]
    context: str
    estimated_tokens: int
    max_tokens: int
    over_budget: bool
    warnings: tuple[str, ...]
    mode: Literal["flat", "grouped", "topic"] = "flat"
    index_sha256: str | None = None
    topic: str | None = None
    topics: tuple[TopicSummary, ...] = ()


def estimated_tokens(text: str) -> int:
    """A declared UTF-8-bytes/4 estimate, not model-specific token accounting."""
    return (len(text.encode("utf-8")) + 3) // 4


def topic_for_document(document: str) -> str:
    parent = PurePosixPath(document).parent.as_posix()
    return f"file:{document}" if parent == "." else f"dir:{parent}"


def _leaf_lines(entries: tuple[IndexEntry, ...]) -> list[str]:
    """Share a document label only when the complete alias row is shorter."""
    plain = [f"- {entry.trigger} -> {entry.document}" for entry in entries]
    documents: dict[str, list[str]] = {}
    for entry in entries:
        documents.setdefault(entry.document, []).append(entry.trigger)
    compact: list[str] = []
    for document, triggers in documents.items():
        rows = [f"- {trigger} -> {document}" for trigger in triggers]
        alias = "- " + json.dumps(
            {"document": document, "triggers": triggers},
            ensure_ascii=False, separators=(",", ":"),
        )
        if len(triggers) > 1 and len(alias.encode("utf-8")) < \
                len("\n".join(rows).encode("utf-8")):
            compact.append(alias)
        else:
            compact.extend(rows)
    return compact if len("\n".join(compact).encode("utf-8")) < \
        len("\n".join(plain).encode("utf-8")) else plain


def _warn(context: str, maximum: int) -> tuple[str, tuple[str, ...]]:
    if estimated_tokens(context) <= maximum:
        return context, ()
    warning = (
        f"Memory INDEX exceeds its {maximum} estimated-token budget "
        "(UTF-8 bytes/4); every entry is retained."
    )
    return context + "WARNING: " + warning + "\n", (warning,)


def render_index_view(
    maximum: int, entries: tuple[IndexEntry, ...], *, topic: str | None = None,
) -> IndexView:
    """Choose a smaller complete representation, never a subset of routes."""
    groups: dict[str, list[IndexEntry]] = {}
    for entry in entries:
        groups.setdefault(topic_for_document(entry.document), []).append(entry)
    summaries: list[TopicSummary] = []
    for name, group in sorted(groups.items()):
        raw = json.dumps(
            sorted((entry.trigger, entry.document) for entry in group),
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        summaries.append(TopicSummary(
            name, len(group), len({entry.document for entry in group}),
            hashlib.sha256(raw).hexdigest(),
        ))
    topics = tuple(summaries)
    revision = index_revision(maximum, entries)
    if topic is not None:
        if topic not in groups:
            raise MemoryIndexError(f"unknown memory INDEX topic: {topic!r}")
        selected = tuple(groups[topic])
        context = "\n".join([
            "# Memory INDEX topic " + json.dumps(topic, ensure_ascii=False),
            f"index_sha256={revision}", *_leaf_lines(selected),
        ]) + "\n"
        context, warnings = _warn(context, maximum)
        return IndexView(
            True, selected, context, estimated_tokens(context), maximum,
            bool(warnings), warnings, mode="topic", index_sha256=revision,
            topic=topic, topics=tuple(item for item in topics if item.topic == topic),
        )
    context = "\n".join(["# Memory INDEX", _FLAT_GUIDE, *_leaf_lines(entries)]) + "\n"
    context, warnings = _warn(context, maximum)
    mode: Literal["flat", "grouped"] = "flat"
    if any(item.documents > 1 for item in topics):
        grouped = "\n".join([
            "# Memory INDEX topics", _GROUP_GUIDE,
            (f"index_sha256={revision} routes={len(entries)} "
             f"documents={len({entry.document for entry in entries})}"),
            *("- " + json.dumps(asdict(item), ensure_ascii=False, separators=(",", ":"))
              for item in topics),
        ]) + "\n"
        grouped, grouped_warnings = _warn(grouped, maximum)
        if estimated_tokens(grouped) < estimated_tokens(context):
            context, warnings, mode = grouped, grouped_warnings, "grouped"
    return IndexView(
        True, entries, context, estimated_tokens(context), maximum,
        bool(warnings), warnings, mode=mode, index_sha256=revision, topics=topics,
    )
