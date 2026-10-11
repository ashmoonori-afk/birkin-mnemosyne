"""MCP tools for immutable scoped handoffs: capture, read and retention fold.

Three thin adapters over the shared handoff core. Capture publishes one
immutable record per [project_key, task_key, capture_id] and is idempotent for
an identical request; read reports the scope's active history; fold previews a
curation-gated fold or applies a fresh preview plan, whose originals the
existing memory_review_undo tool restores. Scope resolution, record validation
and storage all live in the shared core, never duplicated here.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, JsonValue

from .handoff_context import required_scope
from .handoff_models import FoldResult
from .handoff_records import HandoffError, HandoffFields, HandoffNote
from .handoff_retention import HandoffRetention
from .handoffs import SOFT_BUDGET_WARNING, HandoffStore
from .memory_index import MemoryIndexError
from .memory_index_views import estimated_tokens
from .review_journal import ReviewError

__all__ = ["register_handoff_tools"]

_HANDOFF_CAPTURE = ToolAnnotations(
    title="Capture handoff", read_only_hint=False, destructive_hint=False,
    idempotent_hint=True, open_world_hint=False)
_HANDOFF_READ = ToolAnnotations(
    title="Read handoff history", read_only_hint=True, destructive_hint=False,
    idempotent_hint=True, open_world_hint=False)
_HANDOFF_FOLD = ToolAnnotations(
    title="Fold handoff history", read_only_hint=False, destructive_hint=True,
    idempotent_hint=False, open_world_hint=False)

_PROJECT_KEY = "project key (default: $MNEMOSYNE_PROJECT_KEY)"
_TASK_KEY = "task key, only with a project (default: $MNEMOSYNE_TASK_KEY)"
_Entries = Annotated[list[str] | None, Field(
    description="verbatim free-text entries, never truncated")]


def register_handoff_tools(server: MCPServer, vault: Path) -> None:
    """Register the three handoff adapters on ``server``.

    Thin wiring from ``birkin_mnemosyne._mcp_app.create_server``; the tools
    resolve their project/task scope through the shared per-process defaults.
    """
    store = HandoffStore(vault)
    retention = HandoffRetention(vault)

    def handoff_failure(
        exc: HandoffError | ReviewError | MemoryIndexError | OSError | UnicodeError,
    ) -> ToolError:
        """Surface expected library and I/O failures through the tool protocol."""
        if isinstance(exc, OSError):
            detail = exc.strerror or str(exc) or type(exc).__name__
            return ToolError(f"handoff I/O failure ({type(exc).__name__}): {detail}")
        return ToolError(str(exc))

    def note_payload(note: HandoffNote) -> dict[str, JsonValue]:
        """Complete captured fields and immutable record metadata."""
        record = note.record
        return {
            "path": note.path,
            "sha256": note.sha256,
            "scope": {"project_key": record.scope.project_key,
                      "task_key": record.scope.task_key},
            "fields": {
                "work": record.fields.work,
                "next_step": record.fields.next_step,
                "decisions": list(record.fields.decisions),
                "open_items": list(record.fields.open_items),
                "open_questions": list(record.fields.open_questions),
                "links": list(record.fields.links),
            },
            "kind": record.kind,
            "capture_id": record.capture_id,
            "recorded_at": record.recorded_at,
            "event": record.event,
            "session_id": record.session_id,
            "source": record.source,
        }

    def read_warnings(latest: HandoffNote | None) -> list[str]:
        """Soft budget warning measured from the actual raw record bytes."""
        if latest is None:
            return []
        settings = store.settings()
        estimated = estimated_tokens(latest.raw.decode("utf-8"))
        if estimated > settings.max_tokens:
            return [SOFT_BUDGET_WARNING.format(
                estimated=estimated, maximum=settings.max_tokens)]
        return []

    def fold_payload(result: FoldResult) -> dict[str, JsonValue]:
        """Convert the immutable source tuples to JSON arrays at the boundary."""
        return {
            **asdict(result),
            "accepted": [asdict(source) for source in result.accepted],
            "rejected": [asdict(source) for source in result.rejected],
        }

    @server.tool(annotations=_HANDOFF_CAPTURE)
    def memory_handoff_capture(
        capture_id: Annotated[str, Field(
            min_length=1, description="client-supplied checkpoint identity")],
        work: Annotated[str, Field(
            min_length=1, description="what was done, verbatim and complete")],
        project_key: Annotated[str | None,
                               Field(description=_PROJECT_KEY)] = None,
        task_key: Annotated[str | None, Field(description=_TASK_KEY)] = None,
        next_step: str = "",
        decisions: _Entries = None,
        open_items: _Entries = None,
        open_questions: _Entries = None,
        links: _Entries = None,
        event: Annotated[Literal["explicit", "pre-compress", "session-end"],
                         Field(description="capture event kind")] = "explicit",
        session_id: str = "",
        source: str = "api",
    ) -> dict[str, JsonValue]:
        """Persist one immutable scoped handoff capture.

        Retrying the identical request returns the original receipt with
        created=false and changes no bytes; a different payload at the same
        scope/capture_id conflicts. Record data is complete; soft warnings
        never truncate it."""
        try:
            scope = required_scope(project_key, task_key)
            fields = HandoffFields(
                work=work,
                next_step=next_step,
                decisions=tuple(decisions or ()),
                open_items=tuple(open_items or ()),
                open_questions=tuple(open_questions or ()),
                links=tuple(links or ()),
            )
            receipt = store.capture(
                scope, fields, capture_id=capture_id, event=event,
                session_id=session_id, source=source,
            )
        except (HandoffError, ReviewError, MemoryIndexError, OSError,
                UnicodeError) as exc:
            raise handoff_failure(exc) from exc
        return {**asdict(receipt), "warnings": list(receipt.warnings)}

    @server.tool(annotations=_HANDOFF_READ)
    def memory_handoff_read(
        project_key: Annotated[str | None,
                               Field(description=_PROJECT_KEY)] = None,
        task_key: Annotated[str | None, Field(description=_TASK_KEY)] = None,
    ) -> dict[str, JsonValue]:
        """Latest active handoff capture, active record count and soft
        warnings. latest carries every captured field verbatim, never
        truncated; missing history returns count 0 / latest null."""
        try:
            scope = required_scope(project_key, task_key)
            latest = store.latest(scope)
            active = store.records(scope)
            warnings = read_warnings(latest)
        except (HandoffError, ReviewError, MemoryIndexError, OSError,
                UnicodeError) as exc:
            raise handoff_failure(exc) from exc
        return {
            "count": len(active),
            "latest": note_payload(latest) if latest is not None else None,
            "warnings": [*warnings],
        }

    @server.tool(annotations=_HANDOFF_FOLD)
    def memory_handoff_fold(
        project_key: Annotated[str | None,
                               Field(description=_PROJECT_KEY)] = None,
        task_key: Annotated[str | None, Field(description=_TASK_KEY)] = None,
        keep: Annotated[int, Field(
            ge=1, description="retain the newest captures; latest is pinned")
        ] = 3,
        apply: bool = False,
        plan_id: Annotated[str | None, Field(
            description="required for apply; copy from a preview's plan_id")
        ] = None,
    ) -> dict[str, JsonValue]:
        """Preview a curation-gated fold, or apply a fresh preview plan.

        apply=false (default) writes nothing and returns a deterministic
        plan_id plus the exact accepted/rejected image list. apply=true
        requires that plan_id, rechecks every image under the vault lock and
        commits; memory_review_undo restores the archived originals."""
        try:
            scope = required_scope(project_key, task_key)
            if not apply:
                return fold_payload(retention.preview(scope, keep=keep))
            if plan_id is None:
                raise ToolError("apply=True requires plan_id from a preview")
            return fold_payload(retention.apply(scope, plan_id, keep=keep))
        except (HandoffError, ReviewError, MemoryIndexError, OSError,
                UnicodeError) as exc:
            raise handoff_failure(exc) from exc
