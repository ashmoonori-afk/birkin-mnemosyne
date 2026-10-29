"""Shared, reversible note mutations for MCP and local host adapters."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from .curation import evaluate_plan
from .curation_contract import PLAN_VERSION
from .handoff_transcript import JsonValue as Json
from .mnemosyne import ARCHIVE_ZONE, Mnemosyne, normalize_zone
from .vault_lock import VaultLock
from .vault_paths import archived_zone


class MutationResult(TypedDict, total=False):
    slug: str
    zone: str
    path: str
    allowed: bool
    archived: bool
    dry_run: bool
    archive_cap: int
    accepted: list[dict[str, Json]]
    dropped: list[dict[str, Json]]
    effected: list[dict[str, Json]]
    plan_ops: int
    dense_links: int


class NoteLifecycleError(ValueError):
    """A missing, ambiguous or invalid note mutation."""


def exact_note_key(dex: Mnemosyne, note: str) -> str:
    """Resolve only an exact key, vault-relative path or stored title."""
    entries = dex.entries()
    if note in entries:
        return note
    matches = [key for key, meta in entries.items()
               if note in (meta["rel"], meta["title"])]
    if len(matches) != 1:
        detail = "ambiguous note" if matches else "Note not found"
        raise NoteLifecycleError(f"{detail}: {note!r}; use an exact path or key")
    return matches[0]


def forget_note(
    dex: Mnemosyne, key: str, *, reason: str = "", confirm: bool = False,
) -> MutationResult:
    """Archive a resolved key through the gate, including its unknown-key result.

    Host adapters resolve their own identities before calling this helper.
    """
    with VaultLock(dex.vault).hold():
        meta = dex.note_meta(key)
        if meta is not None and archived_zone(meta["zone"]):
            raise NoteLifecycleError(f"note {key!r} is already forgotten "
                                     f"(zone {meta['zone']!r})")
        plan = {"plan_version": PLAN_VERSION, "summary": reason,
                "ops": [{"op": "archive", "slug": key, "reason": reason}]}
        out = evaluate_plan(dex.vault, plan, apply=confirm)
        if confirm:
            dex.refresh()
        allowed = any(o.get("op") == "archive" for o in out.accepted)
        archived = any(o.get("op") == "archive" and "error" not in o
                       for o in out.effected)
        if archived:
            assert meta is not None
            moved = dex.key_for_path(dex.vault / ARCHIVE_ZONE / meta["rel"])
            assert moved is not None
            key = moved
    result: MutationResult = {
        "slug": key, "allowed": allowed, "archived": archived,
        "dry_run": out.dry_run, "archive_cap": out.archive_cap,
        "accepted": out.accepted, "dropped": out.dropped,
        "effected": out.effected, "plan_ops": out.plan_ops,
        "dense_links": out.dense_links}
    if meta is not None:
        result["path"] = (Path(ARCHIVE_ZONE) / meta["rel"]).as_posix() if archived else meta["rel"]
    return result


def restore_note(
    dex: Mnemosyne, note: str, *, zone: str = "inbox", confirm: bool = False,
) -> MutationResult:
    """Restore an exact archived note; the target is its complete new parent."""
    if zone.strip().casefold() == ARCHIVE_ZONE:
        raise NoteLifecycleError("restore target cannot be _archive")
    try:
        target = normalize_zone(zone, allow_archive=False)
    except ValueError as exc:
        raise NoteLifecycleError(str(exc)) from exc
    with VaultLock(dex.vault).hold():
        key = exact_note_key(dex, note)
        meta = dex.note_meta(key)
        assert meta is not None
        if not archived_zone(meta["zone"]):
            raise NoteLifecycleError(f"note {key!r} is not archived "
                                     f"(zone {meta['zone'] or 'inbox'!r})")
        try:
            path = dex.rezone(key, target, dry_run=not confirm)
        except ValueError as exc:
            raise NoteLifecycleError(str(exc)) from exc
        if confirm:
            restored = dex.key_for_path(path)
            assert restored is not None
            key = restored
    return {"slug": key, "zone": target or "inbox",
            "path": path.relative_to(dex.vault).as_posix(),
            "dry_run": not confirm}
