"""Raw text and JSON imports become one lossless labeled candidate each."""

import re
from pathlib import Path

import pytest

from birkin_mnemosyne import frontmatter
from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_plan import plan_init
from birkin_mnemosyne.review_journal import ReviewError, undo_receipt


def tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def directories(root: Path) -> tuple[str, ...]:
    return tuple(sorted(path.relative_to(root).as_posix()
                        for path in root.rglob("*") if path.is_dir()))


def seed_three(external: Path, *, valid_json: bool = True) -> None:
    _ = (external / "x.md").write_bytes(b"# X\nMarkdown body.\n")
    _ = (external / "x.txt").write_bytes(b"first\r\nsecond\n")
    payload = b'{"ok": true, "value": 3}' if valid_json else b'{"broken": '
    _ = (external / "x.json").write_bytes(payload)


def test_same_basename_across_formats_stay_distinct(tmp_path: Path) -> None:
    # Given one basename in every supported format and no vault yet.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = seed_three(external)

    # When the import is planned and applied.
    plan = plan_init(root, import_dir=external)
    md_copy = next(copy for copy in plan.imports if copy.format == "md")

    # Then every format keeps its original suffix and Markdown stays raw.
    assert {Path(copy.destination.path).name for copy in plan.imports} == {
        "x.md", "x.txt.md", "x.json.md"}
    assert md_copy.preimage == md_copy.destination.raw
    first = run_init(plan, apply=True)
    assert first.ok and first.imports == first.notes == 3

    # When the identical import runs again.
    image = tree(root)
    second = run_init(plan_init(root, import_dir=external), apply=True)

    # Then nothing mutates and no journal is created.
    assert second.ok and second.mutations == 0 and second.journal is None
    assert tree(root) == image
    assert (external / "x.txt").read_bytes() == b"first\r\nsecond\n"


@pytest.mark.parametrize(("name", "raw"), [
    ("x.txt", b"\xef\xbb\xbfline one\r\nline two\r\n`single` and ````` run\r\n"),
    ("x.json", b'{"code": "````", "note": "CRLF\r\ninside"}\n'),
])
def test_fenced_candidates_preserve_raw_body_bytes(tmp_path: Path, name: str,
                                                   raw: bytes) -> None:
    # Given a BOM, CRLF and backtick-heavy payload that must survive verbatim.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / name).write_bytes(raw)

    # When the lossless candidate is planned.
    plan = plan_init(root, import_dir=external)
    copy = plan.imports[0]
    longest = max((len(match.group(0)) for match in re.finditer(rb"`+", raw)), default=0)
    fence = b"`" * max(3, longest + 1)

    # Then the preimage differs from the fenced candidate that contains it.
    assert copy.preimage == raw and copy.preimage != copy.destination.raw
    assert copy.destination.raw.startswith(fence + b"\n")
    assert copy.destination.raw.endswith(fence + b"\n")
    assert raw in copy.destination.raw

    # When the plan is applied and the vault re-read.
    report = run_init(plan, apply=True)

    # Then the exact body bytes survive publication and the source is untouched.
    assert report.ok
    assert raw in (root / report.import_documents[0]).read_bytes()
    assert (external / name).read_bytes() == raw


def test_invalid_json_warns_but_stays_text(tmp_path: Path) -> None:
    # Given a JSON file that does not parse.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "x.json").write_bytes(b'{"broken": ')

    # When it is planned, previewed and applied.
    plan = plan_init(root, import_dir=external)
    assert any("invalid JSON" in warning for warning in plan.warnings)
    preview = run_init(plan)

    # Then the text is preserved with a warning, no extraction or rewrite.
    assert preview.imports == 1 and any("invalid JSON" in warning
                                        for warning in preview.warnings)
    report = run_init(plan, apply=True)
    assert report.ok
    assert b'{"broken": ' in (root / report.import_documents[0]).read_bytes()
    rerun = run_init(plan_init(root, import_dir=external), apply=True)
    assert rerun.ok and rerun.mutations == 0


@pytest.mark.parametrize("name", ["bad.md", "bad.txt", "bad.json"])
def test_invalid_utf8_import_is_refused(tmp_path: Path, name: str) -> None:
    # Given a source that is not valid UTF-8 in any supported format.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / name).write_bytes(b"ok \xff\xfe broken")

    # When the import is planned.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=external)

    # Then no vault state is created.
    assert not root.exists()


def test_unsupported_hidden_and_archive_files_are_excluded(tmp_path: Path) -> None:
    # Given mixed visible and excluded sources in one directory.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "keep.md").write_bytes(b"kept")
    _ = (external / "drop.csv").write_bytes(b"drop")
    _ = (external / "drop.png").write_bytes(b"png")
    _ = (external / ".hidden.md").write_bytes(b"hidden")
    _ = (external / "_archive").mkdir()
    _ = (external / "_archive" / "old.md").write_bytes(b"old")

    # When the directory is inventoried.
    plan = plan_init(root, import_dir=external)

    # Then only the visible supported source becomes a candidate.
    assert len(plan.imports) == 1
    assert plan.imports[0].source_label == "keep.md"


def test_single_file_import_is_deterministic_idempotent_and_undoable(
    tmp_path: Path,
) -> None:
    # Given one explicit text file outside the vault.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    raw = b"single file body\n"
    _ = (external / "single.txt").write_bytes(raw)
    plan = plan_init(root, import_dir=external / "single.txt")
    copy = plan.imports[0]

    # When it is applied, re-applied and undone.
    first = run_init(plan, apply=True)
    assert first.ok and first.imports == 1 and first.notes == 1
    destination = root / first.import_documents[0]
    assert b"single file body" in destination.read_bytes()
    image = tree(root)
    second = run_init(plan_init(root, import_dir=external / "single.txt"), apply=True)

    # Then reruns stay stable and undo restores the pre-normalized candidate.
    assert second.ok and second.mutations == 0 and second.journal is None
    assert tree(root) == image
    assert first.undo_transaction is not None
    _ = undo_receipt(root, first.undo_transaction)
    assert destination.read_bytes() == copy.destination.raw
    assert (external / "single.txt").read_bytes() == raw


@pytest.mark.parametrize(("name", "content"), [
    ("data.csv", b"a,b\n"),
    (".secret.md", b"hidden"),
])
def test_single_file_import_rejects_unsupported_or_hidden(
    tmp_path: Path, name: str, content: bytes,
) -> None:
    # Given an explicit file that is not a visible supported source.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / name).write_bytes(content)

    # When the file itself is the import argument.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=external / name)

    # Then nothing was created or planned.
    assert not root.exists()


def test_import_overlap_with_vault_is_refused(tmp_path: Path) -> None:
    # Given a vault and import paths that contain it or live inside it.
    outer = tmp_path / "outer"
    outer.mkdir()
    vault = outer / "vault"
    vault.mkdir()
    _ = (vault / "inside.md").write_bytes(b"x")
    before = tree(outer)

    # When each overlapping path is offered as the import.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(vault, import_dir=vault / "inside.md")
    with pytest.raises(MemoryIndexError):
        _ = plan_init(vault, import_dir=outer)

    # Then no source or vault file was changed by either refused plan.
    assert tree(outer) == before


def test_linked_import_paths_are_refused(tmp_path: Path) -> None:
    # Given a real source tree plus a symlinked root and entry.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "x.md").write_bytes(b"body")
    link = tmp_path / "link"
    link.symlink_to(external, target_is_directory=True)
    _ = (external / "inside.md").write_bytes(b"ok")
    alias = external / "alias.md"
    alias.symlink_to(external / "inside.md")

    # When the linked root or a linked entry is scanned.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=link)
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=external)

    # Then both unsafe sources are refused before any plan exists.
    assert not root.exists()


def test_stale_source_and_selection_refuse_apply(tmp_path: Path) -> None:
    # Given a plan followed by a source edit, addition or removal.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "x.txt").write_bytes(b"original\n")
    changed = plan_init(root, import_dir=external)
    _ = (external / "x.txt").write_bytes(b"changed\n")
    with pytest.raises(ReviewError):
        _ = run_init(changed, apply=True)
    assert not (root / "imports").exists()
    assert not MemoryIndex(root).read().enabled

    added = plan_init(root, import_dir=external)
    _ = (external / "added.txt").write_bytes(b"new\n")
    with pytest.raises(ReviewError):
        _ = run_init(added, apply=True)
    _ = (external / "added.txt").unlink()

    removed = plan_init(root, import_dir=external)
    _ = (external / "x.txt").unlink()
    with pytest.raises(ReviewError):
        _ = run_init(removed, apply=True)

    # Then no import artifact was published by any stale apply.
    assert not (root / "imports").exists()


def test_destination_collision_from_suffix_is_refused(tmp_path: Path) -> None:
    # Given two sources whose converted names coincide.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "x.txt").write_bytes(b"a\n")
    _ = (external / "x.txt.md").write_bytes(b"b\n")

    # When the sources are inventoried.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=external)

    # Then the ambiguous destination is refused without creating a plan.
    assert not root.exists()


def test_case_colliding_import_names_are_refused(tmp_path: Path) -> None:
    # Given two visible sources that differ only in file-name case.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "a.txt").write_bytes(b"first\n")
    _ = (external / "A.txt").write_bytes(b"second\n")
    if len(tuple(external.iterdir())) < 2:
        pytest.skip("case-insensitive filesystem cannot hold case-variant names")

    # When their case-folded destinations would collide.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=external)

    # Then the collision is refused before any plan exists.
    assert not root.exists()


def test_import_notes_carry_source_and_format_labels(tmp_path: Path) -> None:
    # Given imports with and without manually owned metadata.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "x.md").write_bytes(b"---\ntags: [keep]\n---\nbody\n")
    _ = (external / "x.txt").write_bytes(b"text\n")
    _ = (external / "manual.md").write_bytes(
        b"---\ntags: [own]\nlabels: [project:Alpha]\n---\nbody\n")
    _ = (external / "notes").mkdir()
    _ = (external / "notes" / "deep.txt").write_bytes(b"nested\n")

    # When the imports are applied.
    report = run_init(plan_init(root, import_dir=external), apply=True)
    assert report.ok and report.imports == 4
    contents = {Path(document).name: (root / document).read_bytes().decode("utf-8-sig")
                for document in report.import_documents}

    # Then source and format labels identify the original filename.
    meta_md, _ = frontmatter.parse(contents["x.md"])
    assert meta_md["tags"] == ["keep"]
    assert "source:x.md" in meta_md["labels"] and "format:md" in meta_md["labels"]
    meta_txt, _ = frontmatter.parse(contents["x.txt.md"])
    assert "source:x.txt" in meta_txt["labels"] and "format:txt" in meta_txt["labels"]
    meta_deep, _ = frontmatter.parse(contents["deep.txt.md"])
    assert "source:notes/deep.txt" in meta_deep["labels"]
    assert "format:txt" in meta_deep["labels"]

    # And manually owned labels survive without injected replacements.
    meta_manual, _ = frontmatter.parse(contents["manual.md"])
    assert meta_manual["tags"] == ["own"]
    assert "project:Alpha" in meta_manual["labels"]
    assert "format:md" not in meta_manual["labels"]


def test_edited_import_destination_refused_for_txt(tmp_path: Path) -> None:
    # Given an imported text note edited by its owner after apply.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = (external / "x.txt").write_bytes(b"original\n")
    first = run_init(plan_init(root, import_dir=external), apply=True)
    destination = root / first.import_documents[0]
    owner = b"Owner revision."
    _ = destination.write_bytes(owner)

    # When the same import is planned again.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=external)

    # Then neither the source nor the owner revision is touched.
    assert destination.read_bytes() == owner
    assert (external / "x.txt").read_bytes() == b"original\n"


def test_preview_writes_no_files_locks_or_caches(tmp_path: Path) -> None:
    # Given an external tree with every format and no vault.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    _ = seed_three(external)
    before = tree(tmp_path)
    before_directories = directories(tmp_path)

    # When the import is previewed.
    report = run_init(plan_init(root, import_dir=external))

    # Then no bytes, mtimes, directories, locks or caches appear anywhere.
    assert report.mode == "preview" and report.imports == 3
    assert tree(tmp_path) == before
    assert directories(tmp_path) == before_directories
    assert not root.exists()
