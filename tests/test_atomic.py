"""Durability, file-mode and retry behaviour of the atomic write helpers."""

from __future__ import annotations

import errno
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


@pytest.mark.parametrize("code", [errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS])
def test_exclusive_publication_without_hard_links(tmp_path: Path, monkeypatch, code: int):
    # Given a filesystem that refuses hard-link publication.
    def no_link(source, destination):
        raise OSError(code, "hard links not supported", str(destination))

    monkeypatch.setattr(os, "link", no_link)
    target = tmp_path / "note.md"
    payload = b"Complete binary image\r\n\x00\xff"

    # When complete bytes are published exclusively.
    atomic.atomic_create_bytes(target, payload)

    # Then exact bytes are durable and no temporary sibling remains.
    assert target.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("windows_code", [1, 50])
def test_windows_unsupported_link_uses_exclusive_copy(tmp_path, monkeypatch, windows_code):
    # Given Windows' invalid-function or unsupported-operation error.
    class UnsupportedWindowsLink(OSError):
        winerror = windows_code

    def no_link(source, destination):
        raise UnsupportedWindowsLink(errno.EINVAL, "unsupported link", str(destination))

    monkeypatch.setattr(os, "link", no_link)
    target = tmp_path / "note.md"

    # When the portable errno alone does not identify missing hard-link support.
    atomic.atomic_create_bytes(target, b"Complete Windows image.")

    # Then exclusive creation still succeeds without replacing an arrival.
    assert target.read_bytes() == b"Complete Windows image."
    assert list(tmp_path.iterdir()) == [target]


def test_no_hardlink_fallback_never_replaces_destination_arrival(tmp_path, monkeypatch):
    # Given an owner file arriving at the unsupported-link boundary.
    target = tmp_path / "note.md"
    external = b"Owner's new complete image."

    def arrival(source, destination):
        Path(destination).write_bytes(external)
        raise OSError(errno.EOPNOTSUPP, "hard links not supported", str(destination))

    monkeypatch.setattr(os, "link", arrival)

    # When exclusive publication encounters that arrival.
    with pytest.raises(FileExistsError):
        atomic.atomic_create_bytes(target, b"Reviewed replacement.")

    # Then the owner's file is retained and temporary staging is removed.
    assert target.read_bytes() == external
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("code", [errno.EIO, errno.ENOSPC, errno.EACCES])
def test_exclusive_publication_propagates_real_link_errors(tmp_path, monkeypatch, code):
    # Given an I/O or permission failure, rather than unsupported linking.
    def fail_link(source, destination):
        raise OSError(code, "injected link failure", str(destination))

    monkeypatch.setattr(os, "link", fail_link)

    # When publication fails at that boundary.
    with pytest.raises(OSError) as caught:
        atomic.atomic_create_bytes(tmp_path / "note.md", b"Complete bytes.")

    # Then no fallback or public destination was created.
    assert caught.value.errno == code
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("boundary", ["short", "zero", "write-error", "fsync-error"])
def test_no_hardlink_copy_progress_and_failure_ownership(tmp_path, monkeypatch, boundary):
    # Given an unsupported link and a deterministic descriptor fault.
    target = tmp_path / "note.md"
    payload = b"Complete binary image."
    real_write, real_fsync = os.write, os.fsync

    def no_link(source, destination):
        raise OSError(errno.EPERM, "hard links not supported", str(destination))

    def write(fd, data):
        if boundary == "zero":
            return 0
        if boundary == "write-error":
            real_write(fd, data[:3])
            raise OSError(errno.EIO, "injected copy write failure")
        return real_write(fd, data[:3] if boundary == "short" else data)

    def fsync(fd):
        if boundary == "fsync-error" and target.exists():
            raise OSError(errno.EIO, "injected destination fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", fsync)

    # When the exclusive descriptor is copied.
    if boundary == "short":
        atomic.atomic_create_bytes(target, payload)
        assert target.read_bytes() == payload
    else:
        with pytest.raises(atomic.ExclusiveCopyError):
            atomic.atomic_create_bytes(target, payload)
        assert target.read_bytes() == {
            "zero": b"", "write-error": payload[:3], "fsync-error": payload,
        }[boundary]

    # Then successful copies are complete; uncertain public files are never unlinked.
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("replacement", [b"Owner arrival.", b"Complete binary image."])
def test_no_hardlink_copy_rejects_replaced_inode_without_unlink(tmp_path, monkeypatch, replacement):
    # Given a new inode arriving just before descriptor verification.
    target = tmp_path / "note.md"
    real_fsync = os.fsync
    arrived = False
    blocked = False

    def no_link(source, destination):
        raise OSError(errno.EPERM, "hard links not supported", str(destination))

    def fsync(fd):
        nonlocal arrived, blocked
        result = real_fsync(fd)
        if target.exists() and not arrived:
            arrived = True
            arrival = tmp_path / "arrival"
            arrival.write_bytes(replacement)
            try:
                os.replace(arrival, target)
            except PermissionError:
                if os.name != "nt":
                    raise
                blocked = True
                raise
        return result

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "fsync", fsync)

    # When completion discovers that its public pathname changed ownership.
    with pytest.raises(atomic.ExclusiveCopyError):
        atomic.atomic_create_bytes(target, b"Complete binary image.")

    # Then even an identical-byte replacement remains untouched.
    assert target.read_bytes() == (b"Complete binary image." if blocked else replacement)
    if blocked:
        assert (tmp_path / "arrival").read_bytes() == replacement
        assert set(tmp_path.iterdir()) == {target, tmp_path / "arrival"}
    else:
        assert list(tmp_path.iterdir()) == [target]


@posix_only
def test_no_hardlink_copy_preserves_explicit_mode(tmp_path, monkeypatch):
    # Given a captured permission mode and a filesystem without links.
    def no_link(source, destination):
        raise OSError(errno.EPERM, "hard links not supported", str(destination))

    monkeypatch.setattr(os, "link", no_link)
    target = tmp_path / "note.md"

    # When the captured mode is explicitly requested.
    atomic.atomic_create_bytes(target, b"Complete bytes.", mode=0o640)

    # Then descriptor mode changes preserve the requested permission bits.
    assert _mode(target) == 0o640


def test_no_hardlink_copy_detects_in_place_interference(tmp_path, monkeypatch):
    # Given an in-place edit before completeness verification.
    target = tmp_path / "note.md"
    real_fsync = os.fsync
    changed = False
    external = b"Owner's changed bytes."

    def no_link(source, destination):
        raise OSError(errno.EPERM, "hard links not supported", str(destination))

    def fsync(fd):
        nonlocal changed
        result = real_fsync(fd)
        if target.exists() and not changed:
            changed = True
            target.write_bytes(external)
        return result

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "fsync", fsync)

    # When the owned descriptor no longer contains the expected image.
    with pytest.raises(atomic.ExclusiveCopyError):
        atomic.atomic_create_bytes(target, b"Reviewed complete bytes.")

    # Then the changed destination stays intact, never cleaned up by pathname.
    assert target.read_bytes() == external
    assert list(tmp_path.iterdir()) == [target]


def test_no_hardlink_copy_fsyncs_destination_before_success(tmp_path, monkeypatch):
    # Given a copy that needs both staging and destination synchronization.
    target = tmp_path / "note.md"
    real_fsync = os.fsync
    files: list[tuple[int, int]] = []

    def no_link(source, destination):
        raise OSError(errno.EPERM, "hard links not supported", str(destination))

    def fsync(fd):
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode):
            files.append((info.st_dev, info.st_ino))
        return real_fsync(fd)

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "fsync", fsync)

    # When exclusive copying reports success.
    atomic.atomic_create_bytes(target, b"Complete bytes.")

    # Then the staged and actual destination files were independently synced.
    final = target.stat()
    assert len(files) == 2 and files[0] != files[1]
    assert files[1] == (final.st_dev, final.st_ino)
