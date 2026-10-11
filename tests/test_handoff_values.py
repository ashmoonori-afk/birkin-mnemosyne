"""Boundary validation for immutable handoff values."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import TypeAlias

import pytest

from birkin_mnemosyne.handoff_records import (
    HandoffError, HandoffFields, HandoffNote, HandoffReceipt, HandoffRecord,
    HandoffScope, encode_record, scope_directory,
)

Replacement: TypeAlias = (
    str | int | None | HandoffScope | HandoffFields | list[str]
    | tuple[str | int, ...] | tuple[tuple[str, ...], ...]
)


def test_handoff_error_is_a_value_error() -> None:
    assert issubclass(HandoffError, ValueError)


def _scope(project: str = "mn-070", task: str | None = "handoff") -> HandoffScope:
    return HandoffScope(project, task)


def _fields(**overrides: Replacement) -> HandoffFields:
    return replace(HandoffFields(
        work="finished the record codec", next_step="wire the store",
        decisions=("freeze the interface",), open_items=("store integration",),
        open_questions=("fence length policy",), links=("https://example.test/handoff",),
    ), **overrides)


def _record(**overrides: Replacement) -> HandoffRecord:
    return replace(HandoffRecord(
        _scope(), _fields(), "capture", "checkpoint-1",
        "2026-10-11T12:34:56.123456Z", "explicit",
    ), **overrides)


def test_non_ascii_keys_get_deterministic_readable_label_fallbacks() -> None:
    directory = scope_directory(_scope("한국어-프로젝트", "タスク"))
    assert directory.startswith("proj--task--")


def test_scope_directories_distinguish_case_and_null_task() -> None:
    assert scope_directory(HandoffScope("Foo")) != scope_directory(HandoffScope("foo"))
    assert scope_directory(HandoffScope("mn-070", None)) != \
        scope_directory(HandoffScope("mn-070", "release"))
    assert scope_directory(HandoffScope("Foo", None)) != \
        scope_directory(HandoffScope("foo", None))


def test_scope_directory_uses_full_lower_unpadded_base32_of_canonical_json() -> None:
    directory = scope_directory(HandoffScope("mn-070", "release"))
    label, sep, suffix = directory.rpartition("--")
    assert sep == "--"
    assert label == "mn-070--releas"
    assert len(suffix) == 52
    assert suffix == suffix.lower() and "=" not in suffix
    canonical = json.dumps(["mn-070", "release"], ensure_ascii=False,
                           separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    assert suffix == base64.b32encode(digest).decode("ascii").rstrip("=").lower()


def test_scope_labels_are_at_most_six_characters() -> None:
    for directory in (
        scope_directory(_scope("very-long-project-name", "extra-long-task-name")),
        scope_directory(_scope("한국어", "タスク")),
    ):
        pieces = directory.split("--")
        assert all(len(piece) <= 6 for piece in pieces[:-1])
        assert len(pieces[-1]) == 52


def test_scope_directory_is_deterministic() -> None:
    first = scope_directory(_scope("프로젝트", None))
    second = scope_directory(_scope("프로젝트", None))
    assert first == second


def test_null_task_is_distinct_from_every_task_spelling() -> None:
    directory = scope_directory(HandoffScope("mn-070", None))
    for task in ("", " ", "release", "Release", "release/1.0"):
        if task.strip():
            assert scope_directory(HandoffScope("mn-070", task)) != directory
    with pytest.raises(HandoffError):
        _ = HandoffScope("mn-070", "")


@pytest.mark.parametrize("bad", ["", "   ", "\n", "a\x00b", "tab\there"])
def test_blank_or_control_task_keys_are_rejected(bad: str) -> None:
    with pytest.raises(HandoffError):
        _ = HandoffScope("project", bad)


@pytest.mark.parametrize("bad", ["", " ", "a\x1fb", "a\x85b"])
def test_blank_or_control_project_keys_are_rejected(bad: str) -> None:
    with pytest.raises(HandoffError):
        _ = HandoffScope(bad, None)


@pytest.mark.parametrize("stamp", [
    "0000-02-01T12:34:56.123456Z",
    "2026-10-11T12:34:56.12345Z",
    "2026-10-11T12:34:56.123456",
    "2026-10-11T12:34:56.123456z",
    "2026-10-11 12:34:56.123456Z",
    "2026-02-30T12:34:56.123456Z",
    "2026-13-01T12:34:56.123456Z",
    "2026-10-11T24:00:00.123456Z",
    "2026-10-11T12:34:60.123456Z",
])
def test_invalid_timestamps_are_rejected(stamp: str) -> None:
    with pytest.raises(HandoffError):
        _ = _record(recorded_at=stamp)


@pytest.mark.parametrize("overrides", [
    {"kind": "summary", "capture_id": "id-1", "event": "fold"},
    {"kind": "summary", "capture_id": None, "event": "explicit"},
    {"kind": "capture", "capture_id": None, "event": "explicit"},
    {"kind": "capture", "capture_id": "id-1", "event": "fold"},
    {"kind": "digest", "capture_id": "id-1", "event": "explicit"},
    {"kind": "capture", "capture_id": "id-1", "event": "auto"},
])
def test_invalid_kind_capture_event_combinations_are_rejected(overrides: Mapping[str, Replacement]) -> None:
    with pytest.raises(HandoffError):
        _ = _record(**overrides)


@pytest.mark.parametrize("bad_work", ["", "   ", 7, None])
def test_blank_or_non_string_work_is_rejected(bad_work: str | int | None) -> None:
    with pytest.raises(HandoffError):
        _ = _fields(work=bad_work)


def test_empty_and_unknown_next_step_are_accepted() -> None:
    for value in ("", "unknown"):
        rec = _record(fields=_fields(work="done", next_step=value))
        assert rec.fields.next_step == value


@pytest.mark.parametrize("name", ["decisions", "open_items", "open_questions", "links"])
def test_tuple_fields_reject_blank_non_string_or_list_values(name: str) -> None:
    with pytest.raises(HandoffError):
        _ = _fields(**{name: ("ok", "")})
    with pytest.raises(HandoffError):
        _ = _fields(**{name: ("ok", 7)})
    with pytest.raises(HandoffError):
        _ = _fields(**{name: ["ok"]})


def test_provenance_requires_full_hex_hash_pairs() -> None:
    rec = _record(provenance=(("mem/a.md", "ab" * 32),))
    assert rec.provenance == (("mem/a.md", "ab" * 32),)
    upper = _record(provenance=(("mem/a.md", "AB" * 32),))
    assert upper.provenance[0][1] == "AB" * 32
    with pytest.raises(HandoffError):
        _ = _record(provenance=(("mem/a.md", "abc"),))
    with pytest.raises(HandoffError):
        _ = _record(provenance=(("mem/a.md", "z" * 64),))
    with pytest.raises(HandoffError):
        _ = _record(provenance=(("mem/a.md", "ab" * 32, "extra"),))
    with pytest.raises(HandoffError):
        _ = _record(provenance=(("mem/a.md",),))


def test_note_requires_matching_raw_hash() -> None:
    rec = _record()
    raw = encode_record(rec).encode("utf-8")
    with pytest.raises(HandoffError):
        _ = HandoffNote(rec, "x.md", raw, "00" * 32)


def test_receipt_validates_machine_fields() -> None:
    receipt = HandoffReceipt("scope/x.md", True, False, "ab" * 32,
                             "checkpoint-1", 123, ("soft threshold",))
    assert receipt.estimated_tokens == 123
    with pytest.raises(HandoffError):
        _ = HandoffReceipt("", True, False, "ab" * 32, "id", 0, ())
    with pytest.raises(HandoffError):
        _ = replace(receipt, created=1)
    with pytest.raises(HandoffError):
        _ = HandoffReceipt("x.md", True, False, "ab" * 32, "id", -1, ())
    with pytest.raises(HandoffError):
        _ = HandoffReceipt("x.md", True, False, "ab" * 32, "id", 0, ("",))
