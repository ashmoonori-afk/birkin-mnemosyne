"""Complete raw files with signed order for every affected note root.

Nonnegative IDs mean source state; -(offset+1) means explicit supersession.
The listed roots occupy their own natural slots in the declared order. All
unlisted roots keep their natural slots and source state. This representation
never omits a moved root or an explicitly superseded root.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TypeAlias, TypedDict

from .startup_compact import CompactFile, byte_spans, note_units, presentation_effects

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class RootFile(CompactFile, total=False):
    order: list[int]


class RootPayload(TypedDict):
    files: list[RootFile]


def root_order(text: str) -> list[int]:
    """Encode exactly the moved or explicitly superseded roots, in final order."""
    spans = byte_spans(text)
    units = note_units(spans)
    reorders, superseded = presentation_effects(text, spans, units)
    natural = [unit["root"] for unit in units if unit["note"]]
    run_of = {root: run for run in reorders for root in run}
    ordered: list[int] = []
    emitted: set[int] = set()
    for root in natural:
        run = run_of.get(root)
        if run is None:
            ordered.append(root)
        elif run[0] not in emitted:
            ordered.extend(run)
            emitted.add(run[0])
    selected = {before for before, after in zip(natural, ordered) if before != after}
    selected.update(superseded)
    states = set(superseded)
    return [-root - 1 if root in states else root for root in ordered if root in selected]


def root_payload(sources: Mapping[str, bytes]) -> str:
    """Serialize file-root-order/3 without duplicate source bytes or metadata paths."""
    files: list[RootFile] = []
    for path, raw in sources.items():
        text = raw.decode("utf-8")
        record: RootFile = {"path": path, "text": text}
        order = root_order(text)
        if order:
            record["order"] = order
        files.append(record)
    payload: RootPayload = {"files": files}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def apply_root_order(text: str, order: list[int]) -> str:
    """Assemble a verified selected-slot permutation without interpreting dates."""
    units = note_units(byte_spans(text))
    raw = text.encode("utf-8")
    roots = [code if code >= 0 else -code - 1 for code in order]
    selected = set(roots)
    text_of = {unit["root"]: raw[unit["start"]:unit["end"]].decode("utf-8")
               for unit in units if unit["note"]}
    next_root = iter(roots)
    chunks: list[str] = []
    for unit in units:
        if unit["note"] and unit["root"] in selected:
            chunks.append(text_of[next(next_root)])
        else:
            chunks.append(raw[unit["start"]:unit["end"]].decode("utf-8"))
    return "".join(chunks)


def root_payload_errors(payload: dict[str, JsonValue], sources: Mapping[str, bytes]) -> list[str]:
    """Compare untrusted fields and signed effects against authoritative source bytes."""
    errors: list[str] = []
    if set(payload) != {"files"}:
        return ["unexpected-field"]
    records = payload["files"]
    if not isinstance(records, list):
        return ["malformed-files"]
    declared: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) not in (
            {"path", "text"}, {"path", "text", "order"},
        ):
            errors.append("malformed-file")
            continue
        path, text = record.get("path"), record.get("text")
        if not isinstance(path, str) or not isinstance(text, str):
            errors.append("malformed-file")
            continue
        declared.append(path)
        raw = sources.get(path)
        if raw is None:
            errors.append(f"foreign-file:{path}")
            continue
        if text.encode("utf-8") != raw:
            errors.append(f"file-byte-drift:{path}")
        expected = root_order(raw.decode("utf-8"))
        if "order" not in record:
            if expected:
                errors.append(f"missing-order:{path}")
            continue
        if not expected:
            errors.append(f"redundant-order:{path}")
        value = record["order"]
        if not isinstance(value, list):
            errors.append(f"malformed-order:{path}")
            continue
        roots: list[int] = []
        for code in value:
            match code:
                case int() if type(code) is int:
                    roots.append(code)
                case _:
                    errors.append(f"malformed-order:{path}")
        offsets = [code if code >= 0 else -code - 1 for code in roots]
        if len(offsets) != len(set(offsets)):
            errors.append(f"duplicate-root:{path}")
        if roots != expected:
            errors.append(f"root-order-or-state-drift:{path}")
    if declared != list(sources):
        errors.append("path-order")
    return errors
