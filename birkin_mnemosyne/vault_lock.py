"""Canonical cooperating-writer lock; external editors remain uncoordinated."""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable, Generator
from pathlib import Path

LOCK_FILE = ".mnemosyne-mcp.lock"
_STATES: dict[Path, _State] = {}
_GUARD = threading.Lock()


class _State:
    """Mutable lock depth, accessed only while the shared RLock is held."""

    def __init__(self) -> None:
        self.lock: threading.RLock = threading.RLock()
        self.depth: int = 0


class VaultLock:
    """Vault before note/index/profile locks; nested holds reuse the OS lock.

    Acquisition blocks until the lock is free on every platform; there is no
    timeout.
    """

    def __init__(self, vault: Path) -> None:
        self.path: Path = Path(vault).resolve() / LOCK_FILE
        with _GUARD:
            self._state: _State = _STATES.setdefault(self.path, _State())

    @contextlib.contextmanager
    def hold(self) -> Generator[None, None, None]:
        with self._state.lock:
            if self._state.depth:
                self._state.depth += 1
                try:
                    yield
                finally:
                    self._state.depth -= 1
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+b") as handle:
                _lock_file(handle.fileno())
                self._state.depth = 1
                try:
                    yield
                finally:
                    self._state.depth = 0
                    _unlock_file(handle.fileno())


def _acquire_with_retry(
    try_lock: Callable[[], None], sleep: Callable[[float], None],
) -> None:
    """Retry a non-blocking lock attempt until it succeeds (capped backoff)."""
    delay = 0.05
    while True:
        try:
            try_lock()
        except OSError:
            sleep(delay)
            delay = min(delay * 2, 0.5)
        else:
            return


if os.name == "nt":
    import msvcrt

    def _lock_file(fd: int) -> None:
        def try_lock() -> None:
            _ = os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

        _acquire_with_retry(try_lock, time.sleep)

    def _unlock_file(fd: int) -> None:
        _ = os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
