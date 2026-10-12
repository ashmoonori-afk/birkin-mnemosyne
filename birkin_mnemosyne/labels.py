"""Deterministic label suggestions and byte-preserving label field edits.

This is the pure label boundary of the vault: inference and editing run on
source bytes plus a caller-supplied :class:`LabelContext`.  The module never
imports memory, mnemosyne, memory_index or onboarding (those consume labels,
so a reverse import would cycle), never reads the clock and never calls a
provider.

- ``read_labels`` resolves the labels field: ``None`` means no field, ``()``
  means an explicitly empty, user-owned field; invalid label metadata raises
  :class:`LabelError` at this boundary.
- ``suggest_labels`` derives conservative suggestions from explicit metadata,
  typed wikilinks, real ISO calendar dates, path/INDEX context and bounded
  script evidence for language.
- ``annotate_labels`` performs the checked edit: ``labels=None`` only writes
  suggestions when the field is absent; an explicit tuple (including ``()``)
  replaces through a checked operation.  Ambiguous or invalid source metadata
  is retained unchanged with a warning, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Final, TypeAlias

from . import frontmatter, label_frontmatter
from .label_values import (
    LabelError,
    detect_language,
    iso_dates_in_text,
    is_valid_label,
    normalize_labels,
    parse_iso_date,
    typed_wikilinks,
    yaml_label_list,
)

_META_NAMESPACES: Final = (
    ("type", ("type",)),
    ("zone", ("zone",)),
    ("topic", ("topic",)),
    ("project", ("project",)),
    ("person", ("people", "person")),
    ("entity", ("entities", "entity")),
)
_DATE_KEYS: Final = ("created", "updated", "date", "dates")
_LANG_KEYS: Final = ("language", "lang")
MetadataValue: TypeAlias = (
    str | int | float | bool | None | list["MetadataValue"] | dict[str, "MetadataValue"]
)


@dataclass(frozen=True, slots=True)
class LabelContext:
    path: str
    index_topics: tuple[str, ...] = ()
    source: str | None = None
    format: str | None = None


@dataclass(frozen=True, slots=True)
class LabelEdit:
    raw: bytes
    labels: tuple[str, ...]
    suggestions: tuple[str, ...]
    warning: str | None


def read_labels(raw: bytes) -> tuple[str, ...] | None:
    """Resolve the labels field of ``raw`` (None = absent, () = empty)."""
    _ = _decode(raw)
    scan = label_frontmatter.inspect(raw)
    if not scan.present:
        return None
    _require_trustworthy(scan)
    if scan.labels_index is None:
        return None
    if scan.labels_multiline:
        raise LabelError("labels block list cannot be parsed as label strings")
    if scan.labels_empty_scalar:
        return ()
    meta, _ = _parse(raw)
    if "labels" in meta and "labels" not in scan.header_keys:
        raise LabelError("labels field is not a plain top-level scalar")
    match meta.get("labels"):
        case None:
            return ()
        case list() as items:
            return _check_entries(items)
        case _ as other:
            raise LabelError(f"labels metadata must be a list, got {type(other).__name__}")


def suggest_labels(raw: bytes, context: LabelContext) -> tuple[str, ...]:
    """Derive conservative, deterministic label suggestions."""
    meta, body = _parse(raw)
    candidates: list[str] = []

    def add(namespace: str, value: MetadataValue) -> None:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                candidates.append(f"{namespace}:{cleaned}")

    def add_dates(value: MetadataValue) -> None:
        if isinstance(value, str):
            parsed = parse_iso_date(value)
            if parsed is not None:
                candidates.append(f"date:{parsed}")

    for namespace, keys in _META_NAMESPACES:
        for key in keys:
            match meta.get(key):
                case str() as value:
                    add(namespace, value)
                case list() as rows:
                    for row in rows:
                        add(namespace, row)
                case _:
                    pass
    for topic in context.index_topics:
        add("topic", topic)
    for namespace, target in typed_wikilinks(body):
        add(namespace, target)
    for key in _DATE_KEYS:
        match meta.get(key):
            case str() as value:
                add_dates(value)
            case list() as rows:
                for row in rows:
                    add_dates(row)
            case _:
                pass
    for mention in iso_dates_in_text(body):
        candidates.append(f"date:{mention}")
    language = _explicit_language(meta)
    if language is None:
        language = detect_language(body)
    if language is not None:
        candidates.append(f"lang:{language}")
    note_type = _note_type(meta)
    if note_type == "project" or note_type == "person":
        add(note_type, _title_or_stem(meta, context.path))
    parts = PurePosixPath(context.path).parts
    if not any(label.startswith("zone:") for label in candidates):
        if len(parts) > 1 and not parts[0].startswith("."):
            add("zone", parts[0])
    add("source", context.source)
    add("format", context.format)
    valid = [label for label in candidates if is_valid_label(label)]
    return normalize_labels(valid)


def annotate_labels(
    raw: bytes, context: LabelContext, *, labels: tuple[str, ...] | None = None
) -> LabelEdit:
    """Produce a label-field edit for ``raw`` (the input bytes are untouched)."""
    replacement = None if labels is None else normalize_labels(labels)
    scan = label_frontmatter.inspect(raw)
    warning = _structural_warning(scan)
    if warning is not None:
        return LabelEdit(raw, (), (), warning)
    try:
        existing = read_labels(raw)
        suggestions = suggest_labels(raw, context)
    except LabelError as exc:
        return LabelEdit(raw, (), (),
                         f"invalid labels metadata retained: {exc}")
    if replacement is None and existing is not None:
        return LabelEdit(raw, existing, suggestions, None)
    values = suggestions if replacement is None else replacement
    edited, edit_warning = label_frontmatter.apply_label_edit(raw, yaml_label_list(values))
    return LabelEdit(edited, read_labels(edited) or (), suggestions, edit_warning)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LabelError(f"source is not valid UTF-8: {exc}") from exc


def _require_trustworthy(scan: label_frontmatter.HeaderScan) -> None:
    if scan.present and not scan.closed:
        raise LabelError("unterminated frontmatter")
    if scan.duplicate_keys or scan.anchor_ambiguous or scan.unsupported:
        raise LabelError("ambiguous frontmatter cannot resolve the labels field")


def _check_entries(items: Sequence[MetadataValue]) -> tuple[str, ...]:
    out: list[str] = []
    for item in items:
        if not isinstance(item, str) or not is_valid_label(item):
            raise LabelError(f"invalid labels entry: {item!r}")
        out.append(item)
    return tuple(out)


def _explicit_language(meta: dict[str, MetadataValue]) -> str | None:
    for key in _LANG_KEYS:
        match meta.get(key):
            case str() as value if value.strip():
                return value.strip()
            case _:
                pass
    return None


def _note_type(meta: dict[str, MetadataValue]) -> str:
    match meta.get("type"):
        case str() as value:
            return value.strip().casefold()
        case _:
            return ""


def _title_or_stem(meta: dict[str, MetadataValue], path: str) -> str | None:
    match meta.get("title"):
        case str() as value if value.strip():
            return value.strip()
        case _:
            return PurePosixPath(path).stem


def _structural_warning(scan: label_frontmatter.HeaderScan) -> str | None:
    if scan.present and not scan.closed:
        return "unterminated frontmatter retained"
    if scan.present and (scan.duplicate_keys or scan.anchor_ambiguous or scan.unsupported):
        return "ambiguous frontmatter retained"
    return None


def _parse(raw: bytes) -> tuple[dict[str, MetadataValue], str]:
    text = _decode(raw)
    scan = label_frontmatter.inspect(raw)
    if not scan.present:
        return {}, text
    _require_trustworthy(scan)
    if scan.labels_multiline:
        raise LabelError("labels block list cannot be parsed as label strings")
    meta: dict[str, MetadataValue]
    try:
        meta, body = frontmatter.parse(text)
    except (AttributeError, TypeError) as exc:
        raise LabelError("mixed frontmatter containers cannot be parsed") from exc
    return meta, body
