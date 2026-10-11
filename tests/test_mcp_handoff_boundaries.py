"""MCP scope defaults and field-family limits must match the public core."""

from pathlib import Path

import pytest

pytest.importorskip("mcp")

from birkin_mnemosyne.handoff_records import HandoffFields, HandoffScope
from birkin_mnemosyne.handoffs import HandoffStore
from birkin_mnemosyne.startup import StartupReader
from test_mcp_handoffs import ok


@pytest.mark.parametrize("arguments,task,marker", [
    ({}, "default-task", "DEFAULT_SCOPE_SELECTED"),
    ({"task_key": "other-task"}, "other-task", "TASK_OVERRIDE_SELECTED"),
    ({"project_key": "default-project"}, None, "PROJECT_SCOPE_SELECTED"),
])
def test_startup_uses_resolved_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    arguments: dict[str, str], task: str | None, marker: str,
) -> None:
    store = HandoffStore(tmp_path)
    for key, work in (
        ("default-task", "DEFAULT_SCOPE_SELECTED"), ("other-task", "TASK_OVERRIDE_SELECTED"),
        (None, "PROJECT_SCOPE_SELECTED"),
    ):
        _ = store.capture(HandoffScope("default-project", key), HandoffFields(work), capture_id="one")
    monkeypatch.setenv("MNEMOSYNE_PROJECT_KEY", "default-project")
    monkeypatch.setenv("MNEMOSYNE_TASK_KEY", "default-task")
    result = ok(tmp_path, "memory_startup_read", {"paths": [], **arguments})
    assert marker in result["context"]
    assert StartupReader(tmp_path).verify(
        result["context"], [], project_key="default-project", task_key=task,
    ).complete


def test_startup_verify_uses_environment_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = HandoffScope("project", "task")
    _ = HandoffStore(tmp_path).capture(scope, HandoffFields("work"), capture_id="one")
    context = StartupReader(tmp_path).read([], project_key="project", task_key="task").context
    monkeypatch.setenv("MNEMOSYNE_PROJECT_KEY", "project")
    monkeypatch.setenv("MNEMOSYNE_TASK_KEY", "task")
    result = ok(tmp_path, "memory_startup_verify", {"paths": [], "context": context})
    assert result["complete"] is True


@pytest.mark.parametrize("family", ["decisions", "open_items", "open_questions", "links"])
def test_more_than_twenty_entries_are_complete_within_byte_budget(
    tmp_path: Path, family: str,
) -> None:
    entries = [f"entry {number}" for number in range(21)]
    receipt = ok(tmp_path, "memory_handoff_capture", {
        "project_key": "project", "capture_id": "one", "work": "all entries",
        family: entries,
    })
    note = HandoffStore(tmp_path).latest(HandoffScope("project"))
    assert receipt["created"] is True and note is not None
    assert list(getattr(note.record.fields, family)) == entries
