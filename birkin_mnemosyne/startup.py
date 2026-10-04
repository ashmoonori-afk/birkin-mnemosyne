"""Lossless startup bundles: every source line, fresh SHA checks, no semantic cuts."""

from __future__ import annotations

import _thread
import json
import re
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from ._startup_root_order import root_payload
from .startup_compact import compact_payload
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
BundleFormat: TypeAlias = Literal["v1", "v2", "file-root-order/3"]
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
    for line in text.removeprefix("\ufeff").splitlines():
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


def _json_object(members: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {}
    for name, member in members:
        if name in value:
            raise ValueError(f"duplicate JSON member: {name}")
        value[name] = member
    return value


def _json_constant(value: str) -> JsonValue:
    raise ValueError(f"non-JSON constant: {value}")


_startup_json: Callable[[str], JsonValue] = json.JSONDecoder(
    object_pairs_hook=_json_object, parse_constant=_json_constant,
).decode


def _references(path: str, text: str) -> tuple[str, ...]:
    if path.lower().endswith(".json"):
        try:
            value = _startup_json(text.removeprefix("\ufeff"))
        except ValueError as exc:
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
    from datetime import datetime

    from .identity_reader import parse_sections

    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    sections = parse_sections(text, startup_labels=True)
    spans: list[tuple[int, int, str, int]] = []
    cursor = 0
    for section in sections:
        begin, end = section.line_start - 1, section.line_end
        if begin > cursor:
            spans.append((cursor, begin, "Source preamble", 0))
        spans.append((begin, end, section.heading, section.level))
        cursor = end
    if cursor < len(lines) or not spans:
        spans.append((cursor, len(lines), "Source remainder", 0))
    records: list[BlockRecord] = []
    revision = digest(data)
    for begin, end, heading, _ in spans:
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
    units: list[tuple[bool, list[BlockRecord]]] = []
    note_level: int | None = None
    for record, (_, _, _, level) in zip(records, spans):
        if record["heading"].upper().startswith("TOP NOTE"):
            groups.append([record])
            units.append((True, groups[-1]))
            note_level = level
        elif note_level is not None and level > note_level:
            groups[-1].append(record)
        else:
            units.append((False, [record]))
            note_level = None
    if not groups:
        return records
    dates: list[datetime | None] = []
    precisions: set[int] = set()
    for group in groups:
        stamp = re.search(
            r"(?<!\w)(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z)?)(?![\w:+-])",
            group[0]["heading"],
        )
        value = stamp.group(1) if stamp else ""
        parsed = None
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
            precisions.add(len(value))  # Date, UTC minute, or UTC second precision.
        dates.append(parsed)
    if all(date is not None for date in dates) and len(set(dates)) == len(dates) and \
            len(precisions) == 1:
        timestamps = {
            group[0]["anchor"]: date for group, date in zip(groups, dates)
            if date is not None
        }
        begin = 0
        while begin < len(units):
            if not units[begin][0]:
                begin += 1
                continue
            end = begin + 1
            while end < len(units) and units[end][0]:
                end += 1
            units[begin:end] = sorted(
                units[begin:end], key=lambda unit: timestamps[unit[1][0]["anchor"]],
                reverse=True,
            )
            begin = end
    superseded = {
        line.partition(":")[2].strip().casefold()
        for group in groups for record in group for line in active_lines(record["text"])
        if line.strip().casefold().startswith("supersedes:")
    }
    for group in groups:
        if group[0]["heading"].casefold() in superseded:
            for record in group:
                record["state"] = "explicitly-superseded"
    return [record for _, unit in units for record in unit]


class StartupReader:
    """Bounded derived cache; every call rereads all local source bytes."""

    def __init__(self, root: str | Path) -> None:
        self.root: Path = Path(root).resolve()
        self._lock: _thread.RLock = _thread.RLock()
        self._cache: dict[BundleFormat, tuple[tuple[tuple[str, bytes], ...], str]] = {}

    def _sources(self, paths: Sequence[str]) -> dict[str, bytes]:
        if not paths or isinstance(paths, str):
            raise StartupError("supply a nonempty list of startup paths")
        pending = [self.root / path for path in paths]
        sources: dict[str, bytes] = {}
        resolved: set[Path] = set()
        total = 0
        while pending:
            candidate = pending.pop(0)
            if candidate in resolved:
                continue
            path = candidate.resolve()
            if not path.is_relative_to(self.root):
                raise StartupError("required startup file is outside the configured root")
            relative = path.relative_to(self.root).as_posix()
            if relative in sources:
                resolved.add(candidate)
                continue
            resolved.update((candidate, path))
            if len(sources) >= 64:
                raise StartupError("startup bundle exceeds the 64-file budget")
            with path.open("rb") as handle:
                data = handle.read(1_048_577)
            total += len(data)
            if len(data) > 1_048_576 or total > 2_097_152:
                raise StartupError("startup bundle exceeds its complete-read byte budget")
            text = data.decode("utf-8")
            sources[relative] = data
            for reference in _references(relative, text):
                pending.append(path.parent / reference)
        return sources

    def _context(self, sources: dict[str, bytes], format: BundleFormat) -> tuple[str, bool]:
        key = tuple(sources.items())
        cached = self._cache.get(format)
        if cached is not None and cached[0] == key:
            return cached[1], True
        match format:
            case "v2":
                context = compact_payload(sources)
            case "file-root-order/3":
                context = root_payload(sources)
            case "v1":
                files: list[FileRecord] = [{
                    "path": path, "sha256": digest(data), "bytes": len(data),
                    "lines": len(data.decode("utf-8").splitlines(keepends=True)),
                } for path, data in sources.items()]
                blocks = [block for path, data in sources.items() for block in _blocks(path, data)]
                payload: StartupPayload = {
                    "version": 1, "complete": True, "files": files, "blocks": blocks,
                }
                context = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._cache[format] = key, context
        return context, False

    def read(
        self, paths: Sequence[str], *, compact: bool = False, compact_format: str = "v2",
    ) -> StartupBundle:
        """Return all material or raise; verify final context against fresh source bytes."""
        with self._lock:
            format: BundleFormat = "v1"
            if compact:
                match compact_format:
                    case "v2":
                        format = "v2"
                    case "file-root-order/3":
                        format = "file-root-order/3"
                    case _:
                        raise StartupError("unsupported compact startup format")
            elif compact_format != "v2":
                raise StartupError("compact_format requires compact=True")
            sources = self._sources(paths)
            context, hit = self._context(sources, format)
            coverage = verify_context(context, sources)
            if not coverage.complete:
                raise StartupError("returned startup context failed byte/line coverage")
            return StartupBundle(context, coverage, hit)

    def verify(self, context: str, paths: Sequence[str]) -> Coverage:
        """Independently read the requested closure; reject altered/missing/foreign blocks."""
        with self._lock:
            sources = self._sources(paths)
            coverage = verify_context(context, sources)
            if not coverage.complete:
                return coverage
            payload = _json(context)
            if isinstance(payload, dict) and (payload.get("version") == 2 or "version" not in payload):
                return coverage
            expected, _ = self._context(sources, "v1")
            if _json(context) != _json(expected):
                return Coverage(False, coverage.files, coverage.lines, coverage.bytes,
                                ("derived-index-or-order",))
            return coverage
