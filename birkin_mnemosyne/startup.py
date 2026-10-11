"""Lossless startup bundles: every source line, fresh SHA checks, no semantic cuts.

A project/task scope additionally seeds the latest active handoff capture and a
synthetic scope receipt under the vault-before-reader lock ordering, then
verifies them like every other source byte.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypeAlias

from .handoff_records import HandoffError, HandoffNote, HandoffScope
from .handoffs import HandoffStore
from .memory_index import (
    INDEX_DIRECTORY,
    INDEX_SOURCE,
    IndexEntry,
    MemoryIndex,
    estimated_tokens,
)
from .memory_index_views import render_index_view, topic_for_document
from .memory_triggers import match_entries
from .startup_coverage import (
    Coverage,
    FileRecord,
    digest,
    verify_context,
)
from .startup_coverage import StartupError as StartupError
from .startup_sources import active_lines as active_lines, source_blocks as source_blocks, references
from .startup_handoffs import (
    HANDOFF_SCOPE_SOURCE, handoff_scope, handoff_receipt, handoff_warnings, scope_manager,
)

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
_json: Callable[[str], JsonValue] = json.loads


@dataclass(frozen=True, slots=True)
class StartupBundle:
    context: str
    coverage: Coverage
    cache_hit: bool
    estimated_tokens: int = 0
    matched_entries: tuple[IndexEntry, ...] = ()


def _include_source(sources: dict[str, bytes], path: str, data: bytes) -> None:
    if len(sources) >= 64:
        raise StartupError("startup bundle exceeds the 64-file budget")
    if len(data) > 1_048_576 or sum(len(value) for value in sources.values()) + len(data) > 2_097_152:
        raise StartupError("startup bundle exceeds its complete-read byte budget")
    sources[path] = data


class StartupReader:
    """Bounded derived cache; every call rereads all local source bytes.

    A project/task scope additionally seeds the latest active handoff capture
    and its binding receipt from the memory INDEX root, under the
    vault-before-reader lock ordering.
    """

    def __init__(self, root: str | Path, *, memory_index_root: str | Path | None = None,
                 require_index: bool = False) -> None:
        self.root: Path = Path(root).resolve()
        self.memory_index: MemoryIndex = MemoryIndex(
            self.root if memory_index_root is None else memory_index_root,
            required=require_index,
        )
        self._lock: threading.RLock = threading.RLock()
        self._key: tuple[tuple[str, str], ...] = ()
        self._context: str = ""
        self._handoffs: HandoffStore | None = None

    def _handoff_store(self) -> HandoffStore:
        """Disk-backed store rooted at the memory INDEX root, never identity."""
        if self._handoffs is None:
            self._handoffs = HandoffStore(self.memory_index.root)
        return self._handoffs

    def _sources(
        self, paths: Sequence[str], task: str | None, scope: HandoffScope | None,
    ) -> tuple[dict[str, bytes], tuple[IndexEntry, ...], HandoffNote | None]:
        if isinstance(paths, str):
            raise StartupError("supply a nonempty list of startup paths")
        handoff: HandoffNote | None = None
        if scope is not None:
            store = self._handoff_store()
            try:
                handoff = store.latest(scope)
                if handoff is not None or store.settings().enabled:
                    self.memory_index.required = True
            except HandoffError as exc:
                raise StartupError(str(exc)) from exc
        index = self.memory_index.read()
        if not paths and not index.enabled:
            raise StartupError("supply a nonempty list of startup paths")
        matches = match_entries(index.entries, task) if task is not None else ()
        for path in paths:
            if any(part in {".", ".."} or part.startswith(".")
                   for part in path.replace("\\", "/").split("/")):
                raise StartupError(f"refusing hidden path {path!r}")
        pending = [self.root / path for path in paths]
        sources: dict[str, bytes] = (
            {INDEX_SOURCE: index.context.encode("utf-8")} if index.enabled else {}
        )
        if sum(len(data) for data in sources.values()) > 1_048_576:
            raise StartupError("complete memory INDEX exceeds the startup byte budget")
        if scope is not None:
            if handoff is not None:
                _include_source(sources, handoff.path, handoff.raw)
            _include_source(sources, HANDOFF_SCOPE_SOURCE,
                            handoff_receipt(scope, handoff))
        if task is not None:
            receipt = {
                "version": 1, "matcher": "lexical-v2",
                "task_sha256": digest(task.encode("utf-8")),
                "index_sha256": index.index_sha256,
                "matches": [(entry.trigger, entry.document) for entry in matches],
            }
            _include_source(sources, f"{INDEX_DIRECTORY}/task", json.dumps(
                receipt, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8"))
        while pending:
            path = pending.pop(0).resolve()
            if not path.is_relative_to(self.root):
                raise StartupError("required startup file is outside the configured root")
            relative = path.relative_to(self.root).as_posix()
            if any(part.startswith(".") for part in relative.split("/")):
                raise StartupError(f"refusing hidden path {relative!r}")
            if relative in sources:
                continue
            if len(sources) >= 64:
                raise StartupError("startup bundle exceeds the 64-file budget")
            with path.open("rb") as handle:
                data = handle.read(1_048_577)
            _include_source(sources, relative, data)
            text = data.decode("utf-8")
            for reference in references(relative, text):
                pending.append(path.parent / reference)
        if index.mode == "grouped" and matches:
            selected_topics = {topic_for_document(entry.document) for entry in matches}
            for summary in index.topics:
                if summary.topic in selected_topics:
                    leaf = render_index_view(index.max_tokens, index.entries, topic=summary.topic)
                    label = f"{INDEX_DIRECTORY}/topic/{digest(summary.topic.encode('utf-8'))}"
                    _include_source(sources, label, leaf.context.encode("utf-8"))
        for relative in dict.fromkeys(entry.document for entry in matches):
            path = self.memory_index.document_path(relative)
            label = relative if self.root == self.memory_index.root else \
                f"{INDEX_DIRECTORY}/documents/{relative}"
            if label in sources:
                continue
            if len(sources) >= 64:
                raise StartupError("startup bundle exceeds the 64-file budget")
            with path.open("rb") as handle:
                data = handle.read(1_048_577)
            _include_source(sources, label, data)
        return sources, matches, handoff

    def read(
        self, paths: Sequence[str], *, task: str | None = None,
        project_key: str | None = None, task_key: str | None = None,
    ) -> StartupBundle:
        """Return all material or raise; verify final context against fresh source bytes."""
        from .memory_index_integrity import consistency_warnings

        scope = handoff_scope(project_key, task_key)
        with scope_manager(self.memory_index.root, scope), self._lock:
            sources, matches, handoff = self._sources(paths, task, scope)
            key = tuple((path, digest(data)) for path, data in sources.items())
            hit = key == self._key and bool(self._context)
            if not hit:
                files: list[FileRecord] = [{
                    "path": path, "sha256": digest(data), "bytes": len(data),
                    "lines": len(data.decode("utf-8").splitlines(keepends=True)),
                } for path, data in sources.items()]
                blocks = [block for path, data in sources.items() for block in source_blocks(path, data)]
                payload: dict[str, object] = {
                    "version": 1, "complete": True, "files": files, "blocks": blocks,
                }
                if scope is not None:
                    payload["handoff_path"] = (
                        handoff.path if handoff is not None else None)
                    payload["handoff_tokens"] = (
                        estimated_tokens(handoff.raw.decode("utf-8"))
                        if handoff is not None else 0)
                self._context = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"))
                self._key = key
            warnings = (
                *consistency_warnings(self.memory_index),
                *handoff_warnings(
                    self._handoff_store() if scope is not None else None, handoff),
            )
            coverage = replace(
                verify_context(self._context, sources),
                warnings=warnings,
            )
            if not coverage.complete:
                raise StartupError("returned startup context failed byte/line coverage")
            return StartupBundle(
                self._context, coverage, hit, estimated_tokens(self._context), matches)

    def verify(
        self, context: str, paths: Sequence[str], *, task: str | None = None,
        project_key: str | None = None, task_key: str | None = None,
    ) -> Coverage:
        """Independently read the requested closure; reject altered/missing/foreign blocks."""
        from .memory_index_integrity import consistency_warnings

        scope = handoff_scope(project_key, task_key)
        with scope_manager(self.memory_index.root, scope), self._lock:
            sources, _, _ = self._sources(paths, task, scope)
            coverage = replace(
                verify_context(context, sources),
                warnings=consistency_warnings(self.memory_index),
            )
            if not coverage.complete:
                return coverage
            expected = self.read(
                paths, task=task, project_key=project_key, task_key=task_key,
            ).context
            if _json(context) != _json(expected):
                return Coverage(False, coverage.files, coverage.lines, coverage.bytes,
                                ("derived-index-or-order",), coverage.warnings)
            return coverage
