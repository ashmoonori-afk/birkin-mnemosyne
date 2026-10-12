"""Journaled label preview/apply/undo: read-only plans, checked apply, ownership."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from birkin_mnemosyne.consolidation import Consolidation
from birkin_mnemosyne.labeling import plan_labels, run_labeling
from birkin_mnemosyne.labels import read_labels
from birkin_mnemosyne.memory_index import JsonValue, MemoryIndex
from birkin_mnemosyne.onboarding_notes import Note, catalogue
from birkin_mnemosyne.review_journal import ReviewError

BOM = b"\xef\xbb\xbf"
decode_json: Callable[[str], JsonValue] = json.loads


def write(root: Path, relative: str, raw: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_bytes(raw)


def alpha_raw() -> bytes:
    return (
        b"---\n"
        b"title: Alpha Project\n"
        b"type: project\n"
        b"project: phoenix\n"
        b"---\n"
        b"[[project:acme]] released 2026-10-11.\n"
    )


def manual_raw() -> bytes:
    return b'---\nlabels: ["manual:keep"]\n---\nManual body.\n'


def empty_raw() -> bytes:
    return b"---\nlabels: []\n---\nEmpty body.\n"


def gamma_raw() -> bytes:
    return "---\ntitle: Gamma\n---\n한국어 규칙\n".encode()


def seed_vault(root: Path) -> None:
    write(root, "notes/alpha.md", alpha_raw())
    write(root, "notes/beta.md", manual_raw())
    write(root, "deep/gamma.md", gamma_raw())
    _ = MemoryIndex(root).register("ideas", "notes/alpha.md")
    _ = MemoryIndex(root).register("deploy", "deep/gamma.md")


def md_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.md")
    }


def tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file() and path.name != ".mnemosyne-mcp.lock"
    }


def dirs(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_dir()
        )
    )


ALPHA_LABELS = (
    "date:2026-10-11",
    "project:Alpha Project",
    "project:acme",
    "project:phoenix",
    "topic:ideas",
    "type:project",
    "zone:notes",
)
GAMMA_LABELS = ("lang:ko", "topic:deploy", "zone:deep")


def test_preview_is_deterministic_and_read_only(tmp_path: Path) -> None:
    # Given a seeded vault with routes and no prior label artifacts.
    root = tmp_path / "vault"
    seed_vault(root)
    before, before_dirs = tree(root), dirs(root)
    lock_present = (root / ".mnemosyne-mcp.lock").exists()

    # When previewed twice.
    first = plan_labels(root)
    second = plan_labels(root)

    # Then the plan and report are byte-identical and nothing was written.
    assert first == second
    assert run_labeling(first) == run_labeling(second)
    assert tree(root) == before and dirs(root) == before_dirs
    assert (root / ".mnemosyne-mcp.lock").exists() == lock_present
    assert not (root / ".mnemosyne-reviews").exists()
    assert not (root / ".mnemosyne-index.json.z").exists()
    assert not (root / ".mnemosyne-dynamics.json").exists()

    # And the plan carries exact images, INDEX routing and planned edits.
    assert first.labels is None and first.paths is None
    assert tuple(note.path for note in first.notes) == (
        "deep/gamma.md",
        "notes/alpha.md",
        "notes/beta.md",
    )
    by_path = {note.path: note for note in first.notes}
    alpha = by_path["notes/alpha.md"]
    assert alpha.raw == alpha_raw() and alpha.index_topics == ("ideas",)
    assert read_labels(alpha.edit.raw) == ALPHA_LABELS
    assert by_path["notes/beta.md"].edit.raw == manual_raw()
    assert by_path["deep/gamma.md"].index_topics == ("deploy",)
    assert read_labels(by_path["deep/gamma.md"].edit.raw) == GAMMA_LABELS

    # And the report names preview mode with concrete counts.
    report = run_labeling(first)
    assert report.mode == "preview" and report.ok
    assert report.notes == 3 and report.changed == 2
    assert report.warnings == ()
    assert report.undo_transaction is None
    assert report.label_counts == (
        ("date:2026-10-11", 1),
        ("lang:ko", 1),
        ("manual:keep", 1),
        ("project:Alpha Project", 1),
        ("project:acme", 1),
        ("project:phoenix", 1),
        ("topic:deploy", 1),
        ("topic:ideas", 1),
        ("type:project", 1),
        ("zone:deep", 1),
        ("zone:notes", 1),
    )


def test_preview_on_absent_vault_creates_nothing(tmp_path: Path) -> None:
    # Given an absent vault under an absent parent.
    root = tmp_path / "missing" / "vault"

    # When the read-only preview is requested.
    plan = plan_labels(root)
    report = run_labeling(plan)

    # Then nothing is created anywhere.
    assert plan.notes == () and plan.warnings == ()
    assert report.ok and report.notes == report.changed == 0
    assert report.undo_transaction is None
    assert not root.parent.exists()


def test_apply_journals_only_changes_and_undo_restores_exact_bytes(
    tmp_path: Path,
) -> None:
    # Given a seeded vault with one manual owner.
    root = tmp_path / "vault"
    seed_vault(root)
    before = md_bytes(root)
    plan = plan_labels(root)

    # When the plan is applied.
    report = run_labeling(plan, apply=True)

    # Then only the two annotated notes changed and one journal was written.
    assert report.mode == "applied" and report.ok
    assert report.changed == 2 and report.undo_transaction is not None
    assert (root / "notes/beta.md").read_bytes() == manual_raw()
    assert read_labels((root / "notes/alpha.md").read_bytes()) == ALPHA_LABELS
    assert read_labels((root / "deep/gamma.md").read_bytes()) == GAMMA_LABELS
    journals = sorted((root / ".mnemosyne-reviews").glob("*.json"))
    assert len(journals) == 1
    manifest = decode_json(journals[0].read_text("utf-8"))
    assert isinstance(manifest, dict)
    assert manifest["state"] == "committed"
    assert manifest["choice"] == "mnemosyne-label"
    question = manifest["question_id"]
    assert isinstance(question, str) and question.startswith("label:")
    changes = manifest["changes"]
    assert isinstance(changes, list) and len(changes) == 2
    sources: set[str] = set()
    for change in changes:
        assert isinstance(change, dict)
        source = change["source"]
        assert isinstance(source, str)
        assert source == change["target"]
        sources.add(source)
    assert sources == {
        "deep/gamma.md",
        "notes/alpha.md",
    }

    # When the transaction is undone through the existing Consolidation seam.
    undo = Consolidation(root).undo(report.undo_transaction)

    # Then the exact original bytes return and a fresh plan is identical.
    assert undo.state == "undone"
    assert md_bytes(root) == before
    assert plan_labels(root) == plan


def test_undo_refuses_user_edit_without_partial_restore(tmp_path: Path) -> None:
    # Given an applied transaction on two notes.
    root = tmp_path / "vault"
    seed_vault(root)
    report = run_labeling(plan_labels(root), apply=True)
    assert report.undo_transaction is not None
    _ = (root / "notes/alpha.md").write_bytes(
        b"---\ntitle: Alpha\n---\nUser rewrite after apply.\n"
    )
    after_edit = md_bytes(root)

    # When undo is attempted on the drifted post-image.
    with pytest.raises(ReviewError, match="post-image"):
        _ = Consolidation(root).undo(report.undo_transaction)

    # Then nothing was partially restored and the other note stays labeled.
    assert md_bytes(root) == after_edit
    assert read_labels((root / "deep/gamma.md").read_bytes()) == GAMMA_LABELS


def test_manual_and_empty_labels_survive_without_replacement(tmp_path: Path) -> None:
    # Given manual, explicitly empty and absent label fields.
    root = tmp_path / "vault"
    write(root, "notes/beta.md", manual_raw())
    write(root, "notes/delta.md", empty_raw())
    write(root, "notes/alpha.md", alpha_raw())

    # When annotation runs without an explicit replacement.
    plan = plan_labels(root)
    by_path = {note.path: note for note in plan.notes}
    report = run_labeling(plan, apply=True)

    # Then manual and empty ownership stay byte-identical; only alpha changed.
    assert by_path["notes/beta.md"].edit.raw == manual_raw()
    assert by_path["notes/delta.md"].edit.raw == empty_raw()
    assert report.changed == 1 and report.undo_transaction is not None
    assert (root / "notes/beta.md").read_bytes() == manual_raw()
    assert (root / "notes/delta.md").read_bytes() == empty_raw()
    assert read_labels((root / "notes/alpha.md").read_bytes()) is not None


def test_explicit_replacement_overwrites_all_and_preserves_other_bytes(
    tmp_path: Path,
) -> None:
    # Given a BOM/CRLF/comment note with manual labels and a plain note.
    root = tmp_path / "vault"
    fragile = BOM + (
        b"---\r\n"
        b"# keep this comment\r\n"
        b'labels: ["manual:old"]\r\n'
        b"title: Fragile\r\n"
        b"---\r\n"
        b"Body \r\nwith CRLF.\r\n"
    )
    write(root, "raw/fragile.md", fragile)
    write(root, "plain.md", b"---\ntitle: T\n---\nBody.\n")

    # When an explicit replacement contracts the labels field.
    plan = plan_labels(root, labels=("Topic:New",))
    assert plan.labels == ("topic:New",)
    by_path = {note.path: note for note in plan.notes}
    expected = BOM + (
        b"---\r\n"
        b"# keep this comment\r\n"
        b'labels: ["topic:New"]\r\n'
        b"title: Fragile\r\n"
        b"---\r\n"
        b"Body \r\nwith CRLF.\r\n"
    )
    assert by_path["raw/fragile.md"].edit.raw == expected
    assert by_path["plain.md"].edit.raw == (
        b'---\ntitle: T\nlabels: ["topic:New"]\n---\nBody.\n'
    )

    # And an explicit empty list clears every selected note.
    cleared = plan_labels(root, labels=())
    assert cleared.labels == ()
    assert all(
        read_labels(note.edit.raw) == ()
        for note in (cleared.notes[0], cleared.notes[1])
    )


def test_noop_apply_writes_nothing(tmp_path: Path) -> None:
    # Given notes whose manual labels leave nothing to annotate.
    root = tmp_path / "vault"
    write(root, "notes/beta.md", manual_raw())
    write(root, "notes/delta.md", empty_raw())
    before = tree(root)
    plan = plan_labels(root)
    assert all(note.edit.raw == note.raw for note in plan.notes)

    # When the no-op plan is applied.
    report = run_labeling(plan, apply=True)

    # Then no bytes, mtimes, journal, lock or cache appear.
    assert report.ok and report.changed == 0 and report.undo_transaction is None
    assert tree(root) == before
    assert not (root / ".mnemosyne-reviews").exists()
    assert not (root / ".mnemosyne-mcp.lock").exists()
    assert not (root / ".mnemosyne-index.json.z").exists()


def test_apply_refuses_edited_source_without_writes(tmp_path: Path) -> None:
    # Given a captured plan and a note edited afterwards.
    root = tmp_path / "vault"
    seed_vault(root)
    plan = plan_labels(root)
    _ = (root / "notes/alpha.md").write_bytes(
        b"---\ntitle: Alpha\n---\nChanged after preview.\n"
    )
    before = tree(root)

    # When the stale plan is applied.
    with pytest.raises(ReviewError, match="label input changed"):
        _ = run_labeling(plan, apply=True)

    # Then nothing else changed and no journal was written.
    assert tree(root) == before
    assert not (root / ".mnemosyne-reviews").exists()
    assert read_labels((root / "deep/gamma.md").read_bytes()) is None


def test_apply_refuses_routing_change(tmp_path: Path) -> None:
    # Given a captured plan and a changed INDEX route afterwards.
    root = tmp_path / "vault"
    seed_vault(root)
    plan = plan_labels(root)
    _ = MemoryIndex(root).register("extra", "notes/alpha.md")
    before = tree(root)

    # When the stale plan is applied.
    with pytest.raises(ReviewError, match="routing state changed"):
        _ = run_labeling(plan, apply=True)

    # Then no note or journal changed.
    assert tree(root) == before
    assert not (root / ".mnemosyne-reviews").exists()


def test_apply_refuses_new_note_for_whole_vault_selection(tmp_path: Path) -> None:
    # Given a whole-vault plan and a note arriving afterwards.
    root = tmp_path / "vault"
    seed_vault(root)
    plan = plan_labels(root)
    write(root, "notes/new.md", b"---\ntitle: New\n---\nFresh note.\n")
    before = tree(root)

    # When the stale plan is applied.
    with pytest.raises(ReviewError, match="label selection changed"):
        _ = run_labeling(plan, apply=True)

    # Then nothing was applied or journaled.
    assert tree(root) == before
    assert not (root / ".mnemosyne-reviews").exists()


def test_paths_restrict_selection_and_warn_for_missing(tmp_path: Path) -> None:
    # Given a seeded vault and a requested subset with one absent path.
    root = tmp_path / "vault"
    seed_vault(root)
    plan = plan_labels(root, paths=("notes/alpha.md", "nogo.md"))

    # Then only the existing requested note is selected, with a warning.
    assert plan.paths == ("notes/alpha.md", "nogo.md")
    assert tuple(note.path for note in plan.notes) == ("notes/alpha.md",)
    assert any("nogo.md" in warning for warning in plan.warnings)

    # When applied, only the selected note changes.
    report = run_labeling(plan, apply=True)
    assert report.changed == 1 and report.undo_transaction is not None
    assert read_labels((root / "notes/alpha.md").read_bytes()) == ALPHA_LABELS
    assert read_labels((root / "deep/gamma.md").read_bytes()) is None


def test_apply_refuses_selection_appearing_at_requested_path(tmp_path: Path) -> None:
    # Given a plan whose requested path was absent but another change is due.
    root = tmp_path / "vault"
    seed_vault(root)
    plan = plan_labels(root, paths=("notes/alpha.md", "nogo.md"))
    assert tuple(note.path for note in plan.notes) == ("notes/alpha.md",)
    assert any("nogo.md" in warning for warning in plan.warnings)

    # When the path becomes an eligible note before apply.
    write(root, "nogo.md", b"---\ntitle: Nogo\n---\nArrived late.\n")
    with pytest.raises(ReviewError, match="label selection changed"):
        _ = run_labeling(plan, apply=True)
    assert not (root / ".mnemosyne-reviews").exists()
    assert read_labels((root / "notes/alpha.md").read_bytes()) is None


def test_generated_catalogues_and_hidden_state_are_excluded(tmp_path: Path) -> None:
    # Given a generated catalogue and hidden managed/split documents.
    root = tmp_path / "vault"
    seed_vault(root)
    member = Note(
        "notes/alpha.md", alpha_raw(), alpha_raw(), "Alpha Project", "ideas", (), None
    )
    generated = catalogue("ideas", (member,))
    write(root, generated.path, generated.raw)
    write(
        root,
        ".mnemosyne-handoffs/immutable.md",
        b"---\ntitle: Handoff\n---\nManaged.\n",
    )
    write(
        root, ".mnemosyne-memory-index/split.md", b"---\ntitle: Split\n---\nReceipt.\n"
    )

    # Then none of them enter the selection.
    plan = plan_labels(root)
    assert {note.path for note in plan.notes} == {
        "deep/gamma.md",
        "notes/alpha.md",
        "notes/beta.md",
    }


def test_invalid_labels_metadata_is_retained_with_warning(tmp_path: Path) -> None:
    # Given a note whose labels metadata cannot resolve.
    root = tmp_path / "vault"
    bad = b"---\nlabels: [123]\n---\nBody.\n"
    write(root, "bad.md", bad)

    # Then planning retains it unchanged and reports the warning.
    plan = plan_labels(root)
    by_path = {note.path: note for note in plan.notes}
    assert len(plan.warnings) == 1 and "bad.md" in plan.warnings[0]
    assert by_path["bad.md"].edit.raw == bad
    report = run_labeling(plan, apply=True)
    assert report.ok and report.changed == 0 and report.undo_transaction is None
    assert (root / "bad.md").read_bytes() == bad


def test_label_histogram_counts_notes_not_duplicate_spellings(tmp_path: Path) -> None:
    raw = b'---\nlabels: ["Project:Alpha", "project:Alpha", "project:Alpha"]\n---\nbody'
    write(tmp_path, "one.md", raw)
    write(tmp_path, "two.md", b'---\nlabels: ["project:Alpha"]\n---\nbody')
    report = run_labeling(plan_labels(tmp_path))
    assert report.label_counts == (("project:Alpha", 2),)
    assert (tmp_path / "one.md").read_bytes() == raw
