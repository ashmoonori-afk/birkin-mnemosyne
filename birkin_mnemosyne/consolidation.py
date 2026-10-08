"""Conservative questions, explicit answers and byte-exact reversible cleanup.

One question is applied at a time. Similarity flags possible conflict, not a
semantic truth judgement. User confirmation may retire protected notes; the
automatic curation gate is unchanged. External editors must not write during
apply/undo. Journals recover handled failures, not power-loss atomicity.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import threading
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from . import frontmatter
from .capacity import CapacityBudget, retire_candidates
from .memory import _one_line, _yaml_str
from .mnemosyne import ARCHIVE_ZONE, Mnemosyne, tokenize
from .review_journal import Change, Receipt, ReviewError, commit, undo_receipt
from .vault_lock import VaultLock

Choice = Literal[
    "keep-both", "keep-first", "keep-second", "current-first", "current-second",
    "drop-first", "drop-second", "merge",
]
RetireChoice = Literal["keep", "retire"]

#: Candidate partners kept per note (highest Jaccard similarity first, ties by
#: path order). Bounds pair generation to O(n * k) instead of O(n^2).
MAX_PAIRS_PER_NOTE = 20
#: A token present in more than this many notes is too common to pair every
#: note holding it; each such note is paired only with its MAX_PAIRS_PER_NOTE
#: nearest neighbours before and after it (path order) among those notes, so
#: a large cluster of near-identical notes still surfaces questions.
MAX_TOKEN_DF = 200
#: Questions remembered per vault so an answer can be resolved by id without
#: rescanning the vault (see Consolidation.lookup).
MAX_CACHED_QUESTIONS = 500


@dataclass(frozen=True, slots=True)
class NoteSnapshot:
    path: str
    title: str
    sha256: str
    body: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    first: NoteSnapshot
    second: NoteSnapshot
    reason: Literal["duplicate", "overlap-or-conflict"]
    similarity: float

    @property
    def text(self) -> str:
        return (
            f"{self.first.title}: {self.first.body[:120]!r} / "
            f"{self.second.title}: {self.second.body[:120]!r}. "
            "Keep both, keep one, merge, drop one, or which is current?"
        )


@dataclass(frozen=True, slots=True)
class RetireQuestion:
    """Over capacity: ask whether to keep or archive one protected note."""

    id: str
    note: NoteSnapshot
    reason: Literal["over-capacity"]
    last_access: str
    access_count: int

    @property
    def text(self) -> str:
        used = self.last_access[:10] or "never"
        return (
            f"Protected note {self.note.title!r} was last used {used} "
            f"({self.access_count} uses); the vault is over its protected-"
            "note budget. Keep it or retire it to _archive?"
        )


@dataclass(frozen=True, slots=True)
class Answer:
    question_id: str
    choice: Choice
    merged_body: str = ""
    survivor: Literal["first", "second"] = "first"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _question_id(first: NoteSnapshot, second: NoteSnapshot) -> str:
    return _hash(json.dumps(
        [(n.path, n.sha256) for n in (first, second)],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8"))


def _retire_id(note: NoteSnapshot) -> str:
    return _hash(json.dumps([note.path, note.sha256, "retire"],
                            ensure_ascii=False, separators=(",", ":"))
                 .encode("utf-8"))


def _candidate_pairs(terms: list[set[str]]) -> set[tuple[int, int]]:
    """Index pairs (j < i) worth scoring: top partners per note by similarity.

    Similarity here is Jaccard over the tokens a pair was found through; it
    equals the final score whenever no token exceeds MAX_TOKEN_DF.
    """
    postings: dict[str, list[int]] = {}
    for i, tokens in enumerate(terms):
        for token in tokens:
            postings.setdefault(token, []).append(i)
    pairs: set[tuple[int, int]] = set()
    for i, tokens in enumerate(terms):
        shared: dict[int, int] = {}
        for token in tokens:
            posting = postings[token]
            if len(posting) > MAX_TOKEN_DF:
                at = bisect_left(posting, i)
                posting = posting[max(0, at - MAX_PAIRS_PER_NOTE):
                                  at + MAX_PAIRS_PER_NOTE + 1]
            for j in posting:
                if j != i:
                    shared[j] = shared.get(j, 0) + 1
        best = heapq.nsmallest(
            MAX_PAIRS_PER_NOTE, shared.items(),
            key=lambda item: (
                -item[1] / (len(tokens) + len(terms[item[0]]) - item[1]), item[0]),
        )
        pairs.update((min(i, j), max(i, j)) for j, _ in best)
    return pairs


_CACHE_LOCK = threading.Lock()
_QUESTION_CACHE: dict[str, OrderedDict[str, Question]] = {}


def clear_question_cache() -> None:
    """Forget every remembered question (a fresh process starts empty)."""
    with _CACHE_LOCK:
        _QUESTION_CACHE.clear()


def _remember(vault: Path, questions: tuple[Question, ...]) -> None:
    with _CACHE_LOCK:
        cache = _QUESTION_CACHE.setdefault(str(vault), OrderedDict())
        for question in questions:
            cache[question.id] = question
            cache.move_to_end(question.id)
        while len(cache) > MAX_CACHED_QUESTIONS:
            cache.popitem(last=False)


class Consolidation:
    """Discover read-only candidate pairs; apply only an explicit bound answer."""

    def __init__(self, vault: str | Path) -> None:
        self.vault: Path = Path(vault).resolve()
        self.dex: Mnemosyne = Mnemosyne(self.vault)
        #: Vault-relative paths the last questions() call could not decode/parse.
        self.skipped: tuple[str, ...] = ()

    def questions(self, limit: int = 20) -> tuple[Question, ...]:
        """Return deterministic candidate pairs without changing any note."""
        self.skipped = ()
        if limit < 1:
            return ()
        with VaultLock(self.vault).hold():
            self.dex.refresh()
            notes: list[NoteSnapshot] = []
            skipped: list[str] = []
            for entry in self.dex.entries().values():
                if entry["zone"] == ARCHIVE_ZONE:
                    continue
                fields: dict[str, str | int | float | bool | None | list[str]] = entry
                relative = str(fields["rel"])
                title = str(fields["title"])
                path = self.vault / relative
                raw = path.read_bytes()
                try:
                    parsed, body = frontmatter.parse(raw.decode("utf-8"))
                except (UnicodeError, ValueError):
                    skipped.append(relative)
                    continue
                meta: dict[str, str | int | float | bool | None | list[str]] = parsed
                expiry = meta.get("expires_at")
                expired = False
                if expiry:
                    try:
                        expired = date.fromisoformat(str(expiry)) < \
                            datetime.now(timezone.utc).date()
                    except ValueError:
                        expired = False
                if expired:
                    continue
                sources = meta.get("sources")
                notes.append(NoteSnapshot(
                    path=relative, title=title, sha256=_hash(raw),
                    body=body.strip(),
                    sources=tuple(sources) if isinstance(sources, list) else (),
                ))
            self.skipped = tuple(sorted(skipped))
            notes.sort(key=lambda n: n.path)
            terms = [set(tokenize(n.body)) for n in notes]
            result: list[Question] = []
            for i, j in sorted(_candidate_pairs(terms)):
                first, second = notes[i], notes[j]
                common = terms[i] & terms[j]
                union = terms[i] | terms[j]
                similarity = len(common) / len(union) if union else 0.0
                same = " ".join(first.body.split()).casefold() == \
                    " ".join(second.body.split()).casefold()
                if not same and (len(common) < 3 or similarity < 0.55):
                    continue
                result.append(Question(
                    _question_id(first, second), first, second,
                    "duplicate" if same else "overlap-or-conflict", similarity,
                ))
            result.sort(key=lambda q: (-q.similarity, q.id))
            found = tuple(result[:limit])
            _remember(self.vault, found)
            return found

    def lookup(self, question_id: str) -> Question | None:
        """Return a remembered question if both notes are byte-identical now.

        None means the id was never listed in this process (rescan with
        questions()). A remembered question whose notes changed or vanished
        raises ReviewError; the entry ages out of the bounded cache.
        """
        with VaultLock(self.vault).hold():
            with _CACHE_LOCK:
                question = _QUESTION_CACHE.get(str(self.vault), {}).get(question_id)
            if question is None:
                return None
            for note in (question.first, question.second):
                path = self.vault / note.path
                if not path.is_file() or _hash(path.read_bytes()) != note.sha256:
                    raise ReviewError("question is stale or unknown; ask again")
            return question

    def retire_questions(self, limit: int,
                         budget: CapacityBudget) -> tuple[RetireQuestion, ...]:
        """Ask about the oldest/least-used protected notes, only when over
        budget. Read-only; undecodable notes are skipped."""
        with VaultLock(self.vault).hold():
            self.dex.refresh()
            result: list[RetireQuestion] = []
            for row in retire_candidates(self.dex, budget, limit):
                relative = str(row["rel"])
                raw = (self.vault / relative).read_bytes()
                try:
                    parsed, body = frontmatter.parse(raw.decode("utf-8"))
                except (UnicodeError, ValueError):
                    self.skipped = tuple(sorted({*self.skipped, relative}))
                    continue
                meta: dict[str, str | int | float | bool | None | list[str]] = parsed
                sources = meta.get("sources")
                note = NoteSnapshot(
                    path=relative, title=str(row["title"]),
                    sha256=_hash(raw), body=body.strip(),
                    sources=tuple(sources) if isinstance(sources, list) else (),
                )
                result.append(RetireQuestion(
                    _retire_id(note), note, "over-capacity",
                    str(row["last_access"]), int(row["access_count"]),
                ))
            return tuple(result)

    def apply_retire(self, question: RetireQuestion,
                     choice: RetireChoice) -> Receipt:
        """Journal the explicit answer; ``retire`` archives the unchanged
        note through the same reversible path as pair ``drop-*`` choices."""
        if choice not in {"keep", "retire"}:
            raise ReviewError("unknown answer choice")
        note = question.note
        if question.id != _retire_id(note):
            raise ReviewError("answer does not bind to this question")
        with VaultLock(self.vault).hold():
            self.dex.refresh()
            path = (self.vault / note.path).resolve()
            if not path.is_relative_to(self.vault) or path.is_symlink():
                raise ReviewError("unsafe note path")
            if self.dex.resolve_rel(path.stem) != note.path or \
                    note.path.startswith(("_archive/", ".")):
                raise ReviewError("note is not active at the offered path")
            if not path.is_file():
                raise ReviewError("stale question; ask again")
            raw = path.read_bytes()
            if _hash(raw) != note.sha256:
                raise ReviewError("stale question; ask again")
            target = note.path
            if choice == "retire":
                target = f"{ARCHIVE_ZONE}/{Path(note.path).name}"
                if (self.vault / target).exists():
                    raise ReviewError("archive destination already exists")
            receipt = commit(self.vault, question.id, choice, "", "first",
                             (Change(note.path, target, raw, raw),))
            self.dex.refresh()
            return receipt

    def apply(self, question: Question, answer: Answer) -> Receipt:
        """Validate both snapshots, journal exact answer, then soft-retire notes."""
        choices = {
            "keep-both", "keep-first", "keep-second", "current-first",
            "current-second", "drop-first", "drop-second", "merge",
        }
        if answer.choice not in choices or answer.survivor not in {"first", "second"}:
            raise ReviewError("unknown answer choice or survivor")
        if answer.question_id != question.id or question.id != \
                _question_id(question.first, question.second):
            raise ReviewError("answer does not bind to this question")
        if question.first.path == question.second.path:
            raise ReviewError("a question requires two distinct notes")
        if (answer.choice == "merge") != bool(answer.merged_body.strip()):
            raise ReviewError("merge alone requires a nonempty explicit body")
        with VaultLock(self.vault).hold():
            self.dex.refresh()
            originals: list[bytes] = []
            for note in (question.first, question.second):
                path = (self.vault / note.path).resolve()
                if not path.is_relative_to(self.vault) or path.is_symlink():
                    raise ReviewError("unsafe note path")
                if self.dex.resolve_rel(path.stem) != note.path or \
                        note.path.startswith(("_archive/", ".")):
                    raise ReviewError("note is not active at the offered path")
                if not path.is_file():
                    raise ReviewError("stale question; ask again")
                raw = path.read_bytes()
                if _hash(raw) != note.sha256:
                    raise ReviewError("stale question; ask again")
                _, body = frontmatter.parse(raw.decode("utf-8"))
                if body.strip() != note.body:
                    raise ReviewError("question text does not match its byte snapshot")
                originals.append(raw)
            retire = -1
            survivor = 0
            match answer.choice:
                case "keep-both":
                    pass
                case "keep-first" | "current-first" | "drop-second":
                    retire = 1
                case "keep-second" | "current-second" | "drop-first":
                    retire, survivor = 0, 1
                case "merge":
                    survivor = 0 if answer.survivor == "first" else 1
                    retire = 1 - survivor
            changes: list[Change] = []
            for i, note in enumerate((question.first, question.second)):
                target = note.path
                data = originals[i]
                if i == retire:
                    target = f"_archive/{Path(note.path).name}"
                    if (self.vault / target).exists():
                        raise ReviewError("archive destination already exists")
                elif answer.choice == "merge" and i == survivor:
                    data = _merged(originals[i], originals[1 - i],
                                   answer.merged_body)
                changes.append(Change(note.path, target, originals[i], data))
            receipt = commit(self.vault, question.id, answer.choice,
                             answer.merged_body, answer.survivor, tuple(changes))
            self.dex.refresh()
            return receipt

    def undo(self, transaction_id: str) -> Receipt:
        """Reject changed post-images; restore the exact original bytes/paths."""
        with VaultLock(self.vault).hold():
            receipt = undo_receipt(self.vault, transaction_id)
            self.dex.refresh()
            return receipt


def _version(value: object) -> int:
    """Non-numeric or missing versions count as 0, as in the MCP note tools."""
    try:
        return int(str(value or 0))
    except ValueError:
        return 0


def _merged(survivor: bytes, retired: bytes, body: str) -> bytes:
    """Retain survivor metadata, union source evidence; retired bytes are kept."""
    text = survivor.decode("utf-8")
    parsed, _ = frontmatter.parse(text)
    retired_meta, _ = frontmatter.parse(retired.decode("utf-8"))
    meta: dict[str, str | int | float | bool | None | list[str]] = parsed
    other: dict[str, str | int | float | bool | None | list[str]] = retired_meta
    own_sources = meta.get("sources")
    retired_sources = other.get("sources")
    sources = list(dict.fromkeys([
        *(own_sources if isinstance(own_sources, list) else []),
        *(retired_sources if isinstance(retired_sources, list) else []),
    ]))
    header, _ = frontmatter.split_frontmatter(text)
    lines = header.splitlines()
    for key, value in (
        ("sources", "[" + ", ".join(_yaml_str(_one_line(x)) for x in sources) + "]"),
        ("version", str(_version(meta.get("version")) + 1)),
    ):
        start = next((i for i, line in enumerate(lines)
                      if line.startswith(key + ":")), len(lines))
        end = start + 1
        while end < len(lines) and (
            lines[end].startswith((" ", "\t", "- ")) or not lines[end].strip()
        ):
            end += 1
        lines[start:end] = [f"{key}: {value}"]
    return ("---\n" + "\n".join(lines) + "\n---\n\n" +
            body.strip() + "\n").encode("utf-8")
