"""Deterministic task matching and revision binding over an index snapshot."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Final

from .mnemosyne import expansion_weights, tokenize


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


GENERIC_ACTION_TERMS: Final = frozenset(_terms(
    "check checking work working do doing write writing open opening "
    "update updating answer answering report reporting launch launching "
    "resume resuming choose choosing pick picking use using handle handling "
    "post posting send sending format formatting decide deciding "
    "monitor monitoring touch touching deal dealing automate automating"
))
TASK_EQUIVALENTS: Final = (
    ("web", "browser", "website", "site", "webpage"),
    ("login", "log in", "sign in", "authentication"),
    ("repository", "repo", "codebase"),
    ("rollback", "backout", "back out", "revert"),
)


def match_entries(entries: tuple[IndexEntry, ...], task: str) -> tuple[IndexEntry, ...]:
    """Select lexical subjects; repeated generic actions alone are insufficient."""
    if not task.strip():
        raise MemoryIndexError("task must be a nonempty string")
    normalized, terms = _normalized(task), _terms(task)
    equivalents = [
        alias for group in TASK_EQUIVALENTS
        if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", normalized)
               for alias in group)
        for alias in group
    ]
    added = expansion_weights({"synonyms": equivalents}, tokenize(task))
    terms.update(_terms(" ".join(term for term in added if not term.endswith("~"))))
    trigger_terms = {entry.trigger: _terms(entry.trigger) for entry in entries}
    frequencies = Counter(
        term for content in trigger_terms.values() for term in content & GENERIC_ACTION_TERMS
    )
    repeated = {term for term, count in frequencies.items() if count > 1}
    subjects = {
        trigger: content - repeated or content for trigger, content in trigger_terms.items()
    }
    return tuple(
        entry for entry in entries
        if _normalized(entry.trigger) == normalized or subjects[entry.trigger] & terms
    )


def index_revision(maximum: int, entries: tuple[IndexEntry, ...]) -> str:
    """Commit to the complete authoritative routing set and its budget."""
    record = {
        "version": 1, "max_tokens": maximum,
        "entries": sorted((entry.trigger, entry.document) for entry in entries),
    }
    raw = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
