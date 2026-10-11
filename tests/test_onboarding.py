"""First-run plans and explicit application use real files and recovery."""

from dataclasses import asdict
from pathlib import Path

import pytest

from birkin_mnemosyne.memory_index import MemoryIndex
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_plan import plan_init
from birkin_mnemosyne.review_journal import undo_receipt


def tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def messy(root: Path) -> dict[str, bytes]:
    sources = {
        "first.md": b"Review every release before publishing.",
        "second.md": b"Review every release before publishing.",
        "deep/a/policy.md": "한국어 규칙\r\n마지막 줄".encode(),
        "deep/b/policy.md": "日本語のメモ\n最後の行".encode(),
    }
    for relative, raw in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(raw)
    return sources


def test_empty_preview_creates_neither_vault_nor_parent(tmp_path: Path) -> None:
    # Given an absent vault under an absent parent.
    root = tmp_path / "new" / "vault"

    # When the default preview is requested.
    report = run_init(plan_init(root))

    # Then verification is only planned and no directory was created.
    assert report.mode == "preview" and report.verification == "planned"
    assert report.notes == report.topics == 0
    assert not root.parent.exists()


def test_empty_apply_enables_verified_resident_index(tmp_path: Path) -> None:
    # Given an absent vault.
    root = tmp_path / "vault"

    # When the owner explicitly applies initialization.
    report = run_init(plan_init(root), apply=True)

    # Then zero-route startup is actually verified.
    assert report.ok and report.verification == "passed"
    assert report.verification_scope == "resident-index"
    assert MemoryIndex(root).read().enabled
    assert report.notes == report.topics == 0


def test_messy_preview_changes_no_files_or_mtimes(tmp_path: Path) -> None:
    # Given unnormalized multilingual notes and duplicate candidates.
    _ = messy(tmp_path)
    before = tree(tmp_path)
    before_directories = tuple(sorted(path.relative_to(tmp_path).as_posix()
                                      for path in tmp_path.rglob("*") if path.is_dir()))

    # When the default plan/report is generated.
    report = run_init(plan_init(tmp_path))

    # Then all path identities survive and no bytes/mtimes change.
    assert report.notes == 4 and tree(tmp_path) == before
    assert tuple(sorted(path.relative_to(tmp_path).as_posix()
                        for path in tmp_path.rglob("*") if path.is_dir())) == before_directories
    assert {item.path for item in report.sources} == {
        "first.md", "second.md", "deep/a/policy.md", "deep/b/policy.md",
    }
    assert any(item.reason == "duplicate" for item in report.review_questions)
    assert asdict(report)["verification"] == "planned"


def test_apply_preserves_information_and_exposes_byte_exact_undo(tmp_path: Path) -> None:
    # Given original byte images and an existing alias.
    originals = messy(tmp_path)
    _ = MemoryIndex(tmp_path).register("old alias", "first.md")

    # When initialization is explicitly applied.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then sources are retained, indexed, and recoverable through the existing journal.
    assert report.ok and report.undo_transaction is not None
    for relative, raw in originals.items():
        assert (tmp_path / relative).read_bytes().endswith(raw)
    routes = MemoryIndex(tmp_path).read().entries
    assert any(route.trigger == "old alias" and route.document == "first.md" for route in routes)
    assert set(originals).issubset({route.document for route in routes})
    _ = undo_receipt(tmp_path, report.undo_transaction)
    assert {relative: (tmp_path / relative).read_bytes() for relative in originals} == originals
    assert MemoryIndex(tmp_path).read().entries == routes
    assert all((tmp_path / relative).exists() for relative in report.topic_documents)


def test_successful_rerun_changes_zero_file_bytes_or_mtimes(tmp_path: Path) -> None:
    # Given an already initialized messy vault.
    _ = messy(tmp_path)
    first = run_init(plan_init(tmp_path), apply=True)
    before = tree(tmp_path)

    # When initialization is applied again.
    second = run_init(plan_init(tmp_path), apply=True)

    # Then it creates no artifacts, routes, cache updates or journal.
    assert second.ok and second.mutations == 0 and second.journal is None
    assert second.topic_documents == first.topic_documents
    assert tree(tmp_path) == before


def test_import_preview_preserves_both_complete_input_trees(tmp_path: Path) -> None:
    # Given an external Markdown tree and a separate existing vault.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    root.mkdir()
    _ = messy(external)
    before_external, before_root = tree(external), tree(root)
    before_directories = tuple(sorted(path.relative_to(tmp_path).as_posix()
                                      for path in tmp_path.rglob("*") if path.is_dir()))

    # When import is previewed.
    report = run_init(plan_init(root, import_dir=external))

    # Then no source or destination file is created or modified.
    assert report.imports == report.notes == 4
    assert tree(external) == before_external and tree(root) == before_root
    assert tuple(sorted(path.relative_to(tmp_path).as_posix()
                        for path in tmp_path.rglob("*") if path.is_dir())) == before_directories


def test_spaced_header_key_rerun_preserves_catalogue_and_bytes(tmp_path: Path) -> None:
    # Given a vault initialized from an equivalent plain-key form.
    source = tmp_path / "policy.md"
    _ = source.write_bytes(b"---\ntitle : Owner title\n---\nOwner body.")
    first = run_init(plan_init(tmp_path), apply=True)
    before = tree(tmp_path)

    # When the unchanged vault is initialized again.
    second = run_init(plan_init(tmp_path), apply=True)

    # Then no new catalogue, route or source mutation appears.
    assert second.ok and second.mutations == 0 and second.journal is None
    assert second.topic_documents == first.topic_documents
    assert tree(tmp_path) == before


def test_import_apply_then_rerun_without_import_is_idempotent(tmp_path: Path) -> None:
    # Given imported notes that have already been initialized.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = messy(external)
    before_external = tree(external)
    first = run_init(plan_init(root, import_dir=external), apply=True)
    before_root = tree(root)

    # When initialization runs without repeating the import option.
    second = run_init(plan_init(root), apply=True)

    # Then logical topics and outputs remain stable while external bytes are untouched.
    assert second.ok and second.mutations == 0
    assert second.topic_documents == first.topic_documents
    assert tree(root) == before_root and tree(external) == before_external


def test_stale_source_plan_refuses_owner_edits_without_overwrite(tmp_path: Path) -> None:
    # Given a plan followed by an owner edit.
    _ = messy(tmp_path)
    plan = plan_init(tmp_path)
    owner = b"New owner rule."
    _ = (tmp_path / "first.md").write_bytes(owner)

    # When the stale plan is applied.
    with pytest.raises(ValueError):
        _ = run_init(plan, apply=True)

    # Then the owner edit survives and INDEX was not enabled.
    assert (tmp_path / "first.md").read_bytes() == owner
    assert not MemoryIndex(tmp_path).read().enabled
