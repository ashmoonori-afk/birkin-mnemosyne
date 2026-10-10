"""Measure real topic responses and reject lost, duplicated or hidden routes."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Protocol, runtime_checkable

from birkin_mnemosyne.memory_index import IndexEntry, MemoryIndex


class _Topic(Protocol):
    @property
    def topic(self) -> str: ...

    @property
    def routes(self) -> int: ...

    @property
    def documents(self) -> int: ...

    @property
    def sha256(self) -> str: ...


@runtime_checkable
class _GroupedView(Protocol):
    @property
    def mode(self) -> str: ...

    @property
    def topics(self) -> Sequence[_Topic]: ...


def _grouped_view(view: object) -> _GroupedView | None:
    """Probe the loaded product, including the older release's view type."""
    return view if isinstance(view, _GroupedView) else None


def measure_topics(
    index: MemoryIndex, expected: Sequence[IndexEntry],
    counter: Callable[[str], dict[str, int]],
) -> dict[str, object]:
    view = index.read()
    grouped = _grouped_view(view)
    if grouped is None:
        return {
            "mode": None, "topic_count": None, "all_routes_expandable": None,
            "all_topics_in_resident": None, "topic_payloads": [],
        }
    if "topic" not in inspect.signature(index.read).parameters:
        raise TypeError("topic-aware MemoryIndex.read is required")
    expanded: list[IndexEntry] = []
    complete = True
    payloads: list[dict[str, object]] = []
    for topic in grouped.topics:
        leaf = index.read(topic=topic.topic)
        raw = json.dumps(sorted((entry.trigger, entry.document) for entry in leaf.entries),
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        complete = complete and (
            leaf.mode == "topic" and leaf.topic == topic.topic
            and leaf.index_sha256 == view.index_sha256
            and len(leaf.entries) == topic.routes
            and len({entry.document for entry in leaf.entries}) == topic.documents
            and hashlib.sha256(raw).hexdigest() == topic.sha256
        )
        expanded.extend(leaf.entries)
        payloads.append({
            "topic": topic.topic, "routes": len(leaf.entries),
            "documents": len({entry.document for entry in leaf.entries}),
            "rendered_topic": counter(leaf.context),
            "serialized_view": counter(json.dumps(
                asdict(leaf), ensure_ascii=False, separators=(",", ":"),
            )),
        })
    complete = complete and len(expanded) == len(expected) and set(expanded) == set(expected)
    return {
        "mode": grouped.mode, "topic_count": len(grouped.topics),
        "all_routes_expandable": complete,
        "all_topics_in_resident": all(
            view.context.count(json.dumps(topic.topic, ensure_ascii=False)) == 1
            for topic in grouped.topics
        ) if grouped.mode == "grouped" else None,
        "topic_payloads": payloads,
    }
