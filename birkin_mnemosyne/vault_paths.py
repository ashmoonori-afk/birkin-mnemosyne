"""Shared discovery policy for human-organized nested memory folders."""

from pathlib import PurePosixPath
from typing import Final

CACHE_DIRECTORIES: Final = frozenset({"node_modules", "__pycache__"})


def hidden_or_cache(name: str) -> bool:
    """Exclude hidden components and known dependency/runtime caches."""
    return name.startswith(".") or name.casefold() in CACHE_DIRECTORIES


def archived_zone(zone: str) -> bool:
    """Recognize archived descendants as well as the archive root."""
    return any(part.casefold() == "_archive" for part in PurePosixPath(zone).parts)
