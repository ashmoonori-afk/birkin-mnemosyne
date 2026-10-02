"""Frozen context-only startup answerer; no production-reader imports.

Measures constrained field/list/JSON-pointer answers, not generative compliance.
Question source/section/field/pointer are inputs; expected answers never enter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import TypeAlias

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
_decode: Callable[[str], dict[str, JsonValue]] = json.loads
_json_value: Callable[[str], JsonValue] = json.loads


def documents(context: str) -> Mapping[str, str]:
    """Decode full-read files or reconstruct complete-mode blocks in source order."""
    payload = _decode(context)
    result: dict[str, str] = {}
    files = payload.get("files")
    if isinstance(files, list):
        for record in files:
            if isinstance(record, dict):
                path, text = record.get("path"), record.get("text")
                if isinstance(path, str) and isinstance(text, str):
                    result[path] = text
    blocks = payload.get("blocks")
    if isinstance(blocks, list):
        grouped: dict[str, list[tuple[int, str]]] = {}
        for record in blocks:
            if not isinstance(record, dict):
                continue
            path, text, start = record.get("path"), record.get("text"), record.get("start_byte")
            if isinstance(path, str) and isinstance(text, str) and isinstance(start, int):
                grouped.setdefault(path, []).append((start, text))
        for path, parts in grouped.items():
            result[path] = "".join(text for _, text in sorted(parts))
    return result


def answer(context: str, question: Mapping[str, JsonValue]) -> JsonValue:
    """Produce an answer from only supplied context and the structured question."""
    source = question.get("source")
    if not isinstance(source, str):
        return None
    text = documents(context).get(source)
    if text is None:
        return None
    pointer = question.get("json_pointer")
    if isinstance(pointer, str):
        node = _json_value(text.lstrip("\ufeff"))
        for raw in pointer.lstrip("/").split("/") if pointer else []:
            key = raw.replace("~1", "/").replace("~0", "~")
            match node:
                case dict():
                    node = node.get(key)
                case list():
                    if not key.isdigit() or int(key) >= len(node):
                        return None
                    node = node[int(key)]
                case _:
                    return None
        return node
    section, field = question.get("section"), question.get("field")
    if not isinstance(section, str) or not isinstance(field, str):
        return None
    lines = text.splitlines()
    active, fence, width = False, "", 0
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, rest = marker.groups()
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width and not rest.strip():
                fence = ""
            continue
        if fence:
            continue
        heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        label = re.match(r"^ {0,3}(TOP NOTE\b.*)$", line, re.IGNORECASE)
        if heading or label:
            title = heading.group(1) if heading else label.group(1) if label else ""
            active = title.casefold() == section.casefold()
            continue
        key, separator, value = line.strip().partition(":")
        if not active or not separator or key.casefold() != field.casefold():
            continue
        if value.strip():
            return value.strip()
        items: list[JsonValue] = []
        for following in lines[index + 1:]:
            stripped = following.strip()
            if not stripped:
                continue
            if not stripped.startswith("- "):
                break
            items.append(stripped[2:])
        return items if items else None
    return None
