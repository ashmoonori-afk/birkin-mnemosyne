"""Conservative questions, explicit answers and byte-exact reversible cleanup.

One question is applied at a time. Similarity flags possible conflict, not a
semantic truth judgement. User confirmation may retire protected notes; the
automatic curation gate is unchanged. External editors must not write during
apply/undo. Journals recover handled failures, not power-loss atomicity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from . import frontmatter
from .mnemosyne import ARCHIVE_ZONE, Mnemosyne, tokenize
from .review_journal import Change, Receipt, ReviewError, commit, undo_receipt
from .vault_lock import VaultLock

Choice = Literal[
    "keep-both", "keep-first", "keep-second", "current-first", "current-second",
    "drop-first", "drop-second", "merge",
]


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


class Consolidation:
    """Discover read-only candidate pairs; apply only an explicit bound answer."""

    def __init__(self, vault: str | Path) -> None:
        self.vault: Path = Path(vault).resolve()
        self.dex: Mnemosyne = Mnemosyne(self.vault)

    def questions(self, limit: int = 20) -> tuple[Question, ...]:
        """Return deterministic candidate pairs without changing any note."""
        if limit < 1:
            return ()
        with VaultLock(self.vault).hold():
            self.dex.refresh()
            notes: list[NoteSnapshot] = []
            for entry in self.dex.entries().values():
                if entry["zone"] == ARCHIVE_ZONE:
                    continue
                fields: dict[str, str | int | float | bool | None | list[str]] = entry
                relative = str(fields["rel"])
                title = str(fields["title"])
                path = self.vault / relative
                raw = path.read_bytes()
                parsed, body = frontmatter.parse(raw.decode("utf-8"))
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
            notes.sort(key=lambda n: n.path)
            terms = [set(tokenize(n.body)) for n in notes]
            inverted: dict[str, list[int]] = {}
            pairs: set[tuple[int, int]] = set()
            for i, tokens in enumerate(terms):
                for token in tokens:
                    for j in inverted.get(token, []):
                        pairs.add((j, i))
                    inverted.setdefault(token, []).append(i)
            result: list[Question] = []
            for i, j in sorted(pairs):
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
            return tuple(result[:limit])

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
        ("sources", json.dumps(sources, ensure_ascii=False)),
        ("version", str(int(str(meta.get("version", 0))) + 1)),
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
