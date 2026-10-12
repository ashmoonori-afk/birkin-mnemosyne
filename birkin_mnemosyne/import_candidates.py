"""Deterministic, lossless raw-file import candidates for init onboarding.

The external surface accepts one supported file or one directory.  Every
visible ``.md`` / ``.txt`` / ``.json`` source becomes exactly one candidate:
Markdown keeps its original bytes for the existing safe normalization, while
text and JSON are wrapped verbatim inside a backtick fence that no backtick
run in the source can close.  The original suffix is retained in the converted
name (``export.json`` becomes ``export.json.md``) so formats never overwrite
one another.  Sources that are linked, contain invalid UTF-8, or would collide
by converted name or Unicode case folding are refused.
"""

from __future__ import annotations

import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, NoReturn

from .memory_index import MemoryIndexError

SUPPORTED_SUFFIXES: Final = (".md", ".txt", ".json")
FORMAT_BY_SUFFIX: Final = {".md": "md", ".txt": "txt", ".json": "json"}
_MIN_FENCE: Final = 3
_BACKTICK_RUN: Final = re.compile(rb"`+")


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    relative: str
    preimage: bytes
    raw: bytes
    format: str
    warning: str | None


def scan_import(import_path: Path) -> tuple[ImportCandidate, ...]:
    """Inventory one supported file or directory into sorted candidates."""
    if not import_path.exists():
        raise MemoryIndexError(f"import path must be an existing file or directory: {import_path}")
    absolute = import_path.absolute()
    for node in (absolute, *absolute.parents):
        _refuse_link(node)
    root = Path(os.path.realpath(import_path))
    if root.is_file():
        if root.name.startswith(".") or root.name == "_archive":
            raise MemoryIndexError(f"import file is not a visible source: {root.name}")
        if root.suffix not in SUPPORTED_SUFFIXES:
            raise MemoryIndexError(f"import file must be .md, .txt or .json: {root.name}")
        return (_candidate(root, root.name),)
    if root.is_dir():
        return _scan_directory(root)
    raise MemoryIndexError(f"import path must be an existing file or directory: {import_path}")


def destination_name(relative: str) -> str:
    """Converted destination basename below the import namespace."""
    return relative if PurePosixPath(relative).suffix == ".md" else f"{relative}.md"


def _scan_directory(root: Path) -> tuple[ImportCandidate, ...]:
    pending = [root]
    found: list[ImportCandidate] = []
    identities: set[str] = set()
    while pending:
        for node in sorted(pending.pop().iterdir()):
            if node.name.startswith(".") or node.name == "_archive":
                continue
            _refuse_link(node)
            if node.is_dir():
                pending.append(node)
            elif node.is_file() and node.suffix in SUPPORTED_SUFFIXES:
                relative = node.relative_to(root).as_posix()
                candidate = _candidate(node, relative)
                destination = destination_name(relative)
                identity = unicodedata.normalize("NFC", destination).casefold()
                if identity in identities:
                    raise MemoryIndexError(f"ambiguous import destination: {destination}")
                identities.add(identity)
                found.append(candidate)
    return tuple(sorted(found, key=lambda item: item.relative))


def _candidate(path: Path, relative: str) -> ImportCandidate:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoryIndexError(f"import source is not valid UTF-8: {relative}") from exc
    format_ = FORMAT_BY_SUFFIX[path.suffix]
    warning: str | None = None
    if format_ == "json":
        try:
            json.loads(text.removeprefix("\ufeff"), parse_constant=_invalid_constant)
        except ValueError:
            warning = f"{relative}: invalid JSON retained as text"
    converted = raw if format_ == "md" else _fence(raw)
    return ImportCandidate(relative, raw, converted, format_, warning)


def _fence(raw: bytes) -> bytes:
    """Wrap bytes verbatim inside a backtick fence the body cannot terminate."""
    longest = max((len(match.group(0)) for match in _BACKTICK_RUN.finditer(raw)), default=0)
    fence = b"`" * max(_MIN_FENCE, longest + 1)
    body = raw if raw.endswith(b"\n") else raw + b"\n"
    return fence + b"\n" + body + fence + b"\n"


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError(f"non-JSON numeric constant: {value}")


def _refuse_link(node: Path) -> None:
    attributes = getattr(node.lstat(), "st_file_attributes", 0)
    if node.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise MemoryIndexError(f"refusing linked import path: {node}")
