"""Before/post image journal for explicit consolidation and checked recovery."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict

from .atomic import atomic_write_bytes
from .mnemosyne import Mnemosyne

State = Literal["prepared", "committed", "rolled-back", "recovery-required", "undone"]


class ReviewError(ValueError):
    """Unsafe, stale or incomplete review operation."""


@dataclass(frozen=True, slots=True)
class Change:
    source: str
    target: str
    before: bytes
    after: bytes


@dataclass(frozen=True, slots=True)
class Receipt:
    transaction_id: str
    state: State
    journal_path: str


class ImageRecord(TypedDict):
    source: str
    target: str
    before: str
    after: str
    before_sha256: str
    after_sha256: str


class Manifest(TypedDict):
    version: int
    transaction_id: str
    question_id: str
    choice: str
    merged_body: str
    survivor: str
    state: State
    changes: list[ImageRecord]


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | \
    dict[str, "JsonValue"]
_load_json: Callable[[str], JsonValue] = json.loads


def _decode_manifest(text: str) -> Manifest:
    """Parse the versioned disk record before trusting its image fields."""
    try:
        raw = _load_json(text)
    except ValueError as exc:
        raise ReviewError("malformed journal") from exc
    match raw:
        case {
            "version": version, "transaction_id": str() as transaction_id,
            "question_id": str() as question_id, "choice": str() as choice,
            "merged_body": str() as merged_body, "survivor": str() as survivor,
            "state": ("prepared" | "committed" | "rolled-back" |
                      "recovery-required" | "undone") as state,
            "changes": records,
        }:
            if type(version) is not int or version != 1:
                raise ReviewError("invalid journal version")
            if not isinstance(records, list):
                raise ReviewError("malformed journal changes")
            changes: list[ImageRecord] = []
            for record in records:
                match record:
                    case {
                        "source": str() as source, "target": str() as target,
                        "before": str() as before, "after": str() as after,
                        "before_sha256": str() as before_hash,
                        "after_sha256": str() as after_hash,
                    }:
                        changes.append({
                            "source": source, "target": target,
                            "before": before, "after": after,
                            "before_sha256": before_hash, "after_sha256": after_hash,
                        })
                    case _:
                        raise ReviewError("malformed journal image")
            return {
                "version": 1, "transaction_id": transaction_id,
                "question_id": question_id, "choice": choice,
                "merged_body": merged_body, "survivor": survivor,
                "state": state, "changes": changes,
            }
        case _:
            raise ReviewError("malformed journal")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save(path: Path, manifest: Manifest) -> None:
    atomic_write_bytes(path, (json.dumps(
        manifest, ensure_ascii=False, indent=2,
    ) + "\n").encode("utf-8"))


def _safe(vault: Path, relative: str) -> Path:
    path = vault / relative
    if not relative or Path(relative).is_absolute() or \
            not path.resolve().is_relative_to(vault) or path.is_symlink() or \
            not relative.endswith(".md"):
        raise ReviewError(f"unsafe journal path: {relative!r}")
    return path


def _journal_ref(vault: Path, path: Path) -> str:
    """Vault-relative journal path for error text; never the absolute path."""
    try:
        return path.relative_to(vault).as_posix()
    except ValueError:
        return path.name


def _refresh(vault: Path) -> None:
    Mnemosyne(vault).refresh()


def _restore(vault: Path, changes: tuple[Change, ...]) -> None:
    for change in changes:
        source, target = _safe(vault, change.source), _safe(vault, change.target)
        atomic_write_bytes(source, change.before)
        if target != source and target.exists():
            if target.read_bytes() != change.after:
                raise ReviewError(f"archive changed during recovery: {change.target}")
            target.unlink()
    _refresh(vault)


def commit(
    vault: Path, question_id: str, choice: str, merged_body: str,
    survivor: str, changes: tuple[Change, ...],
) -> Receipt:
    """Caller holds canonical vault lock; original bytes precede all mutations."""
    transaction_id = uuid.uuid4().hex
    path = vault / ".mnemosyne-reviews" / f"{transaction_id}.json"
    manifest: Manifest = {
        "version": 1, "transaction_id": transaction_id,
        "question_id": question_id, "choice": choice,
        "merged_body": merged_body, "survivor": survivor,
        "state": "prepared",
        "changes": [{
            "source": c.source, "target": c.target,
            "before": base64.b64encode(c.before).decode("ascii"),
            "after": base64.b64encode(c.after).decode("ascii"),
            "before_sha256": _digest(c.before), "after_sha256": _digest(c.after),
        } for c in changes],
    }
    for change in changes:
        source, target = _safe(vault, change.source), _safe(vault, change.target)
        if source.read_bytes() != change.before or \
                (source != target and target.exists()):
            raise ReviewError("transaction precondition changed")
    _save(path, manifest)
    try:
        for change in changes:
            source, target = _safe(vault, change.source), _safe(vault, change.target)
            if source != target:
                target.parent.mkdir(parents=True, exist_ok=True)
                _ = source.rename(target)
            elif change.before != change.after:
                atomic_write_bytes(target, change.after)
        _refresh(vault)
        manifest["state"] = "committed"
        _save(path, manifest)
    except (OSError, ValueError) as exc:
        try:
            _restore(vault, changes)
        except (OSError, ValueError) as rollback_error:
            manifest["state"] = "recovery-required"
            try:
                _save(path, manifest)
            except OSError:
                # The prepared journal still contains all original bytes.
                raise ReviewError(f"recovery required: {_journal_ref(vault, path)}") from rollback_error
            raise ReviewError(f"recovery required: {_journal_ref(vault, path)}") from rollback_error
        manifest["state"] = "rolled-back"
        _save(path, manifest)
        raise ReviewError(f"transaction rolled back: {_journal_ref(vault, path)}") from exc
    return Receipt(transaction_id, "committed", path.relative_to(vault).as_posix())


def undo_receipt(vault: Path, transaction_id: str) -> Receipt:
    """Validate every image before restoring any; permit checked partial recovery."""
    if not re.fullmatch(r"[a-f0-9]{32}", transaction_id):
        raise ReviewError("invalid transaction id")
    path = vault / ".mnemosyne-reviews" / f"{transaction_id}.json"
    try:
        raw = _decode_manifest(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise ReviewError("malformed journal encoding") from exc
    if raw.get("version") != 1 or raw.get("transaction_id") != transaction_id:
        raise ReviewError("invalid journal identity")
    if raw.get("state") not in {"committed", "prepared", "recovery-required"}:
        raise ReviewError("transaction is already restored")
    recovering = raw["state"] != "committed"
    changes: list[Change] = []
    for record in raw["changes"]:
        try:
            before = base64.b64decode(record["before"], validate=True)
            after = base64.b64decode(record["after"], validate=True)
        except ValueError as exc:
            raise ReviewError("malformed journal image encoding") from exc
        if _digest(before) != record["before_sha256"] or \
                _digest(after) != record["after_sha256"]:
            raise ReviewError("journal image hash mismatch")
        change = Change(record["source"], record["target"], before, after)
        source, target = _safe(vault, change.source), _safe(vault, change.target)
        source_data = source.read_bytes() if source.exists() else None
        target_data = target.read_bytes() if target.exists() else None
        post_image = target_data == after and (
            source == target or source_data is None
        )
        before_image = source_data == before and (
            source == target or target_data is None or target_data == after
        )
        if not post_image and not (recovering and before_image):
            raise ReviewError(f"post-image changed; refusing undo: {change.target}")
        changes.append(change)
    # Persist recovery intent before the first restoration write. If either
    # restoration or the terminal save fails, this phase remains retryable.
    raw["state"] = "recovery-required"
    _save(path, raw)
    try:
        _restore(vault, tuple(changes))
        raw["state"] = "undone"
        _save(path, raw)
    except (OSError, ValueError) as exc:
        raise ReviewError(f"recovery required: {_journal_ref(vault, path)}") from exc
    return Receipt(transaction_id, "undone", path.relative_to(vault).as_posix())
