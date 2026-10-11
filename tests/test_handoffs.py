"""HandoffStore behavior: immutable capture, idempotence, latest and enable."""

from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from birkin_mnemosyne import (
    DEFAULT_MAX_TOKENS,
    HANDOFFS_DIRECTORY,
    HandoffError,
    HandoffFields,
    HandoffScope,
    HandoffStore,
    MemoryIndex,
)
from birkin_mnemosyne.handoff_records import scope_directory


def _scope(project: str = "mn-070", task: str | None = "handoff") -> HandoffScope:
    return HandoffScope(project, task)


def _fields(work: str = "finished the store", **overrides) -> HandoffFields:
    values = {
        "work": work,
        "next_step": "wire startup",
        "decisions": ("freeze the store contract",),
        "open_items": ("archive lookup",),
        "open_questions": ("cap policy",),
        "links": ("https://example.invalid/handoff",),
    }
    values.update(overrides)
    return HandoffFields(**values)


def _scope_dir(vault: Path, scope: HandoffScope) -> Path:
    return vault / HANDOFFS_DIRECTORY / scope_directory(scope)


def _tree(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*")}


_child = r"""
import json
import sys
from dataclasses import asdict

from birkin_mnemosyne import HandoffError, HandoffFields, HandoffScope, HandoffStore

request = json.loads(sys.stdin.read())
store = HandoffStore(request["vault"])
scope = HandoffScope(request["project_key"], request.get("task_key"))
try:
    if request["operation"] == "capture":
        fields = HandoffFields(
            work=request["work"], next_step=request.get("next_step", ""),
            decisions=tuple(request.get("decisions", [])),
            open_items=tuple(request.get("open_items", [])),
            open_questions=tuple(request.get("open_questions", [])),
            links=tuple(request.get("links", [])),
        )
        receipt = store.capture(
            scope, fields, capture_id=request["capture_id"],
            source=request.get("source", "api"),
        )
        result = {"mode": "capture", "receipt": asdict(receipt)}
    else:
        note = store.latest(scope)
        result = {"mode": "latest", "note": None}
        if note is not None:
            result["note"] = {
                "path": note.path, "sha256": note.sha256,
                "work": note.record.fields.work,
                "capture_id": note.record.capture_id,
                "raw": note.raw.decode("utf-8"),
            }
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
except HandoffError as error:
    print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
    raise SystemExit(2)
"""


def _child_result(vault: Path, request: dict[str, str]) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, "-c", _child],
        input=json.dumps({"vault": str(vault), **request}),
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert process.returncode == 0, process.stderr
    payload = json.loads(process.stdout)
    assert payload["ok"] is True, payload
    return payload["result"]


def test_fresh_process_capture_is_read_by_another_fresh_process(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    captured = _child_result(vault, {
        "operation": "capture", "project_key": "Foo", "task_key": "foo",
        "capture_id": "checkpoint-1", "work": "A_ONLY_SENTINEL: process one",
    })
    receipt = captured["receipt"]
    assert receipt["created"] is True
    path = vault / receipt["path"]
    assert path.is_file()
    assert receipt["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert str(path).startswith(str(vault / HANDOFFS_DIRECTORY))

    latest = _child_result(vault, {
        "operation": "latest", "project_key": "Foo", "task_key": "foo",
    })
    assert latest["note"] is not None
    assert "A_ONLY_SENTINEL" in latest["note"]["raw"]
    assert latest["note"]["capture_id"] == "checkpoint-1"


def test_scope_isolation_including_case_and_windows_shaped_keys(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    windows = HandoffScope("C:\\Work\\Repo", "release")
    upper = store.capture(_scope("Foo"), _fields("Foo scope"),
                          capture_id="same-id",
                          now="2026-10-11T00:00:00.000001Z")
    lower = store.capture(_scope("foo"), _fields("foo scope"),
                          capture_id="same-id",
                          now="2026-10-11T00:00:00.000002Z")
    shaped = store.capture(windows, _fields("windows scope"),
                           capture_id="same-id",
                           now="2026-10-11T00:00:00.000003Z")
    assert upper.path != lower.path and upper.path != shaped.path
    assert "\\" not in shaped.path and ":" not in shaped.path
    assert store.latest(_scope("Foo")).record.fields.work == "Foo scope"
    assert store.latest(_scope("foo")).record.fields.work == "foo scope"
    assert store.latest(windows).record.fields.work == "windows scope"


def test_changed_request_at_existing_capture_id_conflicts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    original = store.capture(_scope(), _fields("original work"),
                             capture_id="checkpoint-1")
    record_file = vault / original.path
    before = record_file.read_bytes()

    with pytest.raises(HandoffError):
        store.capture(_scope(), _fields("different work"),
                      capture_id="checkpoint-1")
    with pytest.raises(HandoffError):
        store.capture(_scope(), _fields("original work"),
                      capture_id="checkpoint-1", session_id="another-session")
    assert record_file.read_bytes() == before


def test_identical_request_across_processes_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    request = {
        "operation": "capture", "project_key": "mn-070",
        "task_key": "handoff", "capture_id": "checkpoint-1",
        "work": "original sentinel",
    }
    first = _child_result(vault, request)
    path = vault / first["receipt"]["path"]
    original = path.read_bytes()
    mtime = path.stat().st_mtime_ns

    repeated = _child_result(vault, request)
    assert repeated["receipt"]["created"] is False
    assert repeated["receipt"]["path"] == first["receipt"]["path"]
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == mtime

    conflicting = subprocess.run(
        [sys.executable, "-c", _child],
        input=json.dumps({"vault": str(vault), **request, "work": "changed"}),
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert conflicting.returncode == 2
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == mtime


def test_separate_process_captures_are_read_durably(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    request = {
        "operation": "capture", "project_key": "mn-070",
        "task_key": "handoff", "now": "2026-10-11T03:00:00.000000Z",
    }
    a = _child_result(vault, {**request, "capture_id": "cp-a",
                              "work": "AAA work of a"})
    b = _child_result(vault, {**request, "capture_id": "cp-b",
                              "work": "BBB work of b"})
    assert a["receipt"]["created"] is True
    assert b["receipt"]["created"] is True
    assert a["receipt"]["path"] != b["receipt"]["path"]

    store = HandoffStore(vault)
    notes = store.records(_scope())
    assert {note.record.fields.work for note in notes} == {
        "AAA work of a", "BBB work of b"}
    latest = _child_result(vault, {
        "operation": "latest", "project_key": "mn-070", "task_key": "handoff",
    })
    assert latest["note"]["path"] == store.latest(_scope()).path


def test_retry_after_manual_archive_returns_the_original_receipt(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    first = store.capture(_scope(), _fields("first work"),
                          capture_id="checkpoint-1",
                          now="2026-10-11T00:00:00.000000Z")
    store.capture(_scope(), _fields("second work"),
                  capture_id="checkpoint-2",
                  now="2026-10-11T00:00:00.000001Z")
    scope_dir = _scope_dir(vault, _scope())
    archive = scope_dir / "archive"
    archive.mkdir(exist_ok=True)
    name = first.path.rsplit("/", 1)[-1]
    (scope_dir / name).rename(archive / name)
    original = (archive / name).read_bytes()

    retry = store.capture(_scope(), _fields("first work"),
                          capture_id="checkpoint-1")
    assert retry.archived is True and retry.created is False
    assert retry.sha256 == first.sha256
    assert retry.path.endswith(f"/archive/{name}")
    assert (archive / name).read_bytes() == original
    assert not (scope_dir / name).exists()
    assert store.latest(_scope()).record.capture_id == "checkpoint-2"


def test_clock_rollback_never_replays_a_stored_timestamp(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    late = store.capture(_scope(), _fields("late"),
                         capture_id="late", now="2026-10-11T12:00:00.000000Z")
    early = store.capture(_scope(), _fields("early"),
                          capture_id="early", now="2026-10-11T09:00:00.000000Z")
    late_stamp = late.path.split("/")[-1].split("--")[0]
    early_stamp = early.path.split("/")[-1].split("--")[0]
    assert early_stamp > late_stamp
    assert store.latest(_scope()).record.capture_id == "early"


def test_records_and_latest_are_read_only_and_never_write(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    store.enable()
    store.capture(_scope(), _fields(), capture_id="cp-1")
    before = _tree(vault)

    notes = store.records(_scope())
    latest = store.latest(_scope())
    settings = store.settings()
    warnings = store.warnings_for(_fields())

    assert len(notes) == 1 and latest is not None
    assert settings.enabled is True
    assert warnings == ()
    assert _tree(vault) == before


def test_reads_on_an_empty_scope_are_clean(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    assert store.latest(_scope()) is None
    assert store.records(_scope()) == ()
    assert not (vault / HANDOFFS_DIRECTORY).exists()


def test_latest_ignores_archived_originals(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    first = store.capture(_scope(), _fields("old work"),
                          capture_id="old", now="2026-10-11T00:00:00.000000Z")
    store.capture(_scope(), _fields("new work"),
                  capture_id="new", now="2026-10-11T00:00:00.000001Z")
    scope_dir = _scope_dir(vault, _scope())
    archive = scope_dir / "archive"
    archive.mkdir(exist_ok=True)
    name = first.path.rsplit("/", 1)[-1]
    (scope_dir / name).rename(archive / name)
    assert store.latest(_scope()).record.capture_id == "new"
    assert len(store.records(_scope())) == 1
    assert len(store.records(_scope(), include_archive=True)) == 2


def test_config_has_enabled_state_and_default_max_tokens(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    assert store.settings().enabled is False
    assert store.settings().max_tokens == DEFAULT_MAX_TOKENS
    store.enable(max_tokens=77)
    assert store.settings().enabled is True
    assert store.settings().max_tokens == 77
    config = json.loads(
        (vault / HANDOFFS_DIRECTORY / "config.json").read_text("utf-8"))
    assert config == {"version": 1, "enabled": True, "max_tokens": 77}


def test_capture_enables_an_absent_index_without_resetting_an_existing_one(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    note = vault / "policy.md"
    note.parent.mkdir(parents=True)
    note.write_text("Keep every approval.\n")
    index = MemoryIndex(vault)
    previous = index.register("approval", "policy.md", max_tokens=17)
    before = index.path.read_bytes()

    store = HandoffStore(vault)
    captured = store.capture(_scope(), _fields(), capture_id="cp-1")
    assert captured.created is True
    assert index.path.read_bytes() == before
    assert index.read().entries == previous.entries
    assert index.read().max_tokens == 17
    assert store.settings().enabled is True


def test_receipt_estimates_tokens_and_reports_soft_budget_warning(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    big = store.capture(_scope(), _fields("word " * 5000), capture_id="big")
    file_bytes = (vault / big.path).read_bytes()
    assert big.estimated_tokens == (len(file_bytes) + 3) // 4
    assert any("estimated_tokens" in warning for warning in big.warnings)
    assert any("max_tokens" in warning for warning in big.warnings)
    small = store.capture(_scope(), _fields("small"), capture_id="small")
    assert small.warnings == ()


def test_large_active_history_recommends_retention(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    base = datetime.datetime(2026, 10, 11, tzinfo=datetime.timezone.utc)
    for index in range(21):
        store.capture(_scope(), _fields(f"work {index}"),
                      capture_id=f"cp-{index}",
                      now=base + datetime.timedelta(seconds=index))
    last = store.capture(_scope(), _fields("work 21"),
                         capture_id="cp-21",
                         now=base + datetime.timedelta(seconds=21))
    assert any("run retention" in warning for warning in last.warnings)
    assert store.records(_scope())[-1].record.capture_id == "cp-21"


def test_capture_validates_request_before_any_mutation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    with pytest.raises(HandoffError):
        store.capture(_scope(), _fields(), capture_id="cp", event="fold")
    assert not (vault / HANDOFFS_DIRECTORY).exists()
    with pytest.raises(HandoffError):
        store.capture(_scope(), _fields(), capture_id="cp",
                      now=datetime.datetime(2026, 1, 1))
    assert store.latest(_scope()) is None


def test_malformed_or_partial_owned_markdown_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope_dir = _scope_dir(vault, _scope())
    scope_dir.mkdir(parents=True)
    (scope_dir / "partial.md").write_bytes(b"---\ntype: handoff\n---\n")
    with pytest.raises(HandoffError):
        store.records(_scope())
    with pytest.raises(HandoffError):
        store.latest(_scope())
    archive = scope_dir / "archive"
    archive.mkdir()
    (archive / "partial.md").write_bytes(b"{not a record")
    with pytest.raises(HandoffError):
        store.records(_scope(), include_archive=True)


def test_symlinked_ancestors_are_refused(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope_dir = _scope_dir(vault, _scope())
    scope_dir.mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    (scope_dir / "archive").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(HandoffError):
        store.records(_scope())
    with pytest.raises(HandoffError):
        store.latest(_scope())


def test_private_staging_directories_are_ignored(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope_dir = _scope_dir(vault, _scope())
    scope_dir.mkdir(parents=True)
    staging = scope_dir / ".mnemosyne-reviews"
    staging.mkdir()
    (staging / "partial.md").write_bytes(b"---\nbroken\n")
    (scope_dir / "ignore-me.txt").write_text("not owned markdown")
    assert store.records(_scope()) == ()
    assert store.latest(_scope()) is None


def test_one_mib_raw_cap_is_enforced_before_publication(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    with pytest.raises(HandoffError):
        store.capture(_scope(), _fields("한 " * 350_000), capture_id="huge")
    assert store.latest(_scope()) is None
    assert store.records(_scope()) == ()
    config = vault / HANDOFFS_DIRECTORY / "config.json"
    assert config.is_file()


def test_repeat_request_in_one_process_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    first = store.capture(_scope(), _fields("same work"),
                          capture_id="checkpoint-1",
                          now="2026-10-11T00:00:00.000000Z")
    file_path = vault / first.path
    original = file_path.read_bytes()
    mtime = file_path.stat().st_mtime_ns
    repeated = store.capture(_scope(), _fields("same work"),
                             capture_id="checkpoint-1",
                             now="2026-10-11T00:00:00.000000Z")
    assert repeated.created is False and repeated.path == first.path
    assert repeated.sha256 == first.sha256
    assert file_path.read_bytes() == original
    assert file_path.stat().st_mtime_ns == mtime
    assert len(store.records(_scope())) == 1


def test_separate_process_conflict_changes_no_bytes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    request = {
        "operation": "capture", "project_key": "mn-070",
        "task_key": "handoff", "capture_id": "checkpoint-1",
        "work": "original sentinel",
    }
    first = _child_result(vault, request)
    record_path = vault / first["receipt"]["path"]
    original = record_path.read_bytes()

    repeated = _child_result(vault, request)
    assert repeated["receipt"]["created"] is False
    assert record_path.read_bytes() == original
