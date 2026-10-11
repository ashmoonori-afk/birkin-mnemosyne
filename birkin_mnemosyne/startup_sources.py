"""Lossless startup source parsing and block ordering."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Generator
from datetime import datetime
from typing import TypeAlias

from .identity_reader import parse_sections
from .startup_coverage import BlockRecord, StartupError, block_anchor, digest

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

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


def references(path: str, text: str) -> tuple[str, ...]:
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


def source_blocks(path: str, data: bytes) -> list[BlockRecord]:
    """Return every source byte with its explicit line and byte coordinates."""
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
