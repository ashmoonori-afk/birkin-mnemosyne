"""Shared discovery policy for human-organized nested memory folders."""

import stat
from pathlib import Path, PurePosixPath
from typing import Final

CACHE_DIRECTORIES: Final = frozenset({"node_modules", "__pycache__"})


def hidden_or_cache(name: str) -> bool:
    """Exclude hidden components and known dependency/runtime caches."""
    return name.startswith(".") or name.casefold() in CACHE_DIRECTORIES


def archived_zone(zone: str) -> bool:
    """Recognize archived descendants as well as the archive root."""
    return any(part.casefold() == "_archive" for part in PurePosixPath(zone).parts)


def checked_note_path(vault: Path, relative: str) -> Path:
    """Keep note mutations inside the selected vault without following links."""
    path = vault / relative
    if not path.resolve().is_relative_to(vault.resolve()):
        raise ValueError(f"unsafe note path: {relative!r}")
    for component in (path, *path.parents):
        if component == vault:
            break
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError(f"unsafe linked note path: {relative!r}")
    return path
