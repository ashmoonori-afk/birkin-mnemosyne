"""Hermes lifecycle callbacks: durable scoped handoffs and mandatory prefetch."""

import importlib.util
import json
from pathlib import Path

import pytest

from birkin_mnemosyne import HandoffScope, HandoffStore, MemoryIndex, StartupReader

PROVIDER = Path(__file__).resolve().parents[1] / "integrations" / "hermes" / "provider.py"
SPEC = importlib.util.spec_from_file_location("mnemosyne_hermes_handoffs", PROVIDER)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

PROJECT = "mn-070-hermes"
TASK = "handoff"
OTHER_PROJECT = "mn-070-foreign"

USER_TEXT = "HERMES_USER_SENTINEL: finish the release."
ASSISTANT_TEXT = (
    "HERMES_ASSISTANT_SENTINEL: preserve this complete response.\n"
    "## Decisions\n- Retain original notes.\n"
    "## Open items\n- Run Windows CI.\n"
    "## Open questions\n- Which gate is open?\n"
    "## Next step\nOpen the PR.\n"
    "## Links\nhttps://example.invalid/42\n"
)
MESSAGES = [
    {"role": "user", "content": USER_TEXT},
    {"role": "assistant", "content": ASSISTANT_TEXT},
]


def vault_path(home):
    return Path(home) / "birkin-mnemosyne" / "vault"


def enable_store(home):
    HandoffStore(vault_path(home)).enable()


def spawn(home, **context):
    instance = module.VaultProvider()
    context.setdefault("hermes_home", str(home))
    context.setdefault("agent_context", "primary")
    instance.initialize("session-1", **context)
    return instance


def active_records(home, project=PROJECT, task: str | None = TASK):
    return HandoffStore(vault_path(home)).records(HandoffScope(project, task))


def assert_complete_bundle(context, reader, home, *, task=None, project=PROJECT, task_key=TASK):
    coverage = reader.verify(
        context, [], task=task, project_key=project, task_key=task_key)
    assert coverage.complete
    assert USER_TEXT in context
    assert ASSISTANT_TEXT.splitlines()[0] in context


def test_pre_compress_records_all_fields_and_public_receipt(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        receipt = json.loads(instance.on_pre_compress(MESSAGES))
        assert set(receipt) == {
            "path", "created", "archived", "sha256", "capture_id",
            "estimated_tokens", "warnings",
        }
        assert receipt["created"] is True
        assert receipt["archived"] is False
        assert receipt["warnings"] == []
        notes = active_records(tmp_path)
        assert len(notes) == 1
        record = notes[0].record
        assert record.event == "pre-compress"
        assert record.session_id == "session-1"
        assert record.source == "hermes"
        assert record.capture_id == receipt["capture_id"]
        assert record.fields.work == USER_TEXT + "\n\n" + ASSISTANT_TEXT
        assert record.fields.decisions == ("Retain original notes.",)
        assert record.fields.open_items == ("Run Windows CI.",)
        assert record.fields.open_questions == ("Which gate is open?",)
        assert record.fields.next_step == "Open the PR."
        assert record.fields.links == ("https://example.invalid/42",)
    finally:
        instance.shutdown()


def test_identical_replay_is_idempotent_and_fresh_instance_agrees(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        first = json.loads(instance.on_pre_compress(MESSAGES))
        repeated = json.loads(instance.on_pre_compress(MESSAGES))
        assert repeated["path"] == first["path"] == active_records(tmp_path)[0].path
        assert repeated["sha256"] == first["sha256"]
        assert repeated["created"] is False
        assert len(active_records(tmp_path)) == 1
    finally:
        instance.shutdown()
    resumed = spawn(tmp_path, project_key=PROJECT, task_key=TASK)
    try:
        replay = json.loads(resumed.on_pre_compress(MESSAGES))
        assert replay["path"] == first["path"]
        assert replay["sha256"] == first["sha256"]
        assert replay["created"] is False
        assert len(active_records(tmp_path)) == 1
    finally:
        resumed.shutdown()


def test_changed_evidence_creates_another_record(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        first = json.loads(instance.on_pre_compress(MESSAGES))
        changed = MESSAGES + [{
            "role": "assistant",
            "content": (
                "## Decisions\n- A new decision arrived.\n"
                "## Open items\n- Verify on Windows.\n"
            ),
        }]
        second = json.loads(instance.on_pre_compress(changed))
        assert second["capture_id"] != first["capture_id"]
        assert second["created"] is True
        notes = active_records(tmp_path)
        assert len(notes) == 2
        assert notes[0].record.capture_id == first["capture_id"]
        assert notes[1].record.capture_id == second["capture_id"]
        assert notes[1].record.fields.decisions == (
            "Retain original notes.", "A new decision arrived.")
        assert notes[1].record.fields.open_items == (
            "Run Windows CI.", "Verify on Windows.")
    finally:
        instance.shutdown()


def test_session_end_persists_event_and_returns_none(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(MESSAGES)
        assert instance.on_session_end(MESSAGES) is None
        latest = HandoffStore(vault_path(tmp_path)).latest(HandoffScope(PROJECT, TASK))
        assert latest is not None
        assert latest.record.event == "session-end"
        assert latest.record.session_id == "session-1"
        assert latest.record.fields.work == USER_TEXT + "\n\n" + ASSISTANT_TEXT
    finally:
        instance.shutdown()


def test_fenced_examples_are_not_declarations(tmp_path):
    enable_store(tmp_path)
    fenced = [
        {"role": "user", "content": "lead the campaign"},
        {"role": "assistant", "content": (
            "## Decisions\n- Real decision.\n"
            "```\n## Decisions\n- Fenced example must be ignored.\n"
            "## Open items\n- Also fenced.\n```\n"
            "## Open items\n- Run the suite.\n"
        )},
    ]
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(fenced)
        record = active_records(tmp_path)[0].record
        assert record.fields.decisions == ("Real decision.",)
        assert record.fields.open_items == ("Run the suite.",)
    finally:
        instance.shutdown()


def test_text_parts_and_unknown_families_stay_empty(tmp_path):
    enable_store(tmp_path)
    parts = [
        {"role": "user", "content": [
            {"type": "text", "text": "build the crate"},
            {"type": "image_url", "image_url": {"url": "https://example.invalid/x.png"}},
        ]},
        {"role": "tool", "content": "not a text role"},
        {"role": "assistant", "content": "## Summary\n- not a declared family"},
    ]
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(parts)
        record = active_records(tmp_path)[0].record
        assert record.fields.work == "build the crate\n\n## Summary\n- not a declared family"
        assert record.fields.decisions == ()
        assert record.fields.open_items == ()
        assert record.fields.open_questions == ()
        assert record.fields.next_step == ""
        assert record.fields.links == ()
    finally:
        instance.shutdown()


@pytest.mark.parametrize("bind", [
    {},
    {"task_key": TASK},
])
def test_unbound_callback_writes_nothing(tmp_path, bind):
    enable_store(tmp_path)
    instance = spawn(tmp_path, **bind)
    try:
        assert instance.on_pre_compress(MESSAGES) == ""
        assert instance.on_session_end(MESSAGES) is None
        assert active_records(tmp_path) == ()
    finally:
        instance.shutdown()


def test_disabled_store_writes_nothing_and_keeps_legacy_prefetch(tmp_path):
    vault = vault_path(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        assert instance.on_pre_compress(MESSAGES) == ""
        assert instance.prefetch("") == ""
        assert not (vault / ".mnemosyne-handoffs").exists()
    finally:
        instance.shutdown()


@pytest.mark.parametrize("context", ["subagent", "cron", "flush"])
def test_non_primary_context_never_captures(tmp_path, context):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK,
                     agent_context=context)
    try:
        assert instance.on_pre_compress(MESSAGES) == ""
        assert instance.on_session_end(MESSAGES) is None
        assert active_records(tmp_path) == ()
    finally:
        instance.shutdown()


def test_prefetch_delivers_complete_bundle_for_empty_unmatched_repeated(tmp_path):
    enable_store(tmp_path)
    vault = vault_path(tmp_path)
    (vault / "notes").mkdir(parents=True, exist_ok=True)
    (vault / "notes" / "hermes-route.md").write_text(
        "Hermes recall route stays complete.\n", encoding="utf-8")
    MemoryIndex(vault).register("Hermes handoff route", "notes/hermes-route.md")
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(MESSAGES)
        instance.on_session_end(MESSAGES)
        reader = StartupReader(vault, require_index=True)
        for query in ("", "unmatched-qxznothing", ""):
            context = instance.prefetch(query)
            task = query if query.strip() else None
            assert_complete_bundle(context, reader, tmp_path, task=task)
            assert "Hermes handoff route -> notes/hermes-route.md" in context
        assert reader.verify(
            instance.prefetch(""), [], project_key=PROJECT, task_key=TASK).complete
    finally:
        instance.shutdown()


def test_prefetch_before_any_capture_still_delivers_bundle(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        context = instance.prefetch("")
        reader = StartupReader(vault_path(tmp_path), require_index=True)
        coverage = reader.verify(context, [], project_key=PROJECT, task_key=TASK)
        assert coverage.complete
    finally:
        instance.shutdown()


def test_scope_switch_binds_new_scope_without_inherited_task(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(MESSAGES)
        instance.on_session_switch(
            "session-2", project_key=OTHER_PROJECT, reset=True)
        foreign = instance.prefetch("")
        reader = StartupReader(vault_path(tmp_path), require_index=True)
        assert reader.verify(
            foreign, [], project_key=OTHER_PROJECT, task_key=None).complete
        assert USER_TEXT not in foreign
        _ = instance.on_pre_compress(MESSAGES)
        notes = active_records(tmp_path, project=OTHER_PROJECT, task=None)
        assert len(notes) == 1
        assert notes[0].record.session_id == "session-2"
        assert notes[0].record.scope.task_key is None
        instance.on_session_switch(
            "session-3", project_key=OTHER_PROJECT, task_key="task-seven")
        _ = instance.on_pre_compress(MESSAGES)
        rebound = active_records(tmp_path, project=OTHER_PROJECT, task="task-seven")
        assert rebound[0].record.session_id == "session-3"
        assert rebound[0].record.event == "pre-compress"
    finally:
        instance.shutdown()


def test_session_only_switch_preserves_scope_and_session_identity(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(MESSAGES)
        instance.on_session_switch("session-2")
        reader = StartupReader(vault_path(tmp_path), require_index=True)
        assert_complete_bundle(instance.prefetch(""), reader, tmp_path)
        _ = instance.on_pre_compress(MESSAGES)
        notes = active_records(tmp_path)
        assert len(notes) == 2
        assert notes[1].record.session_id == "session-2"
        assert notes[1].record.capture_id != notes[0].record.capture_id
    finally:
        instance.shutdown()


def test_fresh_provider_resumes_stable_scope(tmp_path):
    enable_store(tmp_path)
    first = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = first.on_pre_compress(MESSAGES)
    finally:
        first.shutdown()
    resumed = spawn(tmp_path, project_key=PROJECT, task_key=TASK)
    try:
        reader = StartupReader(vault_path(tmp_path), require_index=True)
        assert_complete_bundle(resumed.prefetch(""), reader, tmp_path)
    finally:
        resumed.shutdown()


def test_shutdown_clears_binding(tmp_path):
    enable_store(tmp_path)
    instance = spawn(tmp_path, agent_workspace=PROJECT, task_key=TASK)
    try:
        _ = instance.on_pre_compress(MESSAGES)
    finally:
        instance.shutdown()
    assert instance.prefetch("") == ""
    assert instance.on_pre_compress(MESSAGES) == ""
    assert len(active_records(tmp_path)) == 1