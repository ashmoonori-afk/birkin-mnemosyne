"""Neutral atomic file writes for Mnemosyne modules.

Guarantee: readers see either the old file or the complete new file, never a
truncated one (temp sibling + ``os.replace``). The data is flushed and
``fsync``-ed before the rename, and on POSIX the parent directory is
``fsync``-ed afterwards, so the new content survives a power loss wherever the
OS and filesystem honour ``fsync``. Nothing stronger is promised.
"""

from __future__ import annotations

import os
import stat
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

# Windows can briefly refuse to replace a file another process has open
# (editors, antivirus, search indexer); retry a few times before giving up.
_REPLACE_ATTEMPTS = 10
_REPLACE_DELAY = 0.05


def _read_umask() -> int:
    # os.umask can only be read by setting it, which is racy against other
    # threads that create files. Do it once at import time, while the process
    # is effectively single-threaded, and reuse the cached value afterwards.
    mask = os.umask(0)
    _ = os.umask(mask)
    return mask


_UMASK = _read_umask()


def _replace_with_retry(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    *,
    replace: Callable[..., object] | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> None:
    """``os.replace`` that retries on ``PermissionError`` (used on Windows)."""
    do_replace = replace if replace is not None else os.replace
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            _ = do_replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            _ = sleep(_REPLACE_DELAY)


def sync_directory(directory: Path) -> None:
    """Best-effort fsync of a directory so the rename itself is durable."""
    if os.name == "nt":
        return
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _commit(tmp: Path, path: Path) -> None:
    """Give ``tmp`` the right mode, rename it over ``path``, sync the directory."""
    if os.name != "nt":
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except FileNotFoundError:
            mode = 0o666 & ~_UMASK
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    else:
        _replace_with_retry(tmp, path)
    sync_directory(path.parent)


def _write(
    path: Path, data: str | bytes, *, create: bool = False, mode: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        if isinstance(data, bytes):
            with os.fdopen(fd, "wb") as binary:
                _ = binary.write(data)
                binary.flush()
                os.fsync(binary.fileno())
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as text:
                _ = text.write(data)
                text.flush()
                os.fsync(text.fileno())
        if create:
            if os.name != "nt":
                os.chmod(tmp, mode if mode is not None else 0o666 & ~_UMASK)
            os.link(tmp, path)
            tmp.unlink()
            sync_directory(path.parent)
        else:
            _commit(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write(path: Path, text: str) -> None:
    """Atomically replace ``path`` with ``text`` (UTF-8), fsync-ed before rename."""
    _write(path, text)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Binary twin of :func:`atomic_write` (no newline translation)."""
    _write(path, data)


def atomic_create_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Publish complete bytes exclusively; never overwrite an existing path."""
    _write(path, data, create=True, mode=mode)
