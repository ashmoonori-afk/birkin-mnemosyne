"""Scoped handoffs are seeded and verified alongside the startup INDEX."""

from __future__ import annotations

import json

import pytest

from birkin_mnemosyne import (
    HANDOFFS_DIRECTORY,
    HandoffFields,
    HandoffScope,
    HandoffStore,
    MemoryIndex,
    StartupError,
    StartupReader,
)
from birkin_mnemosyne.handoff_records import scope_directory
from birkin_mnemosyne.memory_index_views import estimated_tokens
from birkin_mnemosyne.startup_coverage import digest


def _store(root, *, max_tokens: int | None = None) -> HandoffStore:
    store = HandoffStore(root)
    if max_tokens is not None:
        store.enable(max_tokens=max_tokens)
    return store


def _capture(store, *, project: str = "mn-070", task_key: str | None = "handoff",
             capture_id: str = "checkpoint-1", **fields) -> None:
    values = {"work": "finished the scoped startup verification",
              "next_step": "resume the session"}
    values.update(fields)
    _ = store.capture(HandoffScope(project, task_key),
                      HandoffFields(**values), capture_id=capture_id)


def _payload(context: str):
    return json.loads(context)


def _body(context: str, path: str) -> bytes:
    blocks = sorted(
        (block for block in _payload(context)["blocks"] if block["path"] == path),
        key=lambda block: block["start_byte"],
    )
    return "".join(block["text"] for block in blocks).encode("utf-8")


def _latest(store, *, project: str = "mn-070", task_key: str | None = "handoff"):
    note = store.latest(HandoffScope(project, task_key))
    assert note is not None
    return note


def test_scoped_read_seeds_index_note_and_receipt(tmp_path):
    store = _store(tmp_path)
    _capture(store)
    reader = StartupReader(tmp_path)
    result = reader.read([], project_key="mn-070", task_key="handoff")
    note = _latest(store)
    assert result.coverage.complete
    assert _body(result.context, note.path) == note.raw
    receipt = json.loads(_body(result.context, f"{HANDOFFS_DIRECTORY}/scope"))
    assert receipt["version"] == 1
    assert receipt["handoff"] == {"path": note.path, "sha256": note.sha256}
    assert receipt["scope_sha256"] == digest(json.dumps(
        ["mn-070", "handoff"], ensure_ascii=False, separators=(",", ":")).encode())
    payload = _payload(result.context)
    assert payload["handoff_path"] == note.path
    assert payload["handoff_tokens"] == estimated_tokens(note.raw.decode("utf-8"))
    assert reader.verify(
        result.context, [], project_key="mn-070", task_key="handoff").complete


@pytest.mark.parametrize(("task", "paths"), [
    ("unmatched-query", []),
    ("deployment", []),
    (None, ["MODE.md"]),
])
def test_empty_or_unmatched_task_still_includes_latest(tmp_path, task, paths):
    (tmp_path / "MODE.md").write_bytes(b"# Mode\nRule: guard\n")
    store = _store(tmp_path)
    _capture(store)
    reader = StartupReader(tmp_path)
    result = reader.read(paths, task=task, project_key="mn-070", task_key="handoff")
    assert _body(result.context, _latest(store).path) == _latest(store).raw
    assert reader.verify(
        result.context, paths, task=task, project_key="mn-070",
        task_key="handoff").complete


def test_scope_without_captures_binds_null_handoff(tmp_path):
    MemoryIndex(tmp_path).enable()
    reader = StartupReader(tmp_path)
    result = reader.read([], project_key="mn-070", task_key="handoff")
    receipt = json.loads(_body(result.context, f"{HANDOFFS_DIRECTORY}/scope"))
    assert receipt["handoff"] is None
    payload = _payload(result.context)
    assert payload["handoff_path"] is None
    assert payload["handoff_tokens"] == 0
    assert reader.verify(
        result.context, [], project_key="mn-070", task_key="handoff").complete


def test_no_scope_preserves_existing_output(tmp_path):
    (tmp_path / "MODE.md").write_bytes(b"# Mode\nRule: guard\n")
    reader = StartupReader(tmp_path)
    result = reader.read(["MODE.md"])
    assert set(_payload(result.context)) == {"version", "complete", "files", "blocks"}
    assert result.coverage.complete
    assert reader.read(["MODE.md"]).cache_hit
    assert reader.verify(result.context, ["MODE.md"]).complete


@pytest.mark.parametrize("method", ["read", "verify"])
def test_task_key_requires_project_key(tmp_path, method):
    reader = StartupReader(tmp_path)
    with pytest.raises(StartupError, match="task_key requires project_key"):
        if method == "read":
            _ = reader.read([], task_key="handoff")
        else:
            _ = reader.verify("{}", [], task_key="handoff")
    with pytest.raises(StartupError, match="nonblank"):
        _ = reader.read([], project_key="  ")


def test_distinct_roots_select_handoffs_from_memory_index_root(tmp_path):
    identity, vault = tmp_path / "identity", tmp_path / "vault"
    identity.mkdir()
    vault.mkdir()
    (identity / "MODE.md").write_bytes(b"# Identity\nRule: guard\n")
    store = _store(vault)
    _capture(store, work="resume from the vault store")
    _capture(HandoffStore(identity), project="mn-070", task_key="handoff",
             capture_id="identity-1", work="identity copy must never appear")
    reader = StartupReader(identity, memory_index_root=vault)
    result = reader.read(["MODE.md"], project_key="mn-070", task_key="handoff")
    assert _body(result.context, _latest(store).path) == _latest(store).raw
    assert "identity copy must never appear" not in result.context
    assert reader.verify(
        result.context, ["MODE.md"], project_key="mn-070", task_key="handoff").complete


def test_handoff_payload_is_never_expanded_as_must_read(tmp_path):
    (tmp_path / "MODE.md").write_bytes(b"MUST READ: real.md\n")
    (tmp_path / "real.md").write_bytes(b"# Real\n")
    store = _store(tmp_path)
    _capture(store, work="no expansion",
             decisions=("MUST READ: missing-target.md",),
             links=("MUST READ: also-missing.md",))
    reader = StartupReader(tmp_path)
    result = reader.read(["MODE.md"], project_key="mn-070", task_key="handoff")
    paths = {record["path"] for record in _payload(result.context)["files"]}
    assert "missing-target.md" not in paths
    assert "also-missing.md" not in paths
    assert "real.md" in paths
    assert reader.verify(
        result.context, ["MODE.md"], project_key="mn-070", task_key="handoff").complete


def test_receipt_replay_under_foreign_scope_fails(tmp_path):
    store = _store(tmp_path)
    _capture(store, project="mn-070", task_key="handoff")
    _capture(store, project="other", task_key="review", capture_id="checkpoint-9")
    _capture(store, project="mn-070", task_key=None, capture_id="checkpoint-8",
             work="project-wide state")
    reader = StartupReader(tmp_path)
    context = reader.read([], project_key="mn-070", task_key="handoff").context
    assert reader.verify(
        context, [], project_key="mn-070", task_key="handoff").complete
    for foreign in (("other", "review"), ("mn-070", "review"), ("mn-070", None)):
        assert not reader.verify(
            context, [], project_key=foreign[0], task_key=foreign[1]).complete


def test_newer_capture_replaces_latest_and_stale_context_rejected(tmp_path):
    store = _store(tmp_path)
    _capture(store, capture_id="checkpoint-1", work="first session state")
    reader = StartupReader(tmp_path)
    before = reader.read([], project_key="mn-070", task_key="handoff")
    first = _latest(store)
    _capture(store, capture_id="checkpoint-2", work="second session state")
    after = reader.read([], project_key="mn-070", task_key="handoff")
    assert not after.cache_hit
    second = _latest(store)
    assert second is not first
    assert _body(after.context, second.path) == second.raw
    assert "second session state" in after.context
    assert reader.verify(
        after.context, [], project_key="mn-070", task_key="handoff").complete
    assert not reader.verify(
        before.context, [], project_key="mn-070", task_key="handoff").complete


def test_changed_handoff_record_fails_openly(tmp_path):
    store = _store(tmp_path)
    _capture(store)
    reader = StartupReader(tmp_path)
    context = reader.read([], project_key="mn-070", task_key="handoff").context
    path = tmp_path / _latest(store).path
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(StartupError):
        _ = reader.read([], project_key="mn-070", task_key="handoff")
    with pytest.raises(StartupError):
        _ = reader.verify(context, [], project_key="mn-070", task_key="handoff")


def test_missing_handoff_rejects_previous_context(tmp_path):
    store = _store(tmp_path)
    _capture(store)
    reader = StartupReader(tmp_path)
    context = reader.read([], project_key="mn-070", task_key="handoff").context
    (tmp_path / _latest(store).path).unlink()
    assert not reader.verify(
        context, [], project_key="mn-070", task_key="handoff").complete
    fresh = reader.read([], project_key="mn-070", task_key="handoff")
    assert _payload(fresh.context)["handoff_path"] is None
    assert reader.verify(
        fresh.context, [], project_key="mn-070", task_key="handoff").complete


def test_unsafe_handoff_record_fails_closed(tmp_path):
    store = _store(tmp_path)
    _capture(store)
    scope_dir = (tmp_path / HANDOFFS_DIRECTORY /
                 scope_directory(HandoffScope("mn-070", "handoff")))
    (scope_dir / "intruder.md").write_bytes(b"# forged\n")
    with pytest.raises(StartupError):
        _ = StartupReader(tmp_path).read(
            [], project_key="mn-070", task_key="handoff")


@pytest.mark.parametrize(("maximum", "expect_warning"), [(4, True), (1_000_000, False)])
def test_scoped_soft_budget_warns_from_actual_record_cost(
    tmp_path, maximum: int, expect_warning: bool,
) -> None:
    store = _store(tmp_path, max_tokens=maximum)
    _capture(store, work="probe " * 100)
    reader = StartupReader(tmp_path)
    result = reader.read([], project_key="mn-070", task_key="handoff")
    note = _latest(store)
    estimated = estimated_tokens(note.raw.decode("utf-8"))
    assert (estimated > maximum) is expect_warning
    assert (any("max_tokens" in warning for warning in result.coverage.warnings)
            is expect_warning)
    assert _payload(result.context)["handoff_tokens"] == estimated


def test_scoped_bundle_obeys_complete_file_count_bound(tmp_path):
    store = _store(tmp_path)
    _capture(store)
    index = MemoryIndex(tmp_path)
    for number in range(60):
        (tmp_path / f"rule-{number}.md").write_bytes(b"Complete rule.\n")
        index.register("reviewing deployment", f"rule-{number}.md")
    reader = StartupReader(tmp_path)
    result = reader.read([], task="deployment", project_key="mn-070", task_key="handoff")
    assert result.coverage.files == 64
    (tmp_path / "rule-60.md").write_bytes(b"Complete rule.\n")
    index.register("reviewing deployment", "rule-60.md")
    with pytest.raises(StartupError, match="64-file"):
        _ = reader.read([], task="deployment", project_key="mn-070", task_key="handoff")


def test_scoped_bundle_keeps_hard_total_budget(tmp_path):
    store = _store(tmp_path)
    _capture(store, work="keep the note modest")
    for name in ("a.md", "b.md", "c.md"):
        (tmp_path / name).write_bytes(b"x" * 700_000)
    reader = StartupReader(tmp_path)
    result = reader.read(["a.md", "b.md"], project_key="mn-070", task_key="handoff")
    assert result.coverage.complete
    with pytest.raises(StartupError, match="byte budget"):
        _ = reader.read(
            ["a.md", "b.md", "c.md"], project_key="mn-070", task_key="handoff")


@pytest.mark.parametrize("size", [1_048_576, 1_048_577])
def test_scoped_source_size_bound_never_truncates(tmp_path, size: int) -> None:
    store = _store(tmp_path)
    _capture(store)
    (tmp_path / "big.md").write_bytes(b"x" * size)
    reader = StartupReader(tmp_path)
    if size == 1_048_576:
        result = reader.read(["big.md"], project_key="mn-070", task_key="handoff")
        assert _body(result.context, "big.md") == b"x" * size
        assert result.coverage.complete
    else:
        with pytest.raises(StartupError, match="byte budget"):
            _ = reader.read(["big.md"], project_key="mn-070", task_key="handoff")