"""Independent byte/line coverage verification of the final returned context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeAlias, TypedDict

from .startup_compact import compact_effects

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class FileRecord(TypedDict):
    path: str
    sha256: str
    bytes: int
    lines: int


class BlockRecord(TypedDict):
    path: str
    anchor: str
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    sha256: str
    text: str
    heading: str
    state: str
    must_read: bool


class StartupPayload(TypedDict):
    version: int
    complete: bool
    files: list[FileRecord]
    blocks: list[BlockRecord]


_decode: Callable[[str], StartupPayload] = json.loads


def _strict_object(members: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {}
    for name, member in members:
        if name in value:
            raise ValueError(f"duplicate JSON member: {name}")
        value[name] = member
    return value


def _strict_constant(value: str) -> JsonValue:
    raise ValueError(f"non-JSON constant: {value}")


_strict_decode: Callable[[str], JsonValue] = json.JSONDecoder(
    object_pairs_hook=_strict_object, parse_constant=_strict_constant,
).decode


@dataclass(frozen=True, slots=True)
class Coverage:
    complete: bool
    files: int
    lines: int
    bytes: int
    errors: tuple[str, ...]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def block_anchor(path: str, revision: str, start: int, end: int) -> str:
    return digest(f"{path}\0{revision}\0{start}:{end}".encode())[:20]


def _int(value: JsonValue) -> bool:
    return type(value) is int


def _int_list(value: JsonValue) -> list[int] | None:
    if not isinstance(value, list):
        return None
    result: list[int] = []
    for item in value:
        if not _int(item) or not isinstance(item, int):
            return None
        result.append(item)
    return result


def _compact_order_errors(entry: dict[str, JsonValue], text: str, path: str) -> list[str]:
    errors: list[str] = []
    if set(entry) - {"path", "reorder", "superseded"}:
        errors.append(f"unexpected-order-field:{path}")
    declared_reorder = entry.get("reorder", [])
    declared_superseded = entry.get("superseded", [])
    if ("reorder" in entry and not declared_reorder) or \
            ("superseded" in entry and not declared_superseded):
        errors.append(f"empty-order-effect:{path}")
    if not isinstance(declared_reorder, list) or not isinstance(declared_superseded, list):
        return [f"malformed-order:{path}"]
    reorders: list[list[int]] = []
    for run in declared_reorder:
        parsed_run = _int_list(run)
        if parsed_run is None or not parsed_run:
            errors.append(f"malformed-reorder:{path}")
            continue
        if len(set(parsed_run)) != len(parsed_run):
            errors.append(f"repeated-reorder:{path}")
        reorders.append(parsed_run)
    superseded = _int_list(declared_superseded)
    if superseded is None:
        errors.append(f"malformed-superseded:{path}")
    elif superseded != sorted(superseded):
        errors.append(f"unsorted-superseded:{path}")
    seen: set[int] = set()
    for parsed_run in reorders:
        if seen.intersection(parsed_run):
            errors.append(f"overlapping-reorder:{path}")
        seen.update(parsed_run)
    expected_reorder, expected_superseded = compact_effects(text)
    if reorders != expected_reorder:
        errors.append(f"reorder-drift:{path}")
    if superseded is None or superseded != expected_superseded:
        errors.append(f"supersession-drift:{path}")
    return errors


def _verify_compact(payload: dict[str, JsonValue], sources: Mapping[str, bytes]) -> list[str]:
    """Recompute v2 presentation effects from source bytes; never trust them."""
    errors: list[str] = []
    if set(payload) != {"version", "files", "order"}:
        return ["unexpected-field"]
    records = payload["files"]
    order = payload["order"]
    if not isinstance(records, list) or not isinstance(order, list):
        return ["malformed-files"]
    declared: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "text"}:
            errors.append("malformed-file")
            continue
        path = record.get("path")
        content = record.get("text")
        if not isinstance(path, str) or not isinstance(content, str):
            errors.append("malformed-file")
            continue
        declared.append(path)
        raw = sources.get(path)
        if raw is None or content.encode("utf-8") != raw:
            errors.append(f"file-byte-drift:{path}")
    if len(declared) != len(set(declared)):
        errors.append("duplicate-file")
    if set(declared) != set(sources) or declared != list(sources):
        errors.append("path-order")
    order_paths: list[str] = []
    for entry in order:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("malformed-order")
            continue
        path = entry["path"]
        if not isinstance(path, str):
            errors.append("malformed-order")
            continue
        order_paths.append(path)
        raw = sources.get(path)
        if raw is None:
            errors.append(f"foreign-order:{path}")
            continue
        errors.extend(_compact_order_errors(entry, raw.decode("utf-8"), path))
    if len(order_paths) != len(set(order_paths)):
        errors.append("duplicate-order")
    affected = [path for path, raw in sources.items()
                if any(compact_effects(raw.decode("utf-8")))]
    if order_paths != affected:
        errors.append("missing-order")
    return errors


def verify_context(context: str, sources: Mapping[str, bytes]) -> Coverage:
    """Reconstruct supplied fresh bytes; do not trust the returned certificate."""
    errors: list[str] = []
    nlines = sum(len(raw.decode("utf-8").splitlines(keepends=True))
                 for raw in sources.values())
    nbytes = sum(len(raw) for raw in sources.values())
    try:
        probe = _strict_decode(context)
        if isinstance(probe, dict) and _int(probe.get("version")) and probe["version"] == 2:
            errors.extend(_verify_compact(probe, sources))
            return Coverage(not errors and bool(sources), len(sources), nlines,
                            nbytes, tuple(errors))
        payload = _decode(context)
        if type(payload["version"]) is not int or payload["version"] != 1 or \
                payload["complete"] is not True:
            raise ValueError("not a complete startup payload")
        records = payload["files"]
        declared = [r["path"] for r in records]
        if len(declared) != len(set(declared)) or set(declared) != set(sources):
            errors.append("source-set")
        for record in records:
            raw = sources.get(record["path"])
            if raw is None or record["sha256"] != digest(raw) or \
                    record["bytes"] != len(raw) or \
                    record["lines"] != len(raw.decode("utf-8").splitlines(keepends=True)):
                errors.append(f"certificate:{record['path']}")
        grouped: dict[str, list[BlockRecord]] = {}
        for block in payload["blocks"]:
            if block["path"] not in sources:
                errors.append("foreign-block")
            grouped.setdefault(block["path"], []).append(block)
        if set(grouped) != set(sources):
            errors.append("missing-source-block")
        for path, raw in sources.items():
            cursor, assembled = 0, bytearray()
            line_ends = [0]
            for line in raw.decode("utf-8").splitlines(keepends=True):
                line_ends.append(line_ends[-1] + len(line.encode("utf-8")))
            positions = {offset: i for i, offset in enumerate(line_ends)}
            blocks = sorted(grouped.get(path, []), key=lambda b: b["start_byte"])
            anchors = [block["anchor"] for block in blocks]
            if len(anchors) != len(set(anchors)) or (not raw and len(blocks) != 1):
                errors.append(f"duplicate-block:{path}")
            for block in blocks:
                data = block["text"].encode("utf-8")
                start, end = block["start_byte"], block["end_byte"]
                expected_start_line = positions.get(start, -2) + 1 if raw else 0
                expected_end_line = positions.get(end, -2)
                if type(start) is not int or type(end) is not int or \
                        start != cursor or end < start or end > len(raw) or \
                        (bool(raw) and end == start) or \
                        len(data) != end - start or data != raw[start:end] or \
                        block["sha256"] != digest(data) or \
                        block["anchor"] != block_anchor(path, digest(raw), start, end) or \
                        block["start_line"] != expected_start_line or \
                        block["end_line"] != expected_end_line or \
                        block["must_read"] is not True:
                    errors.append(f"block:{path}")
                cursor = end
                assembled.extend(data)
            if cursor != len(raw) or bytes(assembled) != raw:
                errors.append(f"coverage:{path}")
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append("malformed-context")
    return Coverage(not errors and bool(sources), len(sources), nlines, nbytes, tuple(errors))
