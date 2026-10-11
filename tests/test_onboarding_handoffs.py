"""Init previews explicit handoff enablement and apply keeps it reversible."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from birkin_mnemosyne import HandoffError, HandoffFields, HandoffScope, HandoffStore, MemoryIndex
from birkin_mnemosyne.memory_index import MemoryIndexError
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_plan import plan_init
from birkin_mnemosyne.review_journal import ReviewError

NOTE = b"---\ntitle: Policy\ntype: topic\ntags: []\n---\nPolicy body."


def tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def handoff_tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {path: image for path, image in tree(root).items()
            if path.startswith(".mnemosyne-handoffs/")}


def cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "birkin_mnemosyne.memory_index_cli", *args],
        cwd=cwd, capture_output=True, check=False,
    )


def test_empty_preview_reports_enablement_without_creating_anything(
    tmp_path: Path,
) -> None:
    # Given an absent vault under an absent parent.
    root = tmp_path / "new" / "vault"

    # When a preview requests handoff enablement.
    report = run_init(plan_init(root, enable_handoff=True))

    # Then the request/state is reported without creating the vault or state.
    assert report.mode == "preview"
    assert report.enable_handoff and not report.handoff_enabled
    assert report.mutations > 0
    assert not root.parent.exists()
    assert not HandoffStore(root).settings().enabled


def test_existing_vault_preview_changes_no_bytes_mtimes_or_directories(
    tmp_path: Path,
) -> None:
    # Given an initialized vault with an existing INDEX.
    _ = (tmp_path / "policy.md").write_bytes(NOTE)
    _ = MemoryIndex(tmp_path).enable()
    before = tree(tmp_path)
    before_directories = {path.relative_to(tmp_path).as_posix()
                          for path in tmp_path.rglob("*") if path.is_dir()}

    # When handoff enablement is previewed.
    report = run_init(plan_init(tmp_path, enable_handoff=True))

    # Then no file, mtime, directory or handoff state appears.
    assert report.enable_handoff and not report.handoff_enabled
    assert tree(tmp_path) == before
    assert {path.relative_to(tmp_path).as_posix()
            for path in tmp_path.rglob("*") if path.is_dir()} == before_directories
    assert not (tmp_path / ".mnemosyne-handoffs").exists()


def test_explicit_apply_enables_store_and_preserves_notes_and_routes(
    tmp_path: Path,
) -> None:
    # Given a normalized note with an existing INDEX route.
    note = tmp_path / "policy.md"
    _ = note.write_bytes(NOTE)
    index = MemoryIndex(tmp_path)
    original_entries = index.register("original route", "policy.md").entries
    original = note.read_bytes()

    # When handoff enablement is explicitly applied.
    report = run_init(plan_init(tmp_path, enable_handoff=True), apply=True)

    # Then all notes and routes survive and the store is really enabled.
    assert report.ok and report.verification == "passed"
    assert report.enable_handoff and report.handoff_enabled
    assert HandoffStore(tmp_path).settings().enabled
    assert note.read_bytes() == original
    assert all(entry in index.read().entries for entry in original_entries)


def test_repeated_enable_apply_is_byte_and_mtime_stable(tmp_path: Path) -> None:
    # Given an already enabled vault with a stable note and route set.
    _ = (tmp_path / "policy.md").write_bytes(NOTE)
    _ = MemoryIndex(tmp_path).register("original route", "policy.md")
    first = run_init(plan_init(tmp_path, enable_handoff=True), apply=True)
    assert first.ok and first.handoff_enabled
    image = tree(tmp_path)

    # When the freshly planned init is applied again.
    second = run_init(plan_init(tmp_path, enable_handoff=True), apply=True)

    # Then no spurious mutation occurs and every byte/mtime is stable.
    assert second.ok and second.handoff_enabled and second.mutations == 0
    assert tree(tmp_path) == image


def test_apply_preserves_index_budget_routes_and_handoff_budget(
    tmp_path: Path,
) -> None:
    # Given custom INDEX and handoff budgets with an existing route.
    _ = (tmp_path / "policy.md").write_bytes(b"Approval required.")
    index = MemoryIndex(tmp_path)
    _ = index.enable(max_tokens=4321)
    _ = index.register("approval", "policy.md")
    before_entries = index.read().entries
    handoffs = HandoffStore(tmp_path)
    _ = handoffs.enable(max_tokens=777)

    # When handoff enablement is applied again.
    report = run_init(plan_init(tmp_path, enable_handoff=True), apply=True)

    # Then both budgets and every route are retained additively.
    assert report.ok and report.handoff_enabled
    view = index.read()
    assert view.max_tokens == 4321
    assert all(entry in view.entries for entry in before_entries)
    assert handoffs.settings().max_tokens == 777


def test_managed_captures_are_never_rewritten_by_init(tmp_path: Path) -> None:
    # Given prior captures inside an enabled store.
    _ = (tmp_path / "policy.md").write_bytes(NOTE)
    store = HandoffStore(tmp_path)
    scope = HandoffScope("mn-070", "handoff")
    _ = store.capture(scope, HandoffFields("Keep all bytes."), capture_id="cp-1")
    _ = store.capture(scope, HandoffFields("Newer bytes."), capture_id="cp-2")
    before = handoff_tree(tmp_path)

    # When initialization applies handoff enablement.
    report = run_init(plan_init(tmp_path, enable_handoff=True), apply=True)

    # Then managed records are hidden from inventory and never rewritten.
    assert report.ok and report.handoff_enabled
    assert handoff_tree(tmp_path) == before
    assert [note.record.capture_id for note in store.records(scope)] == ["cp-1", "cp-2"]


def test_malformed_handoff_config_blocks_plan_without_mutation(
    tmp_path: Path,
) -> None:
    # Given a corrupt managed config file.
    _ = (tmp_path / "policy.md").write_bytes(b"# Policy\nApproval required.")
    directory = tmp_path / ".mnemosyne-handoffs"
    directory.mkdir()
    corrupt = directory / "config.json"
    _ = corrupt.write_bytes(b"{not-json")
    before = tree(tmp_path)

    # When enablement is planned against it.
    with pytest.raises(ValueError):
        _ = plan_init(tmp_path, enable_handoff=True)

    # Then the corrupt bytes are untouched.
    assert tree(tmp_path) == before and corrupt.read_bytes() == b"{not-json"


def test_symlinked_handoff_config_is_refused_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a config resolved through a linked path.
    config = tmp_path / ".mnemosyne-handoffs" / "config.json"
    config.parent.mkdir()
    _ = config.write_bytes(b"{}")
    original = Path.is_symlink

    def linked(path: Path) -> bool:
        return path == config or original(path)

    monkeypatch.setattr(Path, "is_symlink", linked)
    before = tree(tmp_path)

    # When enablement is planned against the unsafe path.
    with pytest.raises(HandoffError):
        _ = plan_init(tmp_path, enable_handoff=True)

    # Then nothing is read, written or created.
    assert tree(tmp_path) == before and config.read_bytes() == b"{}"


@pytest.mark.parametrize("value", [1, "yes", None])
def test_non_boolean_enable_handoff_is_refused(
    tmp_path: Path, value: Any,
) -> None:
    # Given a vault and a non-boolean enablement request.
    _ = (tmp_path / "policy.md").write_bytes(b"Approval required.")

    # When plan_init receives the invalid flag.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(tmp_path, enable_handoff=value)

    # Then no plan or file change is produced.
    assert not (tmp_path / ".mnemosyne-handoffs").exists()
    assert (tmp_path / "policy.md").read_bytes() == b"Approval required."


def test_changed_handoff_settings_after_preview_refuse_apply_without_overwrite(
    tmp_path: Path,
) -> None:
    # Given an enabled store with a stable INDEX envelope.
    _ = MemoryIndex(tmp_path).enable()
    _ = (tmp_path / "policy.md").write_bytes(NOTE)
    plan = plan_init(tmp_path, enable_handoff=True)
    config = tmp_path / ".mnemosyne-handoffs" / "config.json"
    owner = {"version": 1, "enabled": True, "max_tokens": 321}
    config.parent.mkdir()
    _ = config.write_text(json.dumps(owner), encoding="utf-8")
    before = tree(tmp_path)

    # When an owner edits the handoff budget between preview and apply.
    with pytest.raises(ReviewError):
        _ = run_init(plan, apply=True)

    # Then the changed settings are never overwritten or mutated around.
    assert json.loads(config.read_text(encoding="utf-8")) == owner
    assert tree(tmp_path) == before


def test_cli_enable_handoff_preview_is_read_only_and_apply_enables(
    tmp_path: Path,
) -> None:
    # Given an existing note with a registered INDEX route.
    vault = tmp_path / "vault"
    note = vault / "policy.md"
    note.parent.mkdir(parents=True)
    _ = note.write_bytes(NOTE)
    index = MemoryIndex(vault)
    original_entries = index.register("original route", "policy.md").entries
    original = note.read_bytes()

    # When the public CLI previews enablement.
    preview = cli("--vault", str(vault), "init", "--enable-handoff", cwd=tmp_path)
    assert preview.returncode == 0, preview.stderr
    payload = json.loads(preview.stdout.decode("utf-8"))
    assert payload["enable_handoff"] is True
    assert payload["handoff_enabled"] is False
    assert payload["mutations"] > 0
    assert note.read_bytes() == original
    assert not HandoffStore(vault).settings().enabled

    # When the public CLI explicitly applies enablement.
    applied = cli("--vault", str(vault), "init", "--enable-handoff", "--apply",
                  cwd=tmp_path)
    assert applied.returncode == 0, applied.stderr
    payload = json.loads(applied.stdout.decode("utf-8"))
    assert payload["ok"] is True and payload["handoff_enabled"] is True
    assert HandoffStore(vault).settings().enabled
    assert note.read_bytes() == original
    assert all(entry in index.read().entries for entry in original_entries)
    committed = tree(vault)

    # When the same apply is repeated, bytes and mtimes stay stable.
    repeated = cli("--vault", str(vault), "init", "--enable-handoff", "--apply",
                   cwd=tmp_path)
    assert repeated.returncode == 0, repeated.stderr
    payload = json.loads(repeated.stdout.decode("utf-8"))
    assert payload["ok"] is True and payload["mutations"] == 0
    assert tree(vault) == committed