"""Deterministic task matching and revision binding over an index snapshot."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Final

from .mnemosyne import tokenize


class MemoryIndexError(ValueError):
    """Invalid or incomplete routing state must never become an empty INDEX."""

    def __init__(self, reason: str) -> None:
        self.reason: str = reason
        super().__init__(reason)


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

FUNCTION_WORDS: Final = frozenset({
    "a", "an", "the", "and", "or", "as", "at", "by", "for", "from", "in", "into",
    "of", "on", "onto", "to", "with", "about", "after", "before", "between",
    "during", "through", "under", "over", "when", "while", "if", "then", "than",
    "that", "this", "these", "those", "what", "how", "why", "where", "which",
    "who", "whom", "whose", "i", "me", "my", "we", "our", "you", "your", "he",
    "his", "she", "her", "it", "its", "they", "their", "is", "am", "are", "was",
    "were", "be", "been", "being", "do", "does", "did", "have", "has", "had",
    "can", "could", "may", "might", "must", "shall", "should", "will", "would",
})


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _terms(text: str) -> set[str]:
    result: set[str] = set()
    for token in tokenize(text):
        if token.endswith("~") or token in FUNCTION_WORDS:
            continue
        result.add(token)
        if not token.isascii() or not token.isalpha():
            continue
        variants: list[str] = []
        if token.endswith(("ies", "ied")):
            variants.append(token[:-3] + "y")
        for suffix in ("ing", "ed"):
            if token.endswith(suffix):
                stem = token[:-len(suffix)]
                variants.append(stem)
                if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] in "bdglmnprt":
                    variants.append(stem[:-1])
        if token.endswith("s") and not token.endswith(("ss", "us", "is")):
            variants.append(token[:-1])
        result.update(variant for variant in variants if len(variant) >= 4)
    return result


def match_entries(entries: tuple[IndexEntry, ...], task: str) -> tuple[IndexEntry, ...]:
    """Select every lexical route; never rank, cap, or search document bodies."""
    if not task.strip():
        raise MemoryIndexError("task must be a nonempty string")
    normalized, terms = _normalized(task), _terms(task)
    return tuple(
        entry for entry in entries
        if _normalized(entry.trigger) == normalized or _terms(entry.trigger) & terms
    )


def index_revision(maximum: int, entries: tuple[IndexEntry, ...]) -> str:
    """Commit to the complete authoritative routing set and its budget."""
    record = {
        "version": 1, "max_tokens": maximum,
        "entries": sorted((entry.trigger, entry.document) for entry in entries),
    }
    raw = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
