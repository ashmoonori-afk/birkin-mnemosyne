"""Lossless startup bundles: every source line, fresh SHA checks, no semantic cuts."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeAlias

from .identity_reader import parse_sections
from .startup_coverage import (
    BlockRecord,
    Coverage,
    FileRecord,
    StartupPayload,
    block_anchor,
    digest,
    verify_context,
)

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
_json: Callable[[str], JsonValue] = json.loads


class StartupError(ValueError):
    """A complete startup claim cannot be made."""


@dataclass(frozen=True, slots=True)
class StartupBundle:
    context: str
    coverage: Coverage
    cache_hit: bool


def active_lines(text: str) -> Generator[str, None, None]:
    """Outside-fence lines for literal declarations, never for coverage filtering."""
    fence, width = "", 0
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, rest = marker.groups()
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width and not rest.strip():
                fence = ""
            continue
        if not fence:
            yield line


def _references(path: str, text: str) -> tuple[str, ...]:
    if path.lower().endswith(".json"):
        try:
            value = _json(text.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise StartupError(f"invalid JSON startup file: {path}") from exc
        match value:
            case dict():
                declared = value.get("must_read", [])
                match declared:
                    case list():
                        if any(not isinstance(ref, str) for ref in declared):
                            raise StartupError("JSON must_read requires local path strings")
                        return tuple(str(ref) for ref in declared)
                    case _:
                        raise StartupError("JSON must_read requires an array")
            case _:
                return ()
    refs: list[str] = []
    for line in active_lines(text):
        match = re.fullmatch(r" {0,3}(?:-\s*)?MUST READ:\s*(.*?)\s*", line, re.IGNORECASE)
        if match:
            reference = match.group(1).strip("`\"'")
            if not reference:
                raise StartupError("MUST READ requires a local path")
            refs.append(reference)
    return tuple(refs)


def _blocks(path: str, data: bytes) -> list[BlockRecord]:
    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    sections = parse_sections(text, startup_labels=True)
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for section in sections:
        begin, end = section.line_start - 1, section.line_end
        if begin > cursor:
            spans.append((cursor, begin, "Source preamble"))
        spans.append((begin, end, section.heading))
        cursor = end
    if cursor < len(lines) or not spans:
        spans.append((cursor, len(lines), "Source remainder"))
    records: list[BlockRecord] = []
    revision = digest(data)
    for begin, end, heading in spans:
        start_byte, end_byte = offsets[begin], offsets[end]
        raw = data[start_byte:end_byte]
        records.append({
            "path": path, "anchor": block_anchor(path, revision, start_byte, end_byte),
            "start_byte": start_byte, "end_byte": end_byte,
            "start_line": begin + 1 if data else 0, "end_line": end,
            "sha256": digest(raw), "text": raw.decode("utf-8"),
            "heading": heading, "state": "source", "must_read": True,
        })
    groups: list[list[BlockRecord]] = []
    prefix: list[BlockRecord] = []
    for record in records:
        if record["heading"].upper().startswith("TOP NOTE"):
            groups.append([record])
        elif groups:
            groups[-1].append(record)
        else:
            prefix.append(record)
    if not groups:
        return records
    dates: list[str] = []
    for group in groups:
        stamp = re.search(
            r"(?<!\w)(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z)?)(?![\w:+-])",
            group[0]["heading"],
        )
        value = stamp.group(1) if stamp else ""
        if value:
            try:
                _ = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                value = ""
        dates.append(value)
    if all(dates) and len(set(dates)) == len(dates) and \
            len({"T" in value for value in dates}) == 1:
        groups = [g for _, g in sorted(zip(dates, groups), key=lambda pair: pair[0],
                                      reverse=True)]
    superseded = {
        line.partition(":")[2].strip().casefold()
        for group in groups for record in group for line in active_lines(record["text"])
        if line.strip().casefold().startswith("supersedes:")
    }
    for group in groups:
        if group[0]["heading"].casefold() in superseded:
            for record in group:
                record["state"] = "explicitly-superseded"
    return prefix + [record for group in groups for record in group]


class StartupReader:
    """Bounded derived cache; every call rereads all local source bytes."""

    def __init__(self, root: str | Path) -> None:
        self.root: Path = Path(root).resolve()
        self._lock: threading.RLock = threading.RLock()
        self._key: tuple[tuple[str, str], ...] = ()
        self._context: str = ""

    def _sources(self, paths: Sequence[str]) -> dict[str, bytes]:
        if not paths or isinstance(paths, str):
            raise StartupError("supply a nonempty list of startup paths")
        pending = [self.root / path for path in paths]
        sources: dict[str, bytes] = {}
        while pending:
            path = pending.pop(0).resolve()
            if not path.is_relative_to(self.root):
                raise StartupError("required startup file is outside the configured root")
            relative = path.relative_to(self.root).as_posix()
            if relative in sources:
                continue
            if len(sources) >= 64:
                raise StartupError("startup bundle exceeds the 64-file budget")
            with path.open("rb") as handle:
                data = handle.read(1_048_577)
            if len(data) > 1_048_576 or sum(len(v) for v in sources.values()) + len(data) > 2_097_152:
                raise StartupError("startup bundle exceeds its complete-read byte budget")
            text = data.decode("utf-8")
            sources[relative] = data
            for reference in _references(relative, text):
                pending.append(path.parent / reference)
        return sources

    def read(self, paths: Sequence[str]) -> StartupBundle:
        """Return all material or raise; verify final context against fresh source bytes."""
        with self._lock:
            sources = self._sources(paths)
            key = tuple((path, digest(data)) for path, data in sources.items())
            hit = key == self._key and bool(self._context)
            if not hit:
                files: list[FileRecord] = [{
                    "path": path, "sha256": digest(data), "bytes": len(data),
                    "lines": len(data.decode("utf-8").splitlines(keepends=True)),
                } for path, data in sources.items()]
                blocks = [block for path, data in sources.items() for block in _blocks(path, data)]
                payload: StartupPayload = {
                    "version": 1, "complete": True, "files": files, "blocks": blocks,
                }
                self._context = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                self._key = key
            coverage = verify_context(self._context, sources)
            if not coverage.complete:
                raise StartupError("returned startup context failed byte/line coverage")
            return StartupBundle(self._context, coverage, hit)

    def verify(self, context: str, paths: Sequence[str]) -> Coverage:
        """Independently read the requested closure; reject altered/missing/foreign blocks."""
        with self._lock:
            sources = self._sources(paths)
            coverage = verify_context(context, sources)
            if not coverage.complete:
                return coverage
            expected = self.read(paths).context
            if _json(context) != _json(expected):
                return Coverage(False, coverage.files, coverage.lines, coverage.bytes,
                                ("derived-index-or-order",))
            return coverage
