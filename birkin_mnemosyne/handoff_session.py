"""Immutable host scope binding and deterministic session checkpoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from .handoff_models import HandoffReceipt, HandoffScope, require_type
from .handoff_transcript import JsonValue, checkpoint_capture_id, transcript_fields
from .handoffs import HandoffStore
from .startup import StartupReader


def _optional_key(value: JsonValue, name: str) -> str | None:
    return None if value is None else require_type(value, str, name)


@dataclass(frozen=True, slots=True)
class HandoffSession:
    store: HandoffStore
    session_id: str
    project_key: str | None
    workspace: str | None
    task_key: str | None

    def __post_init__(self) -> None:
        _ = self.scope

    @property
    def scope(self) -> HandoffScope | None:
        project = self.project_key if self.project_key is not None else self.workspace
        return None if project is None else HandoffScope(project, self.task_key)

    @classmethod
    def from_context(
        cls, store: HandoffStore, session_id: str, context: Mapping[str, JsonValue],
    ) -> HandoffSession:
        return cls(
            store, session_id,
            _optional_key(context.get("project_key"), "project_key"),
            _optional_key(context.get("agent_workspace"), "agent_workspace"),
            _optional_key(context.get("task_key"), "task_key"),
        )

    def switched(self, session_id: str, context: Mapping[str, JsonValue]) -> HandoffSession:
        project = (_optional_key(context["project_key"], "project_key")
                   if "project_key" in context else self.project_key)
        workspace = (_optional_key(context["agent_workspace"], "agent_workspace")
                     if "agent_workspace" in context else self.workspace)
        old_project = self.project_key if self.project_key is not None else self.workspace
        new_project = project if project is not None else workspace
        task = (_optional_key(context["task_key"], "task_key") if "task_key" in context
                else self.task_key if old_project == new_project else None)
        return replace(self, session_id=session_id, project_key=project,
                       workspace=workspace, task_key=task)

    def capture(
        self, messages: Sequence[JsonValue],
        event: Literal["pre-compress", "session-end"], *, primary: bool,
    ) -> HandoffReceipt | None:
        scope = self.scope
        if not primary or scope is None or not self.store.settings().enabled:
            return None
        fields = transcript_fields(messages)
        if fields is None:
            return None
        return self.store.capture(
            scope, fields, capture_id=checkpoint_capture_id(self.session_id, event, fields),
            event=event, session_id=self.session_id, source="hermes",
        )

    def prefetch(self, query: str) -> str | None:
        scope = self.scope
        if scope is None or not self.store.settings().enabled:
            return None
        return StartupReader(self.store.vault, require_index=True).read(
            [], task=query if query.strip() else None,
            project_key=scope.project_key, task_key=scope.task_key,
        ).context
