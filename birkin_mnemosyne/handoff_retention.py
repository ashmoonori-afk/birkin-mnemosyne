"""Curation-gated handoff folding with immutable publication and checked replay."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .curation_gate import validate_clamp
from .handoff_files import HANDOFFS_DIRECTORY
from .handoff_records import (
    HandoffError,
    HandoffNote,
    HandoffRecord,
    HandoffScope,
    record_filename,
    scope_directory,
)
from .handoffs import _note_order
from .mnemosyne import Mnemosyne
from .handoff_models import FoldResult, FoldSource, require_type
from .handoff_fold import _snapshot, _managed_active_notes, _fold_summary
from .handoff_fold_journal import (
    REVIEWS_DIRECTORY, fold_reviews, fold_state, question_id, replay_result, stage_summary,
)
from .review_journal import Change, ReviewError, commit
from .vault_lock import VaultLock

__all__ = ["FoldResult", "FoldSource", "HandoffRetention"]

_PLAN_ID_RE: re.Pattern[str] = re.compile(r"[0-9a-f]{64}")
_ARCHIVE_DIRECTORY: str = "archive"


@dataclass(frozen=True, slots=True)
class _FoldView:
    accepted: tuple[HandoffNote, ...]
    rejected: tuple[tuple[HandoffNote, str], ...]
    pinned: HandoffNote | None
    plan_id: str
    summary_record: HandoffRecord | None
    summary_raw: bytes
    archive_cap: int


class HandoffRetention:
    """Curation-gated fold preview and apply over one immutable store."""

    def __init__(self, vault: str | Path) -> None:
        self.vault: Path = Path(vault).resolve()

    def preview(
        self, scope: HandoffScope, keep: int = 3,
        *, now: datetime | None = None,
    ) -> FoldResult:
        """Read-only deterministic fold report over the current vault state.

        Neither the index cache nor lock files are written; all input bytes
        and mtimes stay untouched. ``keep`` retains the newest captures (the
        latest is always pinned) and only the still-active older records of
        ``scope`` are proposed to the unchanged curation gate.
        """
        keep = _checked_keep(keep)
        now = now or datetime.now(timezone.utc)
        view = _fold_view(self.vault, scope, keep, now)
        return _fold_result(view, None, "preview", "")

    def apply(
        self, scope: HandoffScope, plan_id: str, keep: int = 3,
        *, now: datetime | None = None,
    ) -> FoldResult:
        """Recheck the gate under the vault lock, then archive and publish last."""
        _ = _checked_keep(keep)
        _ = require_type(plan_id, str, "plan_id")
        if _PLAN_ID_RE.fullmatch(plan_id) is None:
            raise HandoffError("plan_id must be a 64-character hex digest")
        now = now or datetime.now(timezone.utc)
        pending, prior = fold_reviews(self.vault, scope, plan_id)
        if pending is None and prior is None:
            candidate = _fold_view(self.vault, scope, keep, now)
            if not candidate.accepted:
                if candidate.plan_id != plan_id:
                    raise ReviewError("retention plan is stale; run preview again")
                return _fold_result(candidate, None, "noop", "")
        with VaultLock(self.vault).hold():
            pending, prior = fold_reviews(self.vault, scope, plan_id)
            if pending is not None:
                raise ReviewError(f"retention fold {pending['transaction_id']} needs undo")
            if prior is not None:
                return replay_result(self.vault, prior, plan_id, keep)
            view = _fold_view(self.vault, scope, keep, now)
            if view.plan_id != plan_id:
                raise ReviewError("retention plan is stale; run preview again")
            if not view.accepted:
                return _fold_result(view, None, "noop", "")
            staging = self.vault / REVIEWS_DIRECTORY / f"fold-{plan_id}.summary.md"
            stage_summary(self.vault, staging, view.summary_raw)
            assert view.summary_record is not None
            summary_rel = _summary_target(view.summary_record, view.summary_raw)
            changes = [
                Change(note.path, _archive_target(note), note.raw, note.raw)
                for note in view.accepted
            ]
            changes.append(Change(
                staging.relative_to(self.vault).as_posix(), summary_rel,
                view.summary_raw, view.summary_raw,
            ))
            report = _fold_result(view, None, "preview", "")
            saved_report = json.dumps({"keep": keep, "result": asdict(report)},
                                      ensure_ascii=False, separators=(",", ":"))
            receipt = commit(
                self.vault, question_id(scope, plan_id), "fold", saved_report,
                summary_rel, tuple(changes),
            )
            return _fold_result(view, receipt.transaction_id, "committed", receipt.journal_path)


def _fold_view(vault: Path, scope: HandoffScope, keep: int,
               now: datetime) -> _FoldView:
    """The complete deterministic pipeline shared by preview and apply."""
    managed = _managed_active_notes(vault)
    dex = Mnemosyne(vault)
    snap = _snapshot(vault, dex, managed)
    captures = [note for note in managed
                if note.record.scope == scope and note.record.kind == "capture"]
    ordered = sorted(captures, key=_note_order)
    pinned = ordered[-1] if ordered else None
    proposed = ordered[:-keep] if len(ordered) > keep else ()
    ops = [{"op": "archive", "slug": note.path,
            "reason": "handoff retention fold"} for note in proposed]
    gate = validate_clamp({"ops": ops}, dex, snap, now=now)
    by_slug = {note.path: note for note in proposed}
    accepted = tuple(by_slug[op["slug"]] for op in gate.accepted
                     if op.get("op") == "archive")
    rejected = tuple((by_slug[drop.op["slug"]], drop.reason) for drop in gate.dropped
                     if drop.op.get("op") == "archive"
                     and drop.op.get("slug") in by_slug)
    summary_record, summary_raw = _fold_summary(scope, accepted)
    plan_id = _plan_id(vault, scope, keep, pinned, accepted, summary_raw)
    return _FoldView(accepted, rejected, pinned, plan_id,
                     summary_record, summary_raw, gate.archive_cap)


def _plan_id(
    vault: Path, scope: HandoffScope, keep: int, pinned: HandoffNote | None,
    accepted: tuple[HandoffNote, ...], summary_raw: bytes,
) -> str:
    """Digest binding scope, keep, pinned latest, accepted images, canonical
    summary bytes and the scope's fold-journal state, so a plan is only
    reusable while every one of those still matches a fresh preview."""
    binding = [
        [scope.project_key, scope.task_key],
        keep,
        pinned.sha256 if pinned is not None else None,
        [[note.path, note.sha256] for note in accepted],
        hashlib.sha256(summary_raw).hexdigest() if summary_raw else None,
        fold_state(vault, scope),
    ]
    return hashlib.sha256(json.dumps(
        binding, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _archive_target(note: HandoffNote) -> str:
    scope_dir = Path(note.path).parent
    return (f"{scope_dir.as_posix()}/{_ARCHIVE_DIRECTORY}/"
            f"{Path(note.path).name}")


def _summary_target(record: HandoffRecord, raw: bytes) -> str:
    return (f"{HANDOFFS_DIRECTORY}/{scope_directory(record.scope)}/"
            f"{record_filename(record, raw)}")


def _checked_keep(keep: int) -> int:
    if type(keep) is not int or keep < 1:
        raise HandoffError("keep must be a positive integer")
    return keep


def _fold_result(view: _FoldView, transaction_id: str | None,
                 state: Literal["preview", "committed", "idempotent", "noop"],
                 journal_path: str) -> FoldResult:
    return FoldResult(
        plan_id=view.plan_id,
        accepted=tuple(FoldSource(note.path, note.sha256,
                                  note.record.recorded_at)
                       for note in view.accepted),
        rejected=tuple(FoldSource(note.path, note.sha256,
                                  note.record.recorded_at, reason)
                       for note, reason in view.rejected),
        pinned=(FoldSource(view.pinned.path, view.pinned.sha256,
                           view.pinned.record.recorded_at)
                if view.pinned is not None else None),
        summary=view.summary_raw.decode("utf-8") if view.summary_raw else "",
        summary_sha256=(hashlib.sha256(view.summary_raw).hexdigest()
                        if view.summary_raw else ""),
        plan_archive_cap=view.archive_cap,
        transaction_id=transaction_id,
        state=state,
        journal_path=journal_path,
    )
