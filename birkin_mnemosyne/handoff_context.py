"""Per-process scope defaults; the vault never stores a shared active scope."""

from __future__ import annotations

import os

from .handoff_records import HandoffError, HandoffScope


def scope_from_defaults(
    project_key: str | None = None, task_key: str | None = None,
) -> HandoffScope | None:
    if project_key is None:
        project = os.environ.get("MNEMOSYNE_PROJECT_KEY")
        task = task_key if task_key is not None else os.environ.get("MNEMOSYNE_TASK_KEY")
    else:
        project, task = project_key, task_key
    if project is None:
        if task is not None:
            raise HandoffError("task_key requires project_key")
        return None
    return HandoffScope(project, task)


def required_scope(
    project_key: str | None = None, task_key: str | None = None,
) -> HandoffScope:
    scope = scope_from_defaults(project_key, task_key)
    if scope is None:
        raise HandoffError("project_key or MNEMOSYNE_PROJECT_KEY is required")
    return scope
