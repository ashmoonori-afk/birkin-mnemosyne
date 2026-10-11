"""Scoped handoff selection receipts and startup warning policy."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from .handoff_records import HandoffError, HandoffNote, HandoffScope
from .handoffs import HANDOFFS_DIRECTORY, SOFT_BUDGET_WARNING, HandoffStore
from .memory_index_views import estimated_tokens
from .startup_coverage import StartupError, digest
from .vault_lock import VaultLock

HANDOFF_SCOPE_SOURCE: str = f"{HANDOFFS_DIRECTORY}/scope"


def handoff_scope(
    project_key: str | None, task_key: str | None,
) -> HandoffScope | None:
    """Validate an optional startup scope; task_key never implies project_key."""
    if project_key is None:
        if task_key is not None:
            raise StartupError("task_key requires project_key")
        return None
    try:
        return HandoffScope(project_key, task_key)
    except HandoffError as exc:
        raise StartupError(str(exc)) from exc


def _scope_digest(scope: HandoffScope) -> str:
    """SHA-256 over the store's canonical scope identity bytes."""
    return digest(json.dumps(
        [scope.project_key, scope.task_key], ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8"))


def handoff_receipt(scope: HandoffScope, note: HandoffNote | None) -> bytes:
    """Synthetic receipt binding the scope hash and selected path/hash or null."""
    selected = None
    if note is not None:
        selected = {"path": note.path, "sha256": note.sha256}
    return json.dumps({
        "version": 1, "scope_sha256": _scope_digest(scope), "handoff": selected,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def handoff_warnings(
    store: HandoffStore | None, handoff: HandoffNote | None,
) -> tuple[str, ...]:
    """Soft warnings measured from the actual raw selected record bytes."""
    if store is None or handoff is None:
        return ()
    try:
        maximum = store.settings().max_tokens
    except HandoffError as exc:
        raise StartupError(str(exc)) from exc
    estimated = estimated_tokens(handoff.raw.decode("utf-8"))
    if estimated > maximum:
        return (SOFT_BUDGET_WARNING.format(
            estimated=estimated, maximum=maximum),)
    return ()


def scope_manager(root: Path, scope: HandoffScope | None
                   ) -> contextlib.AbstractContextManager[None]:
    """Vault-before-reader coordination; no lock at all without a scope."""
    if scope is None:
        return contextlib.nullcontext()
    return VaultLock(root).hold()
