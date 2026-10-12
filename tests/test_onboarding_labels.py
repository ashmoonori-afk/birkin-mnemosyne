"""Init labels notes in one journal, counts them and groups topics opt-in."""

from pathlib import Path

import pytest

from birkin_mnemosyne import frontmatter
from birkin_mnemosyne.memory_index import MemoryIndexError
from birkin_mnemosyne.memory_index_migration import split_note
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_plan import plan_init
from birkin_mnemosyne.review_journal import undo_receipt

META = (
    "---\ntitle: Launch plan\ntype: project\nproject: MyApp\npeople: [Kim, Lee]\n"
    "created: 2026-10-11\nlanguage: ko\n"
    "---\nBody with [[person:Jane]] and 2026-10-12 and 한국어 규칙."
).encode()


def tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def directories(root: Path) -> tuple[str, ...]:
    return tuple(sorted(path.relative_to(root).as_posix()
                        for path in root.rglob("*") if path.is_dir()))


def test_apply_infers_provider_free_labels_and_reports_counts(tmp_path: Path) -> None:
    # Given a note with the full requested metadata families needing normalization.
    (tmp_path / "knowledge").mkdir()
    _ = (tmp_path / "knowledge" / "launch.md").write_bytes(META)

    # When initialization is explicitly applied without any provider.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then labels cover the requested families and counts match note labels.
    assert report.ok
    applied = (tmp_path / "knowledge" / "launch.md").read_bytes()
    assert b"type:project" in applied
    assert b"project:MyApp" in applied
    assert b"person:Jane" in applied and b"person:Kim" in applied
    assert b"date:2026-10-11" in applied and b"date:2026-10-12" in applied
    assert b"lang:ko" in applied and b"zone:knowledge" in applied
    counts = dict(report.label_counts)
    assert counts["project:MyApp"] == 1 and counts["lang:ko"] == 1
    assert counts["date:2026-10-11"] == 1 and counts["zone:knowledge"] == 1


def test_preview_changes_no_bytes_mtimes_or_directories(tmp_path: Path) -> None:
    # Given a vault with unnormalized notes.
    _ = (tmp_path / "first.md").write_bytes(b"Review every release.")
    before = tree(tmp_path)
    before_directories = directories(tmp_path)

    # When the labeled preview is requested without apply.
    report = run_init(plan_init(tmp_path))

    # Then no file, mtime or directory changes and counts are already visible.
    assert report.mode == "preview"
    assert tree(tmp_path) == before
    assert directories(tmp_path) == before_directories
    assert dict(report.label_counts).get("type:topic") == 1


def test_manual_labels_tags_and_explicit_empty_are_preserved(tmp_path: Path) -> None:
    # Given user-owned labels, tags and an explicit empty labels field.
    owned = (tmp_path / "owned.md")
    _ = owned.write_bytes(b"---\ntitle: Owned\ntype: topic\ntags: [mytag]\n"
                          + b"labels: [project:Zed]\n---\nOwner body.")
    _ = (tmp_path / "empty.md").write_bytes(b"---\ntitle: Empty\ntype: topic\ntags: []\n"
                                            + b"labels: []\n---\nEmpty body.")

    # When initialization labels the vault.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then manual labels and the empty field stay byte-identical and untouched.
    assert report.ok
    assert owned.read_bytes() == (b"---\ntitle: Owned\ntype: topic\ntags: [mytag]\n"
                                  + b"labels: [project:Zed]\n---\nOwner body.")
    assert (tmp_path / "empty.md").read_bytes() == (b"---\ntitle: Empty\ntype: topic\ntags: []\n"
                                                    + b"labels: []\n---\nEmpty body.")


def test_label_annotation_is_byte_exact_undoable(tmp_path: Path) -> None:
    # Given original unlabeled bytes.
    raw = b"Review every release."
    _ = (tmp_path / "policy.md").write_bytes(raw)

    # When apply journals the label normalization.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then all source bytes return exactly through the existing journal.
    assert report.undo_transaction is not None
    assert (tmp_path / "policy.md").read_bytes().endswith(raw)
    _ = undo_receipt(tmp_path, report.undo_transaction)
    assert (tmp_path / "policy.md").read_bytes() == raw


def test_grouping_picks_first_label_value_and_falls_back(tmp_path: Path) -> None:
    # Given notes with project labels of different case and one without.
    (tmp_path / "g").mkdir()
    _ = (tmp_path / "g" / "a.md").write_bytes(b"---\ntitle: A\ntype: topic\n"
                                               + b"project: Zed\n---\nA body.")
    _ = (tmp_path / "g" / "b.md").write_bytes(b"---\ntitle: B\ntype: topic\n"
                                               + b"project: [alpha, beta]\n---\nB body.")
    _ = (tmp_path / "g" / "c.md").write_bytes(b"---\ntitle: C\ntype: topic\n"
                                               + b"---\nC body.")

    # When grouping is opted in by project namespace.
    default = plan_init(tmp_path)
    grouped = plan_init(tmp_path, group_by_label="project")

    # Then group topics are the lexicographically first value, case retained,
    # with the existing topic as fallback and default grouping unchanged.
    assert {entry.trigger for entry in default.routes
            if entry.document.startswith("g/")}.issubset({"g", "A", "B", "C"})
    topics = {entry.trigger for entry in grouped.routes}
    assert "Zed" in topics and "alpha" in topics and "g" in topics
    assert not topics & {"Zeta", "beta", "zed", "Alpha", "Beta"}


def test_grouped_rerun_is_byte_and_mtime_stable(tmp_path: Path) -> None:
    # Given a vault already initialized with project grouping.
    (tmp_path / "g").mkdir()
    _ = (tmp_path / "g" / "a.md").write_bytes(b"---\ntitle: A\ntype: topic\n"
                                               + b"project: Zed\n---\nA body.")
    _ = (tmp_path / "g" / "b.md").write_bytes(b"---\ntitle: B\ntype: topic\n"
                                               + b"project: Alpha\n---\nB body.")
    first = run_init(plan_init(tmp_path, group_by_label="project"), apply=True)
    assert first.ok and first.mutations > 0
    image = tree(tmp_path)

    # When the same grouped initialization is applied again.
    second = run_init(plan_init(tmp_path, group_by_label="project"), apply=True)

    # Then nothing changes and the chosen topics remain stable.
    assert second.ok and second.mutations == 0
    assert tree(tmp_path) == image


def test_canonical_duplicate_spelling_counts_once_per_note(tmp_path: Path) -> None:
    # Given duplicate namespace spellings and distinct case-sensitive values.
    _ = (tmp_path / "a.md").write_bytes(b"---\ntitle: A\ntype: topic\ntags: []\n"
                                        + b"labels: [project:Alpha, Project:Alpha, project:alpha]\n---\nA body.")
    _ = (tmp_path / "b.md").write_bytes(b"---\ntitle: B\ntype: topic\ntags: []\n"
                                        + b"labels: [project:Alpha]\n---\nB body.")

    # When the plan histograms the effective labels.
    counts = dict(plan_init(tmp_path).label_counts)

    # Then one note counts once under the canonical spelling.
    assert counts == {"project:Alpha": 2, "project:alpha": 1}
    assert (tmp_path / "a.md").read_bytes().count(b"project:Alpha") == 1


@pytest.mark.parametrize("namespace", ["Not Valid!", "", "3bad", ":", "bad/ns"])
def test_invalid_group_namespace_refuses_before_any_writes(
    tmp_path: Path, namespace: str,
) -> None:
    # Given an absent vault and a malformed grouping namespace.
    root = tmp_path / "new" / "vault"

    # When the namespace is validated during planning.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, group_by_label=namespace)

    # Then nothing was planned or created.
    assert not root.exists() and not root.parent.exists()


def test_group_namespace_is_normalized_case_insensitively(tmp_path: Path) -> None:
    # Given a note with a manual project label.
    _ = (tmp_path / "a.md").write_bytes(b"---\ntitle: A\ntype: topic\ntags: []\n"
                                        + b"labels: [project:Zed]\n---\nA body.")

    # When the namespace arrives with mixed case and spacing.
    plan = plan_init(tmp_path, group_by_label="  Project  ")

    # Then it is normalized to the canonical lowercase namespace.
    assert "Zed" in {entry.trigger for entry in plan.routes}


def test_ambiguous_header_warns_and_stays_unmodified(tmp_path: Path) -> None:
    # Given metadata that cannot be safely labeled.
    raw = b"---\ntitle: First\ntitle: Second\n---\nRule."
    _ = (tmp_path / "bad.md").write_bytes(raw)

    # When the plan inspects and applies it.
    plan = plan_init(tmp_path)
    bad = next(note for note in plan.notes if note.path == "bad.md")
    report = run_init(plan, apply=True)

    # Then inference warns and never touches the unsafe bytes.
    assert bad.warning is not None and bad.normalized == bad.raw
    assert any("bad.md" in warning for warning in report.warnings)
    assert (tmp_path / "bad.md").read_bytes() == raw


def test_protected_split_receipt_notes_are_never_labeled(tmp_path: Path) -> None:
    # Given a note already bound to a split receipt.
    _ = (tmp_path / "policy.md").write_bytes(b"# Policy\nKeep approval.\n## Deploy\nKeep rollback.")
    split = split_note(tmp_path, "policy.md", apply=True)
    protected = ("policy.md", *(topic.document for topic in split.topics))
    before = {relative: (tmp_path / relative).read_bytes() for relative in protected}

    # When initialization runs to completion.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then protected sources keep exact bytes and no frontmatter additions.
    assert report.ok
    assert {relative: (tmp_path / relative).read_bytes() for relative in protected} == before
    assert all(not item.frontmatter_additions
               for item in report.sources if item.path in protected)


def test_import_replan_with_existing_labels_stays_idempotent(tmp_path: Path) -> None:
    # Given an import applied once so its destination already has labels.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "note.md").write_bytes(b"Imported rule body.")
    first = run_init(plan_init(root, import_dir=external), apply=True)
    destination = root / first.import_documents[0]
    assert b"labels: " in destination.read_bytes()
    image = tree(root)

    # When the same import is planned and applied again.
    replan = plan_init(root, import_dir=external)
    second = run_init(replan, apply=True)

    # Then describe_note agrees and nothing changes, while external stays intact.
    assert second.ok and second.mutations == 0
    assert tree(root) == image
    assert (external / "note.md").read_bytes() == b"Imported rule body."
    assert first.undo_transaction is not None
    _ = undo_receipt(root, first.undo_transaction)
    assert destination.read_bytes() == b"Imported rule body."


def test_nested_import_carries_the_full_parent_zone_label(tmp_path: Path) -> None:
    # Given a raw import nested below the import namespace.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "notes").mkdir()
    _ = (external / "notes" / "deep.txt").write_bytes(b"nested\n")

    # When the import is applied.
    report = run_init(plan_init(root, import_dir=external), apply=True)
    assert report.ok and report.imports == 1
    document = report.import_documents[0]
    parent = "/".join(document.split("/")[:-1])
    meta, _ = frontmatter.parse((root / document).read_bytes().decode("utf-8-sig"))

    # Then the zone label names the complete relative parent and counts once.
    zones = [label for label in meta["labels"]
             if isinstance(label, str) and label.startswith("zone:")]
    assert zones == [f"zone:{parent}"]
    assert zones[0].startswith("zone:imports/init-") and zones[0].endswith("/notes")
    assert dict(report.label_counts)[zones[0]] == 1

    # And a rerun stays byte-stable with the full-parent zone retained.
    image = tree(root)
    rerun = run_init(plan_init(root, import_dir=external), apply=True)
    assert rerun.ok and rerun.mutations == 0
    assert tree(root) == image


def test_labels_never_become_ranking_terms(tmp_path: Path) -> None:
    # Given a tagged note without labels.
    _ = (tmp_path / "policy.md").write_bytes(b"---\ntitle: Policy\ntype: topic\n"
                                             + b"---\nPolicy body.")

    # When label attachment runs during apply.
    report = run_init(plan_init(tmp_path), apply=True)
    applied = (tmp_path / "policy.md").read_bytes()

    # Then labels stay a separate metadata field, not a tag or title term.
    assert report.ok and b"labels: " in applied
    meta, _ = frontmatter.parse(applied.decode("utf-8"))
    assert meta["tags"] == [] and meta["title"] == "Policy"
    assert "labels" in meta


def test_complete_header_notes_gain_only_the_missing_labels(tmp_path: Path) -> None:
    # Given a note whose header is already complete without labels.
    raw = b"---\ntitle: Policy\ntype: topic\ntags: []\n---\nPolicy body."
    _ = (tmp_path / "policy.md").write_bytes(raw)

    # When initialization adds the newly supported metadata field.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then every pre-existing byte remains outside the added labels line.
    assert report.ok
    applied = (tmp_path / "policy.md").read_bytes()
    assert b"".join(line for line in applied.splitlines(keepends=True)
                    if not line.startswith(b"labels:")) == raw
    assert [item.frontmatter_additions for item in report.sources] == [("labels",)]
