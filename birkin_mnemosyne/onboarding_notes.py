"""Byte-preserving source notes and deterministic topic catalogues."""

from __future__ import annotations

import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import quote

from . import frontmatter
from .memory import _one_line, _yaml_str
from .memory_index import JsonValue, MemoryIndex, MemoryIndexError
from .startup_coverage import digest

CATALOGUE_MARKER: Final = b"<!-- mnemosyne-init-catalogue:v1 -->\n"
CATALOGUE_NAME: Final = re.compile(r"init-([a-f0-9]{64})\.md")
IMPORT_NAMESPACE: Final = re.compile(r"init-[a-f0-9]{64}")
HEADER_KEY: Final = re.compile(rb"^([A-Za-z_][A-Za-z0-9_-]*):")
AMBIGUOUS_YAML: Final = re.compile(rb"^\s*(?:<<:|[^#:\r\n]+:\s*[&*!])", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class SourceBytes:
    path: str
    raw: bytes


@dataclass(frozen=True, slots=True)
class Note:
    path: str
    raw: bytes
    normalized: bytes
    title: str
    topic: str
    additions: tuple[str, ...]
    warning: str | None


def inventory(root: Path) -> tuple[SourceBytes, ...]:
    """Read every visible active Markdown path without a cache or lock."""
    if not root.exists():
        return ()
    if not root.is_dir():
        raise MemoryIndexError("vault or import root must be a directory")
    index = MemoryIndex(root)
    pending = [index.root]
    sources: list[SourceBytes] = []
    identities: set[str] = set()
    while pending:
        for node in sorted(pending.pop().iterdir()):
            if node.name.startswith(".") or node.name == "_archive":
                continue
            attributes = getattr(node.lstat(), "st_file_attributes", 0)
            if node.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise MemoryIndexError(f"refusing linked source: {node.relative_to(index.root)}")
            if node.is_dir():
                pending.append(node)
            elif node.is_file() and node.suffix == ".md":
                relative = node.relative_to(index.root).as_posix()
                _ = index.document_path(relative)
                identity = unicodedata.normalize("NFC", relative).casefold()
                if identity in identities:
                    raise MemoryIndexError(f"ambiguous source identity: {relative}")
                identities.add(identity)
                sources.append(SourceBytes(relative, node.read_bytes()))
    return tuple(sorted(sources, key=lambda source: source.path))


def generated_catalogue(source: SourceBytes) -> bool:
    """Recognize owned catalogues only when name, marker and digest agree."""
    path = PurePosixPath(source.path)
    if path.parent.as_posix() != "onboarding-topics":
        return False
    matched = CATALOGUE_NAME.fullmatch(path.name)
    reserved = matched is not None or CATALOGUE_MARKER in source.raw
    if not reserved:
        return False
    if matched is None or CATALOGUE_MARKER not in source.raw or digest(source.raw) != matched[1]:
        raise MemoryIndexError(f"generated catalogue changed: {source.path}")
    return True


def complete_header(source: SourceBytes) -> tuple[bytes, tuple[str, ...], str | None]:
    """Insert absent fields without serializing existing YAML or body bytes."""
    raw = source.raw.removeprefix(b"\xef\xbb\xbf")
    lines = raw.splitlines(keepends=True)
    newline = b"\r\n" if lines and lines[0].endswith(b"\r\n") else b"\n"
    close = None
    if lines and lines[0].rstrip(b"\r\n") == b"---":
        close = next((i for i in range(1, len(lines))
                      if lines[i].rstrip(b"\r\n") == b"---"), None)
        if close is None:
            return source.raw, (), "unterminated frontmatter retained"
        header = b"".join(lines[1:close])
        keys = [match[1].decode("ascii") for line in lines[1:close]
                if (match := HEADER_KEY.match(line))]
        if len(keys) != len(set(keys)) or AMBIGUOUS_YAML.search(header):
            return source.raw, (), "ambiguous frontmatter retained"
    else:
        keys = []
    fields = {
        "title": _yaml_str(_one_line(PurePosixPath(source.path).stem)),
        "type": "topic",
        "tags": "[]",
    }
    missing = tuple(key for key in fields if key not in keys)
    if not missing and raw == source.raw:
        return source.raw, (), None
    additions = b"".join(f"{key}: {fields[key]}".encode() + newline for key in missing)
    if close is not None:
        normalized = b"".join(lines[:close]) + additions + b"".join(lines[close:])
    else:
        normalized = b"---" + newline + additions + b"---" + newline + raw
    return normalized, missing, None


def describe_note(source: SourceBytes, *, protected: bool = False) -> Note:
    """Derive a stable topic from source metadata without changing its body."""
    text = source.raw.decode("utf-8-sig")
    meta: dict[str, JsonValue]
    meta, _ = frontmatter.parse(text)
    title = _one_line(meta.get("title") or PurePosixPath(source.path).stem)
    tags: list[str] = []
    match meta.get("tags"):
        case list() as values:
            for value in values:
                match value:
                    case str() as tag:
                        cleaned = unicodedata.normalize("NFKC", _one_line(tag)).casefold()
                        if cleaned:
                            tags.append(cleaned)
                    case _:
                        continue
        case _:
            tags = []
    parts = PurePosixPath(source.path).parts
    if len(parts) > 2 and parts[0] == "imports" and IMPORT_NAMESPACE.fullmatch(parts[1]):
        parts = parts[2:]
    match meta.get("type"):
        case str() as value:
            note_type = _one_line(value) or "topic"
        case _:
            note_type = "topic"
    topic = min(tags) if tags else (parts[0] if len(parts) > 1 else note_type)
    topic = unicodedata.normalize("NFKC", _one_line(topic)).casefold()
    if protected:
        normalized, additions, warning = source.raw, (), "split receipt bytes retained"
    else:
        normalized, additions, warning = complete_header(source)
    return Note(source.path, source.raw, normalized, title, topic, additions, warning)


def catalogue(topic: str, members: tuple[Note, ...]) -> SourceBytes:
    """Render a stable source-link catalogue, never synthesized note prose."""
    lines = [
        "---", f"title: {_yaml_str(_one_line(topic))}", "type: topic", "tags: []", "---",
        CATALOGUE_MARKER.decode("ascii").rstrip("\n"), f"# {_one_line(topic)}", "",
    ]
    for note in sorted(members, key=lambda member: member.path):
        title = note.title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        lines.append(f"- [{title}](../{quote(note.path, safe='/')})")
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    return SourceBytes(f"onboarding-topics/init-{digest(raw)}.md", raw)
