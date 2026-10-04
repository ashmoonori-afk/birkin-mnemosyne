"""Live-vault lexical selection with Kibitzer-shaped documents and candidates.

Contract source: omo 5.1.9 persona and upstream memory-core recall select/gate
at 61086739c3b00f0990cbcdcdfde9146791e243db. This is not upstream selector parity,
committed-HEAD provider semantics, or an autonomous resident judgement.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from . import frontmatter
from ._recall_admission import addresses_agent as _addresses_agent
from ._recall_admission import decision_commentary as _decision_commentary
from ._recall_paths import allowed_path as _allowed
from ._recall_paths import deep_winners, scan_paths
from .mnemosyne import Mnemosyne, bm25_scores, tokenize
from .vault_lock import VaultLock

_SECRET = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    + r"|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}"
    + r"|\bBearer\s+[A-Za-z0-9._~+/-]{12,}"
    + r"|\b(?:password|api[_-]?key|token|secret)\s*[:=]\s*[\"']?[^\s\"']{8,})",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RecallDocument:
    path: str
    description: str
    body: str


@dataclass(frozen=True, slots=True)
class RecallCandidate:
    path: str
    description: str
    excerpt: str
    score: float


@dataclass(frozen=True, slots=True)
class RecallNudge:
    path: str
    hint: str


@dataclass(frozen=True, slots=True)
class Admission:
    accepted: tuple[RecallNudge, ...]
    rejected: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _ParsedDocument:
    document: RecallDocument
    expiry: str
    terms: dict[str, int]
    length: int


@dataclass(frozen=True, slots=True)
class _Snapshot:
    fingerprint: tuple[tuple[str, int, int, int], ...]
    day: date
    documents: tuple[RecallDocument, ...]
    postings: dict[str, dict[str, int]]
    lengths: dict[str, int]
    parsed: dict[str, _ParsedDocument]


def utf16_length(text: str) -> int:
    """JavaScript's string.length counts UTF-16 code units, not Python characters."""
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def _clip(text: str, units: int) -> str:
    return text.encode("utf-16-le")[:units * 2].decode("utf-16-le", errors="ignore")


def _excerpt(body: str, terms: Collection[str]) -> str:
    plain = " ".join(body.split())
    folded = plain.casefold()
    positions = [folded.find(t) for t in terms if len(t) > 1 and t in folded]
    # Window is in Python characters; final budget is in UTF-16 units.
    start = max(0, min(positions, default=0) - 70)
    return _clip(plain[start:], 200)


class KibitzerAdapter:
    """Mutable fresh snapshot and owned stdlib core index, with description fallback."""

    def __init__(self, vault: str | Path) -> None:
        self.vault: Path = Path(vault).resolve()
        self._cache: _Snapshot | None = None
        self._lock: threading.RLock = threading.RLock()
        self._core: Mnemosyne = Mnemosyne(self.vault, semantic=False)

    def _snapshot(self, force_refresh: bool) -> _Snapshot:
        # Windows ctime is creation time, not a content-change fingerprint.
        # Same-size edits can preserve every stat value; read content each time.
        force_refresh = force_refresh or sys.platform == "win32"
        with VaultLock(self.vault).hold(), self._lock:
            fingerprints = scan_paths(self.vault)
            signature = tuple(sorted(fingerprints))
            deep = deep_winners(fingerprints)
            day = datetime.now(timezone.utc).astimezone().date()
            if self._cache is not None and self._cache.fingerprint == signature and \
                    self._cache.day == day and not force_refresh:
                # A core TTL scan cannot discover deep paths. Keep those targeted
                # entries alive without changing the core's shallow scan contract.
                if deep:
                    self._core.refresh()
                    for relative in deep:
                        self._core.note_written(self.vault / relative)
                return self._cache
            documents: list[RecallDocument] = []
            postings: dict[str, dict[str, int]] = {}
            lengths: dict[str, int] = {}
            parsed_documents: dict[str, _ParsedDocument] = {}
            previous = {fingerprint[0]: fingerprint for fingerprint in
                        self._cache.fingerprint} if self._cache is not None else {}
            changed = {fingerprint[0] for fingerprint in signature
                       if force_refresh or previous.get(fingerprint[0]) != fingerprint}
            # Core refresh removes deleted/renamed entries but compares only mtime/size.
            # Explicit writes below must follow it, including preserved-stat edits.
            self._core.refresh_content(
                self.vault / relative for relative, _, _, _ in fingerprints
                if relative in changed
            )
            # Targeted writes drop/reinsert postings; a sorted path order would
            # change the core's lexical shortlist when scores tie before boosts.
            for relative, _, _, _ in fingerprints:
                path = self.vault / relative
                if relative in changed:
                    meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
                    body = _SECRET.sub("[redacted]", body)
                    title = str(meta.get("title") or path.stem)
                    description = str(meta.get("description") or
                                      f"{title}: {' '.join(body.split())[:160]}")
                    description = _SECRET.sub("[redacted]", description)
                    terms = tokenize(description + " " + body)
                    cached = _ParsedDocument(
                        RecallDocument(relative, description, body),
                        str(meta.get("expires_at") or ""), dict(Counter(terms)), len(terms),
                    )
                else:
                    assert self._cache is not None
                    cached = self._cache.parsed[relative]
                parsed_documents[relative] = cached
                if cached.expiry:
                    try:
                        expiry_day = date.fromisoformat(cached.expiry)
                    except ValueError:
                        expiry_day = day  # Malformed expiry remains visible, as in core.
                    if expiry_day < day:
                        continue
                documents.append(cached.document)
                lengths[relative] = cached.length
                for term, count in cached.terms.items():
                    postings.setdefault(term, {})[relative] = count
            # Core discovery is root + one zone; retain deeper adapter discoveries
            # after refresh, in their original discovery order.
            for relative in deep:
                self._core.note_written(self.vault / relative)
            self._cache = _Snapshot(signature, day, tuple(sorted(documents, key=lambda d: d.path)),
                                    postings, lengths,
                                    parsed_documents)
            return self._cache

    def documents(self, *, force_refresh: bool = False) -> tuple[RecallDocument, ...]:
        """Upstream-shaped live documents, with descriptions and conservative redaction."""
        return self._snapshot(force_refresh).documents

    def select(
        self, query: str, *, limit: int = 3,
        surfaced: Collection[str] = (), exclude_paths: Collection[str] = (),
        force_refresh: bool = False,
    ) -> tuple[RecallCandidate, ...]:
        """Exclude before cap; lower score is better, excerpts <=200 UTF-16 units."""
        with VaultLock(self.vault).hold(), self._lock:
            snapshot = self._snapshot(force_refresh)
            terms = tokenize(query)
            excluded = {*surfaced, *exclude_paths}
            eligible = {doc.path: doc for doc in snapshot.documents
                        if doc.path not in excluded}
            # Do not let the core's result limit consume caller-excluded slots.
            hits = self._core.search(
                query, limit=sys.maxsize,
            )
            ranked: list[tuple[RecallDocument, float]] = []
            for hit in hits:
                relative = hit["rel"]
                score = hit["score"]
                if relative in eligible:
                    ranked.append((eligible[relative], score))
            if not ranked:
                scores = bm25_scores(
                    terms, snapshot.postings, snapshot.lengths,
                    sum(snapshot.lengths.values()) / max(1, len(snapshot.lengths)),
                    len(snapshot.documents),
                )
                ranked = sorted(
                    ((doc, scores[doc.path]) for doc in eligible.values()
                     if scores.get(doc.path, 0) > 0),
                    key=lambda item: (-item[1], item[0].path),
                )
            return tuple(RecallCandidate(
                doc.path, doc.description, _excerpt(doc.body, terms), 1 / (1 + score),
            ) for doc, score in ranked[:max(0, limit)])

    def export(self, destination: str | Path) -> tuple[str, ...]:
        """Export described notes to a separate explicit root; never overwrite files."""
        root = Path(destination).resolve()
        if root.is_relative_to(self.vault) or self.vault.is_relative_to(root):
            raise ValueError("export root must be separate from the source vault")
        documents = self.documents()
        for doc in documents:
            target = root / doc.path
            if not target.resolve().is_relative_to(root) or target.exists():
                raise FileExistsError(f"unsafe or occupied export path: {doc.path}")
        for doc in documents:
            text = (
                "---\n"
                + f"description: {json.dumps(doc.description, ensure_ascii=False)}\n"
                + f"mnemosyne_source: {json.dumps(doc.path, ensure_ascii=False)}\n"
                + "---\n\n" + doc.body.rstrip() + "\n"
            )
            target = root / doc.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                _ = handle.write(text.encode("utf-8"))
        return tuple(doc.path for doc in documents)


def admit(
    nudges: Iterable[RecallNudge], *, offered: Collection[str],
    surfaced: Collection[str] = (), max_items: int = 2,
) -> Admission:
    """Validate caller-authored facts; lexical checks cannot prove their truth."""
    accepted: list[RecallNudge] = []
    rejected: list[tuple[str, str]] = []
    seen: set[str] = set()
    for nudge in nudges:
        reason = ""
        if len(accepted) >= max(0, max_items):
            reason = "cap"
        elif not _allowed(nudge.path) or nudge.path not in offered:
            reason = "unoffered-or-protected"
        elif nudge.path in surfaced or nudge.path in seen:
            reason = "already-surfaced-or-duplicate"
        elif not nudge.hint.strip() or utf16_length(nudge.hint) > 200 or \
                "\n" in nudge.hint or "\r" in nudge.hint or \
                re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", nudge.hint):
            reason = "hint-shape"
        elif _addresses_agent(nudge.hint):
            reason = "addresses-agent"
        elif _decision_commentary(nudge.hint):
            reason = "decision-commentary"
        elif _SECRET.search(nudge.hint):
            reason = "secret-like"
        if reason:
            rejected.append((nudge.path, reason))
        else:
            accepted.append(nudge)
            seen.add(nudge.path)
    return Admission(tuple(accepted), tuple(rejected))


def render_recall(nudge: RecallNudge) -> str:
    """Render an already admitted nudge, preserving data through XML escaping."""
    return (
        f'<recalled-memory source="[[{escape(nudge.path, quote=True)}]]">\n'
        + "Memory reference supplied by the Mnemosyne adapter; "
        + "the current task remains authoritative.\n"
        + f"{escape(nudge.hint)}\n</recalled-memory>"
    )
