"""Exclusive pure-move journal helpers: publication and checked inverse moves.

A pure move detaches a source note from the public vault and publishes it at
a different target path. These helpers never replace a public destination:
the target is created exclusively and the source is captured into a private
transaction-owned slot where both images are verified before the move is
reported durable. The inverse move restores the source exclusively and
detaches the public target into another private slot before checking its bytes.
A racing arrival is retained in that slot and reported as a conflict, never
unlinked after a stale pathname check.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from .atomic import atomic_create_bytes, sync_directory

class MoveError(ValueError):
    """Conflicting or unverifiable move state; every image is retained."""


def _capture_tag(captures: Path, path: Path) -> str:
    """Stable per-path tag so captures never collide across same-stem notes."""
    relative = path.relative_to(captures.parent.parent).as_posix()
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]


def find_source_capture(captures: Path, source: Path) -> Path | None:
    """Locate the private capture of *source* for this transaction, if any."""
    prefix = f"{source.stem[:24]}-{_capture_tag(captures, source)}-"
    return _find_snapshot(captures, prefix, "source.snapshot")


def find_target_capture(captures: Path, target: Path) -> Path | None:
    """Locate a private verified capture of *target*, created by inverse moves."""
    prefix = f"t-{target.stem[:24]}-{_capture_tag(captures, target)}-"
    return _find_snapshot(captures, prefix, "target.snapshot")


def _find_snapshot(captures: Path, prefix: str, name: str) -> Path | None:
    if not captures.is_dir():
        return None
    for directory in captures.glob(f"{prefix}*"):
        snapshot = directory / name
        if snapshot.is_file() or snapshot.is_symlink():
            return snapshot
    return None


def _require_owned_captures(captures: Path) -> None:
    if captures.is_symlink() or not captures.resolve().is_relative_to(
            captures.parent.parent,
    ):
        raise MoveError("unsafe source capture directory")


def publish_move(
    captures: Path, source: Path, target: Path, before: bytes, after: bytes,
) -> None:
    """Publish *target* exclusively, then capture and verify the moved source.

    The public target is created with :func:`~birkin_mnemosyne.atomic.
    atomic_create_bytes` so any arrival at the destination raises
    :class:`FileExistsError` and nothing is moved. The source is then detached
    into a fresh private slot and both images are verified; an unverifiable
    image raises :class:`MoveError` with every byte retained for the caller to
    mark recovery-required.
    """
    _require_owned_captures(captures)
    mode = stat.S_IMODE(source.stat().st_mode)
    atomic_create_bytes(target, after, mode=mode)
    captures.mkdir(parents=True, exist_ok=True)
    prefix = f"{source.stem[:24]}-{_capture_tag(captures, source)}-"
    directory = Path(tempfile.mkdtemp(dir=captures, prefix=prefix))
    slot = directory / "source.snapshot"
    _ = os.rename(source, slot)
    if not stat.S_ISREG(slot.lstat().st_mode):
        raise MoveError(f"captured source is not a regular note: {source}")
    with slot.open("rb+") as stream:
        actual = stream.read()
        os.fsync(stream.fileno())
    if actual != before or target.read_bytes() != after:
        raise MoveError(
            f"move image changed at the destructive handoff: {source} -> {target}",
        )
    for directory_to_sync in (
        directory, captures, captures.parent, source.parent, target.parent,
    ):
        sync_directory(directory_to_sync)


def restore_move(
    captures: Path, source: Path, target: Path, before: bytes, after: bytes,
) -> None:
    """Restore a moved source exclusively and retract its public target.

    Safe states are recognised: an identical source is left untouched, a
    private capture holding the expected image is restored with exclusive
    creation (again refusing a racing arrival), legacy receipts without a
    capture restore from the journal image, and the public target is captured
    privately and verified before it leaves the public namespace. Anything
    else raises :class:`MoveError` and keeps every file.
    """
    _require_owned_captures(captures)
    source_capture = find_source_capture(captures, source)
    if source_capture is not None and source_capture.is_symlink():
        raise MoveError(f"captured source became a link: {source}")
    if source_capture is not None and source_capture.read_bytes() != before:
        raise MoveError(f"captured source changed during recovery: {source}")
    if source.exists():
        if source.read_bytes() != before:
            raise MoveError(f"source changed during recovery: {source}")
    elif source_capture is None:
        # Legacy receipt without a private capture: the journal image is the
        # authoritative original, still published with exclusive creation.
        atomic_create_bytes(source, before)
    else:
        _restore_capture(source_capture, source)
    _capture_target(captures, target, after)


def _restore_capture(capture: Path, source: Path) -> None:
    """Restore a private capture to its public path without replacing arrivals."""
    atomic_create_bytes(source, capture.read_bytes(),
                        mode=stat.S_IMODE(capture.stat().st_mode))


def _capture_target(captures: Path, target: Path, after: bytes) -> None:
    """Detach the actual target inode, then verify it; never unlink an arrival."""
    _require_owned_captures(captures)
    if not target.exists():
        return
    existing = find_target_capture(captures, target)
    if existing is not None:
        raise MoveError(f"public archive reappeared after capture: {target}")
    captures.mkdir(parents=True, exist_ok=True)
    prefix = f"t-{target.stem[:24]}-{_capture_tag(captures, target)}-"
    directory = Path(tempfile.mkdtemp(dir=captures, prefix=prefix))
    slot = directory / "target.snapshot"
    _ = os.rename(target, slot)
    if not stat.S_ISREG(slot.lstat().st_mode):
        raise MoveError(f"captured archive is not a regular note: {target}")
    with slot.open("rb+") as stream:
        actual = stream.read()
        os.fsync(stream.fileno())
    if actual != after:
        raise MoveError(f"archive changed during recovery: {target}")
    for directory_to_sync in (
        directory, captures, captures.parent, target.parent,
    ):
        sync_directory(directory_to_sync)
