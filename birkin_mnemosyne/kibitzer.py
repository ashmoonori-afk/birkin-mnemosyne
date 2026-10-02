"""Live-vault lexical selection with Kibitzer-shaped documents and candidates.

Contract source: omo 5.1.9 persona and upstream memory-core recall select/gate
at 61086739c3b00f0990cbcdcdfde9146791e243db. This is not upstream selector parity,
committed-HEAD provider semantics, or an autonomous resident judgement.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import frontmatter
from .mnemosyne import bm25_scores, tokenize
from .vault_lock import VaultLock

_SECRET = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    + r"|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}"
    + r"|\bBearer\s+[A-Za-z0-9._~+/-]{12,}"
    + r"|\b(?:password|api[_-]?key|token|secret)\s*[:=]\s*[\"']?[^\s\"']{8,})",
    re.IGNORECASE,
)


def _addresses_agent(hint: str) -> bool:
    """Independently implement the documented address/imperative restrictions."""
    words = re.findall(r"\b[a-z]+(?:['’][a-z]+)?\b", hint.casefold())
    if set(words) & {"you", "your", "yours", "yourself"}:
        return True
    openings = {
        "never", "always", "ensure", "verify", "check", "run", "use", "read",
        "stop", "avoid", "remember", "keep", "prefer", "skip", "consider",
        "don't", "don’t",
    }
    if words and (words[0] in openings or words[:2] in (
        ["do", "not"], ["make", "sure"],
    )):
        return True
    ending = hint.rstrip(" \t.!?")
    return ending.endswith((
        "세요", "십시오", "십시요", "하라", "해라", "합니다", "지 마", "지 마라",
    )) or re.search("하지\\s*마", hint) is not None


def _decision_commentary(hint: str) -> bool:
    """Reject decisions about whether to nudge, rather than stored observations."""
    text = " ".join(hint.casefold().split())
    if any(phrase in text for phrase in (
        "no stored memory", "clears the bar", "not relevant", "no relevant",
    )):
        return True
    if not ({"memory", "memories"} & set(re.findall(r"\w+", text))):
        return False
    return any(phrase in text for phrase in (
        "is unrelated to", "are unrelated to", "is not about", "are not about",
        "does not cover", "do not cover", "does not address", "do not address",
        "does not pertain", "do not pertain",
    )) or ("not the" in text and any(p in text for p in ("covers ", "cover ")))


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
class _Snapshot:
    fingerprint: tuple[tuple[str, int, int, int], ...]
    day: date
    documents: tuple[RecallDocument, ...]
    postings: dict[str, dict[str, int]]
    lengths: dict[str, int]


def utf16_length(text: str) -> int:
    """JavaScript's string.length counts UTF-16 code units, not Python characters."""
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def _clip(text: str, units: int) -> str:
    return text.encode("utf-16-le")[:units * 2].decode("utf-16-le", errors="ignore")


def _allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and not PurePosixPath(path).is_absolute() and \
        not PureWindowsPath(path).drive and \
        not any(p in {".", ".."} or p.startswith(".") for p in parts) and \
        parts[0].casefold() not in {"system", "_archive"} and \
        "\\" not in path and not re.search(r"[\x00-\x1f\ud800-\udfff\ufffe\uffff]", path)


def _excerpt(body: str, query: str) -> str:
    plain = " ".join(body.split())
    terms = sorted(set(tokenize(query)), key=len, reverse=True)
    folded = plain.casefold()
    positions = [folded.find(t) for t in terms if len(t) > 1 and t in folded]
    # Window is in Python characters; final budget is in UTF-16 units.
    start = max(0, min(positions, default=0) - 70)
    return _clip(plain[start:], 200)


class KibitzerAdapter:
    """Mutable snapshot cache; lexical index reuses the stdlib core tokenizer."""

    def __init__(self, vault: str | Path) -> None:
        self.vault: Path = Path(vault).resolve()
        self._cache: _Snapshot | None = None
        self._lock: threading.RLock = threading.RLock()

    def _snapshot(self, force_refresh: bool) -> _Snapshot:
        with VaultLock(self.vault).hold(), self._lock:
            paths = sorted(p for p in self.vault.rglob("*.md")
                           if _allowed(p.relative_to(self.vault).as_posix()) and
                           p.resolve().is_relative_to(self.vault))
            fingerprints: list[tuple[str, int, int, int]] = []
            for path in paths:
                stat = path.stat()
                fingerprints.append((path.relative_to(self.vault).as_posix(),
                                     stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
            signature = tuple(fingerprints)
            day = datetime.now(timezone.utc).astimezone().date()
            if self._cache is not None and self._cache.fingerprint == signature and \
                    self._cache.day == day and not force_refresh:
                return self._cache
            documents: list[RecallDocument] = []
            postings: dict[str, dict[str, int]] = {}
            lengths: dict[str, int] = {}
            for path in paths:
                parsed, body = frontmatter.parse(path.read_text(encoding="utf-8"))
                meta: dict[str, str | int | float | bool | None | list[str]] = parsed
                expiry = meta.get("expires_at")
                if expiry:
                    try:
                        expiry_day = date.fromisoformat(str(expiry))
                    except ValueError:
                        expiry_day = day  # Malformed expiry remains visible, as in core.
                    if expiry_day < day:
                        continue
                body = _SECRET.sub("[redacted]", body)
                title = str(meta.get("title") or path.stem)
                description = str(meta.get("description") or
                                  f"{title}: {' '.join(body.split())[:160]}")
                description = _SECRET.sub("[redacted]", description)
                relative = path.relative_to(self.vault).as_posix()
                documents.append(RecallDocument(relative, description, body))
                terms = tokenize(description + " " + body)
                lengths[relative] = len(terms)
                for term, count in Counter(terms).items():
                    postings.setdefault(term, {})[relative] = count
            self._cache = _Snapshot(signature, day, tuple(documents), postings, lengths)
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
        snapshot = self._snapshot(force_refresh)
        scores = bm25_scores(
            tokenize(query), snapshot.postings, snapshot.lengths,
            sum(snapshot.lengths.values()) / max(1, len(snapshot.lengths)),
            len(snapshot.documents),
        )
        excluded = {*surfaced, *exclude_paths}
        ranked = sorted(
            (doc for doc in snapshot.documents
             if doc.path not in excluded and scores.get(doc.path, 0) > 0),
            key=lambda doc: (-scores[doc.path], doc.path),
        )[:max(0, limit)]
        return tuple(RecallCandidate(
            doc.path, doc.description, _excerpt(doc.body, query),
            1 / (1 + scores[doc.path]),
        ) for doc in ranked)

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
