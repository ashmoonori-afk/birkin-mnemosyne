"""Canonical vault discovery and newest-slug selection in native scan order."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

Fingerprint = tuple[str, int, int, int]


def allowed_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and not PurePosixPath(path).is_absolute() and \
        not PureWindowsPath(path).drive and \
        not any(p in {".", ".."} or p.startswith(".") for p in parts) and \
        parts[0].casefold() not in {"system", "_archive"} and \
        "\\" not in path and not re.search(r"[\x00-\x1f\ud800-\udfff\ufffe\uffff]", path)


def scan_paths(vault: Path) -> list[Fingerprint]:
    """Discover allowed note paths without sorting the native discovery order."""
    fingerprints: list[Fingerprint] = []

    def discover(directory: Path) -> None:
        """Preserve core discovery order, including pre-boost candidate ties."""
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(vault).as_posix()
                if not allowed_path(relative):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    discover(path)
                elif entry.name.endswith(".md") and entry.is_file() and \
                        path.resolve().is_relative_to(vault):
                    stat = entry.stat()
                    fingerprints.append((relative, stat.st_mtime_ns,
                                         stat.st_ctime_ns, stat.st_size))
    discover(vault)
    return fingerprints


def deep_winners(fingerprints: list[Fingerprint]) -> list[str]:
    """Forward only newest deep copies; shallow winners retain equal-time ties."""
    winners: dict[str, tuple[str, float]] = {}
    for relative, mtime_ns, _, _ in fingerprints:
        path = PurePosixPath(relative)
        previous_winner = winners.get(path.stem)
        mtime = mtime_ns / 1_000_000_000
        if previous_winner is None or mtime > previous_winner[1] or (
            mtime == previous_winner[1] and len(path.parts) <= 2
            and len(PurePosixPath(previous_winner[0]).parts) > 2
        ):
            winners[path.stem] = (relative, mtime)
    return [relative for relative, _, _, _ in fingerprints
            if len(PurePosixPath(relative).parts) > 2
            and winners[PurePosixPath(relative).stem][0] == relative]
