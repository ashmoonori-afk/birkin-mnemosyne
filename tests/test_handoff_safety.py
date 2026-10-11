"""Real-file isolation checks at the managed handoff boundary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest

from birkin_mnemosyne.handoff_records import (
    HandoffError, HandoffFields, HandoffScope, encode_record, record_filename,
)
from birkin_mnemosyne.handoffs import HANDOFFS_DIRECTORY, HandoffStore


@pytest.mark.parametrize("operation", ["records", "latest"])
def test_foreign_record_copied_into_scope_is_rejected(
    tmp_path: Path, operation: Literal["records", "latest"],
) -> None:
    store = HandoffStore(tmp_path)
    scope = HandoffScope("project-a")
    first = store.capture(scope, HandoffFields("A only"), capture_id="a")
    foreign = store.capture(HandoffScope("project-b"), HandoffFields("B only"), capture_id="b")
    target = (tmp_path / first.path).parent / Path(foreign.path).name
    _ = target.write_bytes((tmp_path / foreign.path).read_bytes())

    reader = store.records if operation == "records" else store.latest
    with pytest.raises(HandoffError):
        _ = reader(scope)


def test_managed_directory_link_is_rejected_on_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HandoffStore(tmp_path)
    scope = HandoffScope("project")
    _ = store.capture(scope, HandoffFields("private"), capture_id="one")
    managed = tmp_path / HANDOFFS_DIRECTORY
    original = Path.is_symlink

    def linked(path: Path) -> bool:
        return path == managed or original(path)

    # Supply the exact filesystem metadata signal without requiring Windows
    # symlink privileges; storage and record decoding remain real.
    monkeypatch.setattr(Path, "is_symlink", linked)
    with pytest.raises(HandoffError):
        _ = store.latest(scope)


def test_conflicting_capture_identity_on_disk_is_rejected(tmp_path: Path) -> None:
    store = HandoffStore(tmp_path)
    scope = HandoffScope("project")
    receipt = store.capture(scope, HandoffFields("original"), capture_id="one")
    note = store.latest(scope)
    assert note is not None
    conflicting = replace(note.record, fields=HandoffFields("conflicting"))
    raw = encode_record(conflicting).encode("utf-8")
    _ = ((tmp_path / receipt.path).parent / record_filename(conflicting, raw)).write_bytes(raw)

    with pytest.raises(HandoffError):
        _ = store.latest(scope)


def test_latest_does_not_read_archived_corruption(tmp_path: Path) -> None:
    store = HandoffStore(tmp_path)
    scope = HandoffScope("project")
    old = store.capture(scope, HandoffFields("old"), capture_id="old")
    newest = store.capture(scope, HandoffFields("new"), capture_id="new")
    old_path = tmp_path / old.path
    archive = old_path.parent / "archive"
    archive.mkdir()
    archived = archive / old_path.name
    _ = old_path.rename(archived)
    _ = archived.write_bytes(b"CORRUPT_ARCHIVE")

    latest = store.latest(scope)
    assert latest is not None and latest.path == newest.path


def test_archive_aware_retry_still_rejects_archived_corruption(tmp_path: Path) -> None:
    store = HandoffStore(tmp_path)
    scope = HandoffScope("project")
    receipt = store.capture(scope, HandoffFields("original"), capture_id="one")
    path = tmp_path / receipt.path
    archive = path.parent / "archive"
    archive.mkdir()
    archived = archive / path.name
    _ = path.rename(archived)
    _ = archived.write_bytes(b"CORRUPT_ARCHIVE")

    with pytest.raises(HandoffError):
        _ = store.capture(scope, HandoffFields("original"), capture_id="one")


@pytest.mark.parametrize("operation", ["settings", "enable", "capture"])
def test_windows_reparse_root_is_refused_before_config_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    store = HandoffStore(tmp_path)
    store.managed_root.mkdir()
    original = Path.lstat

    def reparse(path: Path) -> object:
        result = original(path)
        if path == store.managed_root:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=1024)
        return result

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(HandoffError):
        if operation == "capture":
            _ = store.capture(HandoffScope("project"), HandoffFields("work"), capture_id="id")
        elif operation == "enable":
            _ = store.enable()
        else:
            _ = store.settings()
    assert not store.config_path.exists()
