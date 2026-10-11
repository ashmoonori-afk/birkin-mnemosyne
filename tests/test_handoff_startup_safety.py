"""A scoped handoff never substitutes for a lost required INDEX."""

import shutil
from pathlib import Path
from typing import Literal

import pytest

from birkin_mnemosyne.handoff_records import HandoffFields, HandoffScope
from birkin_mnemosyne.handoffs import HandoffStore
from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.startup import StartupError, StartupReader


@pytest.mark.parametrize("lifetime", ["before-capture", "seen-index", "after-loss"])
def test_handoff_requires_index_even_when_reader_has_not_seen_it(
    tmp_path: Path, lifetime: Literal["before-capture", "seen-index", "after-loss"],
) -> None:
    _ = (tmp_path / "identity.md").write_text("# Identity\nKeep the original rules.\n", encoding="utf-8")
    reader = StartupReader(tmp_path)
    _ = HandoffStore(tmp_path).capture(
        HandoffScope("project"), HandoffFields("unfinished work"), capture_id="one",
    )
    if lifetime == "seen-index":
        _ = reader.read(["identity.md"], project_key="project")
    shutil.rmtree(MemoryIndex(tmp_path).directory)
    if lifetime == "after-loss":
        reader = StartupReader(tmp_path)
    with pytest.raises((MemoryIndexError, StartupError)):
        _ = reader.read(["identity.md"], project_key="project")
