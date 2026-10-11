"""Host scopes and explicit transcript sections keep their original boundaries."""

import shutil
from pathlib import Path

import pytest

from birkin_mnemosyne.handoff_records import HandoffScope
from birkin_mnemosyne.handoff_transcript import transcript_fields
from birkin_mnemosyne.handoffs import HandoffStore
from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.startup import StartupError
from test_hermes_handoffs import MESSAGES, PROJECT, TASK, enable_store, module, spawn, vault_path


@pytest.mark.parametrize("damage", ["index", "record"])
def test_scoped_prefetch_surfaces_required_source_failure(tmp_path: Path, damage: str) -> None:
    enable_store(tmp_path)
    provider = spawn(tmp_path, project_key=PROJECT, task_key=TASK)
    try:
        _ = provider.on_pre_compress(MESSAGES)
        if damage == "index":
            shutil.rmtree(MemoryIndex(vault_path(tmp_path)).directory)
        else:
            note = HandoffStore(vault_path(tmp_path)).latest(HandoffScope(PROJECT, TASK))
            assert note is not None
            _ = (vault_path(tmp_path) / note.path).write_bytes(b"corrupt")
        with pytest.raises((MemoryIndexError, StartupError)):
            _ = provider.prefetch("")
    finally:
        provider.shutdown()


def test_host_preserves_nonblank_key_spelling(tmp_path: Path) -> None:
    enable_store(tmp_path)
    provider = spawn(tmp_path, project_key=" project ", task_key=" task ")
    try:
        _ = provider.on_pre_compress(MESSAGES)
        assert HandoffStore(vault_path(tmp_path)).latest(HandoffScope(" project ", " task ")) is not None
        assert HandoffStore(vault_path(tmp_path)).latest(HandoffScope("project", "task")) is None
    finally:
        provider.shutdown()


@pytest.mark.parametrize("task", ["another-task", None])
def test_task_only_switch_rebinds_without_changing_project(tmp_path: Path, task: str | None) -> None:
    enable_store(tmp_path)
    provider = spawn(tmp_path, project_key=PROJECT, task_key=TASK)
    try:
        _ = provider.on_pre_compress(MESSAGES)
        provider.on_session_switch("new-session", task_key=task)
        _ = provider.on_pre_compress(MESSAGES)
        store = HandoffStore(vault_path(tmp_path))
        assert len(store.records(HandoffScope(PROJECT, TASK))) == 1
        assert len(store.records(HandoffScope(PROJECT, task))) == 1
    finally:
        provider.shutdown()


def test_same_workspace_switch_keeps_bound_task(tmp_path: Path) -> None:
    enable_store(tmp_path)
    provider = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        provider.on_session_switch("rotated", agent_workspace=PROJECT)
        _ = provider.on_pre_compress(MESSAGES)
        note = HandoffStore(vault_path(tmp_path)).latest(HandoffScope(PROJECT, TASK))
        assert note is not None and note.record.session_id == "rotated"
    finally:
        provider.shutdown()


def test_switch_to_non_primary_context_stops_capture(tmp_path: Path) -> None:
    enable_store(tmp_path)
    provider = spawn(tmp_path, project_key=PROJECT, task_key=TASK)
    try:
        _ = provider.on_pre_compress(MESSAGES)
        provider.on_session_switch("worker", agent_context="subagent")
        provider.on_session_end(MESSAGES)
        assert len(HandoffStore(vault_path(tmp_path)).records(HandoffScope(PROJECT, TASK))) == 1
    finally:
        provider.shutdown()


def test_invalid_reinitialization_does_not_mix_old_scope_and_new_vault(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    enable_store(first)
    enable_store(second)
    provider = spawn(first, project_key=PROJECT, task_key=TASK)
    try:
        with pytest.raises(module.InvalidArgument):
            provider.initialize("other", hermes_home=str(second), project_key=" ")
        provider.on_session_end(MESSAGES)
        assert HandoffStore(vault_path(second)).records(HandoffScope(PROJECT, TASK)) == ()
        assert HandoffStore(vault_path(first)).latest(HandoffScope(PROJECT, TASK)) is not None
    finally:
        provider.shutdown()


def test_sections_do_not_consume_unheaded_followup_or_tool_output() -> None:
    fields = transcript_fields([
        {"role": "assistant", "content": "## Decisions\n- Keep originals."},
        {"role": "user", "content": "Please inspect the next file."},
        {"role": "tool", "content": "## Decisions\n- TOOL_DATA_ONLY"},
    ])
    assert fields is not None and fields.decisions == ("Keep originals.",)


def test_fence_width_and_message_boundary_are_respected() -> None:
    fields = transcript_fields([
        {"role": "assistant", "content": "````markdown\n```\n## Decisions\n- EXAMPLE_ONLY\n```\n````"},
        {"role": "assistant", "content": "```unfinished example"},
        {"role": "assistant", "content": "## Decisions\n- Keep originals."},
    ])
    assert fields is not None and fields.decisions == ("Keep originals.",)
