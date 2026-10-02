"""Independent byte/line coverage verification of the final returned context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypedDict


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


def verify_context(context: str, sources: Mapping[str, bytes]) -> Coverage:
    """Reconstruct supplied fresh bytes; do not trust the returned certificate."""
    errors: list[str] = []
    nlines = sum(len(raw.decode("utf-8").splitlines(keepends=True))
                 for raw in sources.values())
    nbytes = sum(len(raw) for raw in sources.values())
    try:
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
