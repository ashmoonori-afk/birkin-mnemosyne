"""Compact startup bundle v2: source bytes once, fresh-order arrangement.

Version 2 stores every supplied UTF-8 file once and describes presentation
separately: ``files`` carries each raw source string, ``order`` carries only
the affected files (those a note run rearranged or a supersession marked)
with the note group IDs and the exact string transforms that relocate
material. Nothing here is trusted when the context is verified - the effects
are recomputed from the supplied source bytes.

Group IDs are the natural UTF-8 byte offset of a TOP NOTE root's first line,
so they survive re-serialization. A descendant section moves with its root.
Supersession reuses the exact date and ``Supersedes:`` rules of
:mod:`birkin_mnemosyne.startup`: only distinct, same-precision, all-valid
dates permit descending order inside a contiguous run of notes, and a
``Supersedes:`` line names a full heading case-insensitively, ignoring
fenced lines. Old material is never dropped - a superseded root is only
marked.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict

from .identity_reader import parse_sections

NORMAL_STATE = "source"
SUPERSEDED_STATE = "explicitly-superseded"
_STAMP = r"(?<!\w)(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z)?)(?![\w:+-])"


class CompactFile(TypedDict):
    path: str
    text: str


class _OrderPath(TypedDict):
    path: str


class OrderEntry(_OrderPath, total=False):
    reorder: list[list[int]]
    superseded: list[int]


class CompactPayload(TypedDict):
    version: int
    files: list[CompactFile]
    order: list[OrderEntry]


class _Unit(TypedDict):
    note: bool
    root: int
    start: int
    end: int
    heading: str


def _spans(text: str) -> list[tuple[int, int, str, int]]:
    """Byte spans for every preamble/heading span, in source order."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    lines = text.splitlines(keepends=True)
    spans: list[tuple[int, int, str, int]] = []
    cursor = 0
    for section in parse_sections(text, startup_labels=True):
        begin, end = section.line_start - 1, section.line_end
        if begin > cursor:
            spans.append((cursor, begin, "Source preamble", 0))
        spans.append((begin, end, section.heading, section.level))
        cursor = end
    if cursor < len(lines) or not spans:
        spans.append((cursor, len(lines), "Source remainder", 0))
    return [(offsets[begin], offsets[end], heading, level)
            for begin, end, heading, level in spans]


def _units(text: str) -> list[_Unit]:
    """Byte partition: note groups (root + descendants) and plain spans."""
    units: list[_Unit] = []
    active: int | None = None
    level = 0
    for start, end, heading, heading_level in _spans(text):
        if heading.upper().startswith("TOP NOTE"):
            units.append({"note": True, "root": start, "start": start,
                          "end": end, "heading": heading})
            active = len(units) - 1
            level = heading_level
        elif active is not None and heading_level > level:
            units[active]["end"] = end
        else:
            units.append({"note": False, "root": start, "start": start,
                          "end": end, "heading": heading})
            active = None
    return units


def _stamp(heading: str) -> tuple[datetime | None, int]:
    match = re.search(_STAMP, heading)
    value = match.group(1) if match else ""
    if not value:
        return None, 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")), len(value)
    except ValueError:
        return None, len(value)


def _supersession_targets(text: str) -> set[str]:
    """Outside-fence ``Supersedes:`` targets, casefolded; mirrors startup rules."""
    targets: set[str] = set()
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
        if not fence and line.strip().casefold().startswith("supersedes:"):
            targets.add(line.partition(":")[2].strip().casefold())
    return targets


def compact_effects(text: str) -> tuple[list[list[int]], list[int]]:
    """Presentation effects for one file: changed note runs and superseded roots."""
    units = _units(text)
    notes = [unit for unit in units if unit["note"]]
    if not notes:
        return [], []
    stamped = [_stamp(unit["heading"]) for unit in notes]
    dates = [value for value, _ in stamped]
    precisions = {precision for _, precision in stamped}
    reorder: list[list[int]] = []
    if all(date is not None for date in dates) and len(set(dates)) == len(dates) and \
            len(precisions) == 1:
        timestamps = {unit["root"]: value
                      for unit, value in zip(notes, dates) if value is not None}
        begin = 0
        while begin < len(units):
            if not units[begin]["note"]:
                begin += 1
                continue
            end = begin + 1
            while end < len(units) and units[end]["note"]:
                end += 1
            run = [units[position]["root"] for position in range(begin, end)]
            ordered = sorted(run, key=lambda root: timestamps[root], reverse=True)
            if ordered != run:
                first, last = 0, len(run)
                while run[first] == ordered[first]:
                    first += 1
                while run[last - 1] == ordered[last - 1]:
                    last -= 1
                reorder.append(ordered[first:last])
            begin = end
    raw = text.encode("utf-8")
    declared: set[str] = set()
    # Legacy declarations are scoped to each individual note section.
    for start, end, _, _ in _spans(text):
        if any(unit["start"] <= start < unit["end"] for unit in notes):
            declared.update(_supersession_targets(raw[start:end].decode("utf-8")))
    superseded = sorted(unit["root"] for unit in notes
                        if unit["heading"].casefold() in declared)
    return reorder, superseded


def _plan(sources: Mapping[str, bytes]) -> CompactPayload:
    order: list[OrderEntry] = []
    for path, raw in sources.items():
        reorder, superseded = compact_effects(raw.decode("utf-8"))
        if not reorder and not superseded:
            continue
        entry: OrderEntry = {"path": path}
        if reorder:
            entry["reorder"] = reorder
        if superseded:
            entry["superseded"] = superseded
        order.append(entry)
    return {
        "version": 2,
        "files": [{"path": path, "text": raw.decode("utf-8")}
                  for path, raw in sources.items()],
        "order": order,
    }


def compact_payload(sources: Mapping[str, bytes]) -> str:
    """Serialise the complete v2 bundle: each raw UTF-8 file once plus effects."""
    return json.dumps(_plan(sources), ensure_ascii=False, separators=(",", ":"))


def apply_order(text: str, entry: OrderEntry) -> str:
    """Assemble one file: relocate whole note groups into the declared order."""
    units = _units(text)
    raw = text.encode("utf-8")
    text_of = {unit["root"]: raw[unit["start"]:unit["end"]].decode("utf-8")
               for unit in units if unit["note"]}
    run_of: dict[int, list[int]] = {}
    for run in entry.get("reorder", []):
        for root in run:
            run_of[root] = run
    chunks: list[str] = []
    emitted: set[int] = set()
    for unit in units:
        if not unit["note"]:
            chunks.append(raw[unit["start"]:unit["end"]].decode("utf-8"))
            continue
        run = run_of.get(unit["root"])
        if run is None:
            chunks.append(text_of[unit["root"]])
            continue
        if run[0] not in emitted:
            emitted.add(run[0])
            for root in run:
                chunks.append(text_of[root])
    return "".join(chunks)
