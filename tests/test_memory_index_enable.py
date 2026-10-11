"""An empty vault can opt in without inventing or dropping a document."""

import os
from pathlib import Path

import pytest

from birkin_mnemosyne import MemoryIndex, MemoryIndexError, StartupReader

PathStr = str | bytes | os.PathLike[str] | os.PathLike[bytes]


def test_empty_enable_supports_independent_startup_verification(tmp_path: Path) -> None:
    # Given a vault directory that does not yet exist.
    root = tmp_path / "new" / "vault"
    index = MemoryIndex(root)

    # When the owner explicitly enables its INDEX.
    view = index.enable()

    # Then zero routes form a complete, independently verifiable startup.
    assert view.enabled and view.entries == ()
    reader = StartupReader(root, require_index=True)
    bundle = reader.read([])
    assert reader.verify(bundle.context, []).complete
    assert bundle.coverage.warnings == ()


def test_enable_rerun_preserves_existing_routes_budget_and_bytes(tmp_path: Path) -> None:
    # Given an already enabled vault with a custom budget and route.
    note = tmp_path / "policy.md"
    note.write_bytes(b"Keep every approval.\r\n")
    index = MemoryIndex(tmp_path)
    previous = index.register("approval", note.name, max_tokens=17)
    before = index.path.read_bytes()

    # When initialization enables it again without a budget override.
    current = index.enable()

    # Then its durable routing snapshot remains byte-identical.
    assert current == previous
    assert index.path.read_bytes() == before
    assert note.read_bytes() == b"Keep every approval.\r\n"


def test_explicit_enable_budget_change_retains_every_route(tmp_path: Path) -> None:
    # Given an enabled route at its original budget.
    (tmp_path / "policy.md").write_bytes(b"Keep every approval.")
    index = MemoryIndex(tmp_path)
    previous = index.register("approval", "policy.md")

    # When the owner explicitly supplies a smaller budget.
    current = index.enable(max_tokens=1)

    # Then the route is retained and the limit is reported as a warning.
    assert current.entries == previous.entries
    assert current.max_tokens == 1 and current.over_budget
    assert current.warnings


@pytest.mark.parametrize("budget", [0, -1, True])
def test_invalid_enable_budget_changes_no_files(tmp_path: Path, budget: int) -> None:
    # Given an empty vault.
    index = MemoryIndex(tmp_path)

    # When an invalid budget crosses the API boundary.
    with pytest.raises(MemoryIndexError):
        index.enable(max_tokens=budget)

    # Then even a lock file or opt-in marker was not created.
    assert list(tmp_path.iterdir()) == []


def test_failed_first_creation_leaves_no_enabled_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a vault that has never opted in and a failing first publication.
    index = MemoryIndex(tmp_path / "vault")

    def fail_replace(_src: PathStr, _dst: PathStr) -> None:
        raise OSError("injected failure during first index.json creation")

    monkeypatch.setattr(os, "replace", fail_replace)

    # When the very first enable fails while creating index.json.
    with pytest.raises(OSError):
        index.enable()

    # Then no opt-in marker is left behind and the vault still reads as absent.
    assert not index.directory.exists()
    assert index.read().enabled is False


def test_enable_retry_after_failed_first_creation_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a first publication that fails once and then works normally.
    root = tmp_path / "vault"
    index = MemoryIndex(root)
    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src: PathStr, dst: PathStr) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("injected failure during first index.json creation")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    with pytest.raises(OSError):
        index.enable()
    assert not index.directory.exists()

    # When enable is retried after the transient failure.
    view = index.enable()

    # Then a complete, enabled zero-route INDEX exists with no staged leftovers.
    assert view.enabled and view.entries == ()
    assert index.path.is_file()
    assert [p.name for p in root.iterdir() if p.name.startswith(index.directory.name + ".")] == []


def test_enable_never_resets_invalid_existing_marker(tmp_path: Path) -> None:
    # Given an existing opt-in marker whose index.json is corrupt.
    index = MemoryIndex(tmp_path)
    index.directory.mkdir()
    index.path.write_bytes(b"{not valid json")

    # When enable runs against the corrupt marker.
    with pytest.raises(MemoryIndexError):
        index.enable()

    # Then it fails closed without resetting or rewriting the marker.
    assert index.path.read_bytes() == b"{not valid json"
