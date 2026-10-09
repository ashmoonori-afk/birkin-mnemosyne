"""Durability, file-mode and retry behaviour of the atomic write helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from birkin_mnemosyne import atomic

WRITERS = [
    pytest.param(atomic.atomic_write, "text", id="text"),
    pytest.param(atomic.atomic_write_bytes, b"bytes", id="bytes"),
]

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
@pytest.mark.parametrize(("write", "payload"), WRITERS)
def test_rewrite_keeps_existing_file_mode(tmp_path, write, payload):
    target = tmp_path / "note.md"
    target.write_bytes(b"old")
    target.chmod(0o644)
    write(target, payload)
    assert _mode(target) == 0o644


@posix_only
@pytest.mark.parametrize(("write", "payload"), WRITERS)
def test_new_file_uses_umask_default_not_0600(tmp_path, monkeypatch, write, payload):
    monkeypatch.setattr(atomic, "_UMASK", 0o022)
    target = tmp_path / "new.md"
    write(target, payload)
    assert _mode(target) == 0o644


@pytest.mark.parametrize(("write", "payload"), WRITERS)
def test_file_is_fsynced_before_replace(tmp_path, monkeypatch, write, payload):
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    def replace(src, dst):
        events.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    write(tmp_path / "n.md", payload)
    assert "fsync" in events
    assert events.index("fsync") < events.index("replace")


@posix_only
def test_parent_directory_is_fsynced_after_replace(tmp_path, monkeypatch):
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(
        os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))[1]
    )
    monkeypatch.setattr(
        os, "replace", lambda s, d: (events.append("replace"), real_replace(s, d))[1]
    )
    atomic.atomic_write(tmp_path / "n.md", "x")
    assert events == ["fsync", "replace", "fsync"]


def test_directory_fsync_failure_is_ignored(tmp_path, monkeypatch):
    real_fsync = os.fsync
    calls = {"n": 0}

    def fsync(fd):
        calls["n"] += 1
        if calls["n"] > 1:  # the second call is the directory fsync
            raise OSError("dir fsync unsupported")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    target = tmp_path / "n.md"
    atomic.atomic_write(target, "ok")
    assert target.read_text(encoding="utf-8") == "ok"


def test_replace_retry_recovers_from_transient_permission_error():
    attempts: list[tuple[str, str]] = []
    sleeps: list[float] = []

    def replace(src, dst):
        attempts.append((src, dst))
        if len(attempts) <= 2:
            raise PermissionError("held open by another process")

    atomic._replace_with_retry("a", "b", replace=replace, sleep=sleeps.append)
    assert len(attempts) == 3
    assert sleeps == [atomic._REPLACE_DELAY] * 2


def test_replace_retry_reraises_after_last_attempt():
    sleeps: list[float] = []
    calls = {"n": 0}

    def replace(src, dst):
        calls["n"] += 1
        raise PermissionError("still locked")

    with pytest.raises(PermissionError):
        atomic._replace_with_retry("a", "b", replace=replace, sleep=sleeps.append)
    assert calls["n"] == atomic._REPLACE_ATTEMPTS
    assert len(sleeps) == atomic._REPLACE_ATTEMPTS - 1


def test_replace_retry_does_not_retry_other_errors():
    calls = {"n": 0}

    def replace(src, dst):
        calls["n"] += 1
        raise FileNotFoundError("gone")

    with pytest.raises(FileNotFoundError):
        atomic._replace_with_retry("a", "b", replace=replace, sleep=lambda _s: None)
    assert calls["n"] == 1


def test_temp_file_removed_when_replace_fails(tmp_path, monkeypatch):
    def replace(src, dst):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(atomic, "_REPLACE_DELAY", 0.0)
    with pytest.raises(PermissionError):
        atomic.atomic_write(tmp_path / "n.md", "x")
    assert list(tmp_path.iterdir()) == []


def test_temp_file_removed_on_non_oserror_failure(tmp_path):
    with pytest.raises(UnicodeEncodeError):
        atomic.atomic_write(tmp_path / "n.md", "\ud800")  # lone surrogate
    assert list(tmp_path.iterdir()) == []


def test_exclusive_publication_preserves_a_late_destination(tmp_path, monkeypatch):
    target = tmp_path / "note.md"
    link = os.link
    external = b"Other writer's complete document."

    def late_link(source, destination):
        assert Path(source).read_bytes() == b"New complete document."
        Path(destination).write_bytes(external)
        link(source, destination)
    monkeypatch.setattr(os, "link", late_link)
    with pytest.raises(FileExistsError):
        atomic.atomic_create_bytes(target, b"New complete document.")
    assert target.read_bytes() == external
    assert list(tmp_path.iterdir()) == [target]
