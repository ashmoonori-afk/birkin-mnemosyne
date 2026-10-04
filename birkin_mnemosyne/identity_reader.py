"""Revision-bound Markdown sections and small, stat-invalidated read caches.

Search is partial context, not a replacement for comprehensive instructions.
ATX/setext headings and backtick/tilde fences are supported. Frontmatter is
excluded from section ranking; full reads preserve every source byte.
"""

from __future__ import annotations

import hashlib
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path

from ._startup_syntax import parse_spans


class IdentityReadError(ValueError):
    """An identity path, revision or section cannot be safely read."""


@dataclass(frozen=True, slots=True)
class Section:
    anchor: str
    heading: str
    ancestry: tuple[str, ...]
    level: int
    line_start: int
    line_end: int
    text: str


@dataclass(frozen=True, slots=True)
class ReadResult:
    path: str
    revision: str
    sections: tuple[Section, ...]
    context: str
    complete_file: bool


@dataclass(frozen=True, slots=True)
class _Document:
    fingerprint: tuple[int, int, int, int]
    revision: str
    text: str
    sections: tuple[Section, ...]
    postings: dict[str, dict[str, int]]
    lengths: dict[str, int]


class IdentityReader:
    """Mutable LRU cache, bounded to one MiB of source across four files."""

    def __init__(self, root: str | Path) -> None:
        self.root: Path = Path(root).resolve()
        self._cache: OrderedDict[Path, _Document] = OrderedDict()
        self._lock: threading.RLock = threading.RLock()

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise IdentityReadError("path is outside the configured identity root")
        return path

    def _load(self, relative: str, force_refresh: bool) -> _Document:
        from .mnemosyne import tokenize

        path = self._path(relative)
        with self._lock:
            try:
                stat = path.stat()
            except FileNotFoundError:
                _ = self._cache.pop(path, None)
                raise
            if stat.st_size > 1_048_576:
                raise IdentityReadError("identity file exceeds the one MiB read budget")
            fingerprint = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
            cached = self._cache.get(path)
            if cached is not None and cached.fingerprint == fingerprint and \
                    not force_refresh:
                self._cache.move_to_end(path)
                return cached
            with path.open("rb") as handle:
                data = handle.read(1_048_577)
            if len(data) > 1_048_576:
                raise IdentityReadError("identity file exceeds the one MiB read budget")
            text = data.decode("utf-8")
            sections = parse_sections(text)
            postings: dict[str, dict[str, int]] = {}
            lengths: dict[str, int] = {}
            for section in sections:
                terms = tokenize(" ".join(section.ancestry) + " " + section.text)
                lengths[section.anchor] = len(terms)
                for term, count in Counter(terms).items():
                    postings.setdefault(term, {})[section.anchor] = count
            document = _Document(
                fingerprint, hashlib.sha256(data).hexdigest(), text,
                sections, postings, lengths,
            )
            self._cache[path] = document
            self._cache.move_to_end(path)
            while len(self._cache) > 4 or sum(
                d.fingerprint[2] for d in self._cache.values()
            ) > 1_048_576:
                _ = self._cache.popitem(last=False)
            return document

    def sections(self, path: str, *, force_refresh: bool = False) -> ReadResult:
        """Return the section catalog and revision, without full body context."""
        document = self._load(path, force_refresh)
        return ReadResult(path, document.revision, document.sections, "", False)

    def read_full(self, path: str, *, force_refresh: bool = False) -> ReadResult:
        """Read all instructions, including frontmatter, global rules and examples."""
        document = self._load(path, force_refresh)
        return ReadResult(path, document.revision, document.sections,
                          document.text, True)

    def search(
        self, path: str, query: str, *, limit: int = 3,
        force_refresh: bool = False, include_preamble: bool = True,
    ) -> ReadResult:
        """Return ranked whole sections with ancestry; no-match has empty context."""
        from .mnemosyne import bm25_scores, tokenize

        document = self._load(path, force_refresh)
        scores = bm25_scores(
            tokenize(query), document.postings, document.lengths,
            sum(document.lengths.values()) / max(1, len(document.lengths)),
            len(document.sections),
        )
        ranked = sorted(
            (s for s in document.sections if scores.get(s.anchor, 0) > 0),
            key=lambda s: (-scores[s.anchor], s.line_start),
        )[:max(0, limit)]
        if ranked and include_preamble:
            preamble = next((s for s in document.sections if s.level == 0), None)
            if preamble is not None and preamble not in ranked:
                ranked.insert(0, preamble)
        return ReadResult(path, document.revision, tuple(ranked),
                          _context(path, document.revision, tuple(ranked)), False)

    def read_section(
        self, path: str, anchor: str, revision: str, *,
        include_children: bool = False, force_refresh: bool = False,
    ) -> ReadResult:
        """Reject stale revisions; fetch a whole source span, optionally its subtree."""
        document = self._load(path, force_refresh)
        if revision != document.revision:
            raise IdentityReadError("stale revision; request a fresh section catalog")
        selected = next((s for s in document.sections if s.anchor == anchor), None)
        if selected is None:
            raise IdentityReadError("anchor is absent from this revision")
        sections = [selected]
        if include_children:
            for section in document.sections:
                if section.line_start <= selected.line_start:
                    continue
                if section.level <= selected.level:
                    break
                sections.append(section)
        return ReadResult(path, document.revision, tuple(sections),
                          _context(path, document.revision, tuple(sections)), False)


def _context(path: str, revision: str, sections: tuple[Section, ...]) -> str:
    if not sections:
        return ""
    chunks = [f"Source: {path}\nRevision: {revision}\nPartial context: true\n"]
    for section in sections:
        chunks.append(
            f"\nAnchor: {section.anchor}; lines {section.line_start}-{section.line_end}\n"
        )
        for level, heading in enumerate(section.ancestry, 1):
            chunks.append(f"{'#' * level} {heading}\n")
        chunks.append(section.text)
        if not section.text.endswith(("\n", "\r")):
            chunks.append("\n")
    return "".join(chunks)


def parse_sections(text: str, *, startup_labels: bool = False) -> tuple[Section, ...]:
    """Partition exact spans; bare startup TOP NOTE labels act as level-2 headings."""
    lines = text.splitlines(keepends=True)
    ancestors: list[tuple[int, str]] = []
    occurrences: Counter[tuple[str, ...]] = Counter()
    result: list[Section] = []
    for begin, end, heading, level in parse_spans(text, startup_labels=startup_labels):
        content = "".join(lines[begin:end])
        while ancestors and ancestors[-1][0] >= level:
            _ = ancestors.pop()
        ancestry = tuple(title for _, title in ancestors)
        key = (*ancestry, heading)
        occurrences[key] += 1
        anchor = hashlib.sha256(
            ("\0".join(key) + f"\0{occurrences[key]}").encode("utf-8"),
        ).hexdigest()[:16]
        result.append(Section(anchor, heading, ancestry, level,
                              begin + 1, end, content))
        if level:
            ancestors.append((level, heading))
    return tuple(result)
