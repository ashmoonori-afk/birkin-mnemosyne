"""Durable, additive trigger-to-document routing, separate from the search cache."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from typing import Final, Literal, TypeAlias

from .atomic import atomic_write_bytes
from .mnemosyne import Mnemosyne, bm25_scores, tokenize
from .vault_lock import VaultLock

INDEX_DIRECTORY: Final = ".mnemosyne-memory-index"
INDEX_SOURCE: Final = ".mnemosyne-memory-index/context"
DEFAULT_INDEX_TOKENS: Final = 2000
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | \
    dict[str, "JsonValue"]


class MemoryIndexError(ValueError):
    """Invalid or incomplete routing state must never become an empty INDEX."""

    def __init__(self, reason: str) -> None:
        self.reason: str = reason
        super().__init__(reason)


def estimated_tokens(text: str) -> int:
    """A declared UTF-8-bytes/4 estimate, not model-specific token accounting."""
    return (len(text.encode("utf-8")) + 3) // 4


@dataclass(frozen=True, slots=True)
class IndexEntry:
    trigger: str
    document: str

    def __post_init__(self) -> None:
        for name, text in (("trigger", self.trigger), ("document", self.document)):
            if not text.strip() or \
                    text != text.strip() or len(text.splitlines()) != 1 or \
                    any(ord(c) < 32 or ord(c) == 127 for c in text):
                raise MemoryIndexError(f"{name} must be a nonempty single-line string")


@dataclass(frozen=True, slots=True)
class IndexView:
    enabled: bool
    entries: tuple[IndexEntry, ...]
    context: str
    estimated_tokens: int
    max_tokens: int
    over_budget: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OpenedDocument:
    path: str
    content: str


@dataclass(frozen=True, slots=True)
class OpenResult:
    matched_by: Literal["exact", "trigger", "search", "none"]
    documents: tuple[OpenedDocument, ...]


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise MemoryIndexError(f"duplicate INDEX field: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> JsonValue:
    raise MemoryIndexError(f"invalid JSON constant: {value}")


decode_index_json: Callable[[str], JsonValue] = json.JSONDecoder(
    object_pairs_hook=_unique_object, parse_constant=_invalid_constant,
).decode


def validate_index_budget(value: int) -> int:
    """Shared positive-token budget boundary for registration and migration."""
    if type(value) is not int or value < 1:
        raise MemoryIndexError("max_tokens must be a positive integer")
    return value


class MemoryIndex:
    """Additive routing state; reads never create or truncate it.

    The directory persists as an opt-in marker. ``required`` additionally
    detects removal of the marker itself, including across a host restart.
    Generic Markdown-note lifecycle operations cannot address this state.
    """

    def __init__(self, root: str | Path, *, required: bool = False) -> None:
        self.root: Path = Path(root).resolve()
        self.directory: Path = self.root / INDEX_DIRECTORY
        self.path: Path = self.directory / "index.json"
        self.required: bool = required

    def document_path(self, document: str) -> Path:
        """Resolve a visible local document without allowing hidden-state access."""
        relative = document.replace("\\", "/")
        parts = relative.split("/")
        if not relative or Path(relative).is_absolute() or \
                PureWindowsPath(document).drive or \
                any(not part or part.startswith(".") or part == "_archive" for part in parts):
            raise MemoryIndexError(f"unsafe document path: {document!r}")
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root) or \
                any(parent.is_symlink() for parent in (path, *path.parents)
                    if parent != self.root and parent.is_relative_to(self.root)):
            raise MemoryIndexError(f"unsafe document path: {document!r}")
        return path

    def _state(self) -> tuple[int, tuple[IndexEntry, ...]] | None:
        if self.directory.is_symlink() or self.path.is_symlink():
            raise MemoryIndexError("INDEX state must not be a symlink")
        if not self.directory.exists():
            if self.required:
                raise MemoryIndexError("required memory INDEX is missing")
            return None
        self.required = True
        try:
            raw = decode_index_json(self.path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise MemoryIndexError("enabled memory INDEX is missing or invalid") from exc
        match raw:
            case {"version": version, "max_tokens": int() as maximum, "entries": list() as rows}:
                if type(version) is not int or version != 1 or \
                        set(raw) != {"version", "max_tokens", "entries"}:
                    raise MemoryIndexError("invalid memory INDEX version or fields")
                budget = validate_index_budget(maximum)
                entries: list[IndexEntry] = []
                for row in rows:
                    match row:
                        case {"trigger": str() as trigger, "document": str() as document}:
                            if set(row) != {"trigger", "document"}:
                                raise MemoryIndexError("invalid INDEX entry fields")
                            entry = IndexEntry(trigger, document)
                            path = self.document_path(document)
                            if path.relative_to(self.root).as_posix() != document:
                                raise MemoryIndexError("INDEX document paths must be canonical")
                            if entry in entries:
                                raise MemoryIndexError("duplicate memory INDEX entry")
                            entries.append(entry)
                        case _:
                            raise MemoryIndexError("invalid memory INDEX entry")
                return budget, tuple(entries)
            case _:
                raise MemoryIndexError("invalid memory INDEX record")

    def read(self) -> IndexView:
        """Read every entry, with a warning rather than eviction over budget."""
        state = self._state()
        if state is None:
            return IndexView(False, (), "", 0, DEFAULT_INDEX_TOKENS, False, ())
        maximum, entries = state
        lines = [
            "# Memory INDEX",
            ("Always retain every entry, including after compaction. "
             "When a trigger applies, open its document with memory_open_trigger; "
             "use memory_search if no trigger matches."),
        ]
        lines.extend(f"- {entry.trigger} -> {entry.document}" for entry in entries)
        context = "\n".join(lines) + "\n"
        warnings: tuple[str, ...] = ()
        if estimated_tokens(context) > maximum:
            warning = (
                f"Memory INDEX exceeds its {maximum} estimated-token budget "
                "(UTF-8 bytes/4); every entry is retained."
            )
            warnings = (warning,)
            context += "WARNING: " + warning + "\n"
        return IndexView(True, entries, context, estimated_tokens(context),
                         maximum, bool(warnings), warnings)

    def render(self) -> str:
        return self.read().context

    def register(self, trigger: str, document: str, *,
                 max_tokens: int | None = None) -> IndexView:
        """Opt in and add a mapping; duplicates are idempotent, never replacements."""
        entry = IndexEntry(trigger, document)
        with VaultLock(self.root).hold():
            state = self._state()
            maximum, previous = state if state is not None else (DEFAULT_INDEX_TOKENS, ())
            if max_tokens is not None:
                maximum = validate_index_budget(max_tokens)
            path = self.document_path(entry.document)
            if not path.is_file() and "/" not in document and "\\" not in document:
                relative = Mnemosyne(self.root).resolve_rel(document)
                if relative is not None:
                    path = self.document_path(relative)
            if not path.is_file():
                raise MemoryIndexError(f"INDEX document does not exist: {document!r}")
            canonical = IndexEntry(trigger, path.relative_to(self.root).as_posix())
            entries = previous if canonical in previous else (*previous, canonical)
            if state != (maximum, entries):
                record = {"version": 1, "max_tokens": maximum,
                          "entries": [asdict(item) for item in entries]}
                atomic_write_bytes(self.path, (json.dumps(
                    record, ensure_ascii=False, separators=(",", ":"),
                ) + "\n").encode("utf-8"))
            return self.read()

    def open(self, query: str, *, limit: int = 3) -> OpenResult:
        """Open exact/lexical trigger matches, or fall back to the existing search."""
        if not query.strip():
            raise MemoryIndexError("query must be a nonempty string")
        if type(limit) is not int or limit < 1:
            raise MemoryIndexError("limit must be a positive integer")
        entries = self.read().entries
        exact = [entry for entry in entries if entry.trigger.casefold() == query.strip().casefold()]
        matched_by: Literal["exact", "trigger", "search", "none"]
        if exact:
            selected = exact
            matched_by = "exact"
        else:
            postings: dict[str, dict[str, int]] = {}
            lengths: dict[str, int] = {}
            for i, entry in enumerate(entries):
                terms = tokenize(entry.trigger)
                lengths[str(i)] = len(terms)
                for term, count in Counter(terms).items():
                    postings.setdefault(term, {})[str(i)] = count
            scores = bm25_scores(
                tokenize(query), postings, lengths,
                sum(lengths.values()) / len(entries) if entries else 0.0, len(entries),
            )
            ranked = sorted(scores, key=lambda key: (-scores[key], int(key)))
            selected = [entries[int(key)] for key in ranked if scores[key] > 0]
            matched_by = "trigger"
        paths = list(dict.fromkeys(entry.document for entry in selected))[:limit]
        if not paths:
            paths = [hit["rel"] for hit in Mnemosyne(self.root).search(query, limit=limit)]
            matched_by = "search" if paths else "none"
        documents: list[OpenedDocument] = []
        for relative in paths:
            path = self.document_path(relative)
            try:
                content = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise MemoryIndexError(f"cannot read INDEX document: {relative!r}") from exc
            documents.append(OpenedDocument(relative, content))
        return OpenResult(matched_by, tuple(documents))
