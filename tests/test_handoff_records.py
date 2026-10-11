"""Pure codec tests for the canonical scoped handoff record contract."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from typing import TypeAlias

import pytest

from birkin_mnemosyne.handoff_records import (
    HandoffError,
    HandoffFields,
    HandoffRecord,
    HandoffScope,
    decode_record,
    encode_record,
    record_filename,
    scope_directory,
)

Replacement: TypeAlias = (
    str | int | None | HandoffScope | HandoffFields | list[str]
    | tuple[str | int, ...] | tuple[tuple[str, ...], ...]
)


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


def _encoded(record: HandoffRecord) -> tuple[bytes, str]:
    raw = encode_record(record).encode("utf-8")
    return raw, record_filename(record, raw)


def test_handoff_error_is_a_value_error() -> None:
    assert issubclass(HandoffError, ValueError)


def test_capture_round_trip_preserves_every_field() -> None:
    rec = _record(provenance=(("memory/policy.md", "ab" * 32),))
    raw, name = _encoded(rec)
    note = decode_record(raw, name)
    assert note.record == rec
    assert note.path == name
    assert note.sha256 == hashlib.sha256(raw).hexdigest()
    assert note.raw == raw


def test_summary_round_trip_with_fold_event_and_no_capture_id() -> None:
    rec = _record(kind="summary", capture_id=None, event="fold")
    raw, name = _encoded(rec)
    assert name.split("--")[1] == "summary"
    assert decode_record(raw, name).record == rec


def test_key_case_and_slashes_survive_round_trip() -> None:
    rec = _record(scope=_scope("GitHub/Repo", "Release/1.0"))
    note = decode_record(*_encoded(rec))
    assert (note.record.scope.project_key, note.record.scope.task_key) == \
        ("GitHub/Repo", "Release/1.0")


def test_windows_shaped_keys_round_trip_and_never_leak_into_directory() -> None:
    rec = _record(scope=_scope("C:\\Work\\Repo", "release"))
    note = decode_record(*_encoded(rec))
    assert note.record.scope.project_key == "C:\\Work\\Repo"
    directory = scope_directory(rec.scope)
    assert "\\" not in directory and ":" not in directory
    assert directory.startswith("cworkr--")


def test_unicode_keys_round_trip_with_original_spelling() -> None:
    rec = _record(scope=_scope("한국어-프로젝트", "タスク"))
    note = decode_record(*_encoded(rec))
    assert note.record.scope == _scope("한국어-프로젝트", "タスク")


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


def test_encoding_has_minimal_canonical_frontmatter() -> None:
    lines = encode_record(_record()).splitlines()
    assert lines[:6] == [
        "---",
        "type: handoff",
        "created: 2026-10-11T12:34:56.123456Z",
        "updated: 2026-10-11T12:34:56.123456Z",
        "tags: []",
        "---",
    ]
    assert lines[6] == ""


def test_body_is_pretty_json_with_version_one_and_every_field() -> None:
    text = encode_record(_record())
    assert "\n```json\n" in text
    body = text.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    payload = json.loads(body)
    assert payload["version"] == 1
    assert set(payload) == {
        "version", "scope", "fields", "kind", "capture_id", "recorded_at",
        "event", "session_id", "source", "provenance",
    }
    assert payload["scope"] == {"project_key": "mn-070", "task_key": "handoff"}
    assert set(payload["fields"]) == {
        "work", "next_step", "decisions", "open_items", "open_questions", "links",
    }
    assert payload["fields"]["decisions"] == ["freeze the interface"]


def test_fence_grows_beyond_longest_backtick_run_in_payload() -> None:
    content = "line\n```\nmore"
    rec = _record(fields=_fields(work=content, decisions=("````", "a ` b")))
    text = encode_record(rec)
    assert "\n`````json\n" in text
    note = decode_record(*_encoded(rec))
    assert note.record.fields.work == content
    assert note.record.fields.decisions == ("````", "a ` b")


def test_long_fence_round_trips_multiline_content_with_many_backticks() -> None:
    content = "`\n``\n```\n````\n`````\nline with ` ticks"
    rec = _record(fields=_fields(work=content, decisions=(content,), next_step=""))
    note = decode_record(*_encoded(rec))
    assert note.record.fields.work == content
    assert note.record.fields.decisions == (content,)


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_unicode_separators_survive_canonical_round_trip(separator: str) -> None:
    content = f"before{separator}after"
    rec = _record(fields=_fields(work=content, next_step=content))
    note = decode_record(*_encoded(rec))
    assert note.record.fields.work == content
    assert note.record.fields.next_step == content


def test_filename_is_stamp_kind_and_full_raw_hash() -> None:
    rec = _record()
    raw, name = _encoded(rec)
    stamp, kind, b32hash = name[:-len(".md")].split("--")
    assert stamp == "20261011T123456123456Z"
    assert kind == "capture"
    digest = hashlib.sha256(raw).digest()
    assert b32hash == base64.b32encode(digest).decode("ascii").rstrip("=").lower()


def test_filename_stamp_matches_recorded_at_leap_day() -> None:
    rec = _record(recorded_at="2024-02-29T00:00:00.000000Z")
    raw, name = _encoded(rec)
    assert name.startswith("20240229T000000000000Z--capture--")
    assert decode_record(raw, name).record.recorded_at == \
        "2024-02-29T00:00:00.000000Z"


@pytest.mark.parametrize("edit", [
    "body-work", "frontmatter-created", "frontmatter-type", "frontmatter-extra",
    "body-kind", "extra-field", "duplicate-key", "bad-version",
    "trailing-garbage", "crlf", "extra-newline",
])
def test_decode_rejects_altered_or_malformed_files(edit: str) -> None:
    raw, name = _encoded(_record())
    text = raw.decode("utf-8")
    if edit == "body-work":
        text = text.replace('"work": "finished the record codec"',
                            '"work": "tampered"')
    elif edit == "frontmatter-created":
        text = text.replace("created: 2026-10-11T12:34:56.123456Z",
                            "created: 2020-01-01T00:00:00.000000Z")
    elif edit == "frontmatter-type":
        text = text.replace("type: handoff", "type: note")
    elif edit == "frontmatter-extra":
        text = text.replace("tags: []", "tags: []\nextra: true")
    elif edit == "body-kind":
        text = text.replace('"kind": "capture"', '"kind": "summary"')
    elif edit == "extra-field":
        text = text.replace('"version": 1,', '"version": 1,\n  "extra": true,')
    elif edit == "duplicate-key":
        text = text.replace('"version": 1,', '"version": 1,\n  "version": 1,')
    elif edit == "bad-version":
        text = text.replace('"version": 1,', '"version": 2,')
    elif edit == "trailing-garbage":
        text = text.rstrip("\n") + "\ngarbage\n"
    elif edit == "crlf":
        text = text.replace("\n", "\r\n")
    elif edit == "extra-newline":
        text = text + "\n"
    with pytest.raises(HandoffError):
        _ = decode_record(text.encode("utf-8"), name)


def test_decode_rejects_hash_mismatch_between_filename_and_bytes() -> None:
    _, name = _encoded(_record())
    other = encode_record(_record(capture_id="checkpoint-2")).encode("utf-8")
    with pytest.raises(HandoffError):
        _ = decode_record(other, name)


def test_decode_rejects_wrong_kind_or_stamp_in_filename() -> None:
    raw, name = _encoded(_record())
    with pytest.raises(HandoffError):
        _ = decode_record(raw, name.replace("--capture--", "--summary--"))
    with pytest.raises(HandoffError):
        _ = decode_record(raw, name.replace("20261011T123456123456Z",
                                        "20200101T000000000000Z"))
    with pytest.raises(HandoffError):
        _ = decode_record(raw, "not-a-handoff.md")


def test_decode_rejects_empty_or_non_utf8_bytes() -> None:
    with pytest.raises(HandoffError):
        _ = decode_record(b"", "whatever.md")
    with pytest.raises(HandoffError):
        _ = decode_record(b"\xff\xfe\x00", "whatever.md")
    with pytest.raises(HandoffError):
        _ = decode_record(b"", "")


def test_decode_rejects_duplicate_or_unknown_json_fields() -> None:
    raw, name = _encoded(_record())
    text = raw.decode("utf-8")
    with pytest.raises(HandoffError):
        _ = decode_record(text.replace('"work": "finished the record codec",',
                                   '"work": "x", "work": "restated",').encode(), name)
    with pytest.raises(HandoffError):
        _ = decode_record(text.replace('"task_key": "handoff"',
                                   '"task_key": "handoff", "task_key": null').encode(),
                      name)


def test_decode_rejects_empty_task_key_inside_body() -> None:
    rec = _record(scope=_scope("mn-070", None))
    raw, name = _encoded(rec)
    text = raw.decode("utf-8").replace('"task_key": null', '"task_key": ""')
    with pytest.raises(HandoffError):
        _ = decode_record(text.encode("utf-8"), name)


def test_decode_rejects_non_integer_version() -> None:
    raw, name = _encoded(_record())
    text = raw.decode("utf-8").replace('"version": 1,', '"version": true,')
    with pytest.raises(HandoffError):
        _ = decode_record(text.encode("utf-8"), name)


def test_decode_rejects_missing_fence_and_unnamed_fence() -> None:
    raw, name = _encoded(_record())
    text = raw.decode("utf-8")
    with pytest.raises(HandoffError):
        _ = decode_record(text.replace("```json\n{", "```\n{", 1).encode(), name)
    with pytest.raises(HandoffError):
        _ = decode_record(text.replace("```json\n{", "{", 1).encode(), name)
