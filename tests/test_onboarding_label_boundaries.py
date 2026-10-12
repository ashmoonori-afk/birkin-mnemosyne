"""Initialization reports labels that it actually persists, without guessing."""

from pathlib import Path

import pytest

from birkin_mnemosyne.labels import read_labels
from birkin_mnemosyne.memory_index import MemoryIndexError
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_notes import SourceBytes, describe_note
from birkin_mnemosyne.onboarding_plan import plan_init
from birkin_mnemosyne.review_journal import undo_receipt


def test_complete_unlabeled_header_is_labeled_and_exactly_undoable(tmp_path: Path) -> None:
    raw = b"---\r\ntitle: Complete\r\ntype: fact\r\ntags: [owner]\r\n---\r\nBody"
    path = tmp_path / "complete.md"
    _ = path.write_bytes(raw)
    plan = plan_init(tmp_path)
    assert path.read_bytes() == raw
    report = run_init(plan, apply=True)
    actual = read_labels(path.read_bytes())
    assert actual and dict(report.label_counts) == {label: 1 for label in actual}
    assert report.undo_transaction is not None
    _ = undo_receipt(tmp_path, report.undo_transaction)
    assert path.read_bytes() == raw


def test_complete_markdown_import_gets_source_and_format_labels(tmp_path: Path) -> None:
    source, vault = tmp_path / "complete.md", tmp_path / "vault"
    raw = b"---\ntitle: Complete\ntype: fact\ntags: [owner]\n---\nBody"
    _ = source.write_bytes(raw)
    report = run_init(plan_init(vault, import_dir=source), apply=True)
    labels = read_labels((vault / report.import_documents[0]).read_bytes())
    assert labels is not None and {"source:complete.md", "format:md"} <= set(labels)
    assert source.read_bytes() == raw


@pytest.mark.parametrize("namespace", ["project:Alpha", "project:", "project::x"])
def test_group_namespace_cannot_include_a_label_value(tmp_path: Path, namespace: str) -> None:
    with pytest.raises(MemoryIndexError):
        _ = plan_init(tmp_path / "absent", group_by_label=namespace)
    assert not (tmp_path / "absent").exists()


def test_counts_preserve_distinct_values_and_normalize_namespace_only(tmp_path: Path) -> None:
    raw = b'---\ntitle: A\ntype: fact\ntags: []\nlabels: ["Project:Alpha", "project:Alpha", "project:alpha"]\n---\nBody'
    _ = (tmp_path / "a.md").write_bytes(raw)
    assert dict(plan_init(tmp_path).label_counts) == {"project:Alpha": 1, "project:alpha": 1}
    assert (tmp_path / "a.md").read_bytes() == raw


@pytest.mark.parametrize("header", [
    b"labels:\n- project:broken\n",
    b"metadata:\n  name: value\n  - mixed container\n",
    b"labels: invalid\n",
])
def test_unsafe_headers_warn_without_rewriting_or_crashing(
    tmp_path: Path, header: bytes,
) -> None:
    raw = b"---\ntitle: Bad\ntype: fact\ntags: []\n" + header + b"---\nBody"
    path = tmp_path / "bad.md"
    _ = path.write_bytes(raw)
    report = run_init(plan_init(tmp_path), apply=True)
    assert report.warnings and report.label_counts == ()
    assert path.read_bytes() == raw


def test_protected_note_never_reports_unwritten_label_suggestions() -> None:
    raw = b"---\ntitle: Protected\ntype: fact\ntags: []\n---\nBody"
    note = describe_note(
        SourceBytes("protected.md", raw), protected=True, group_by_label="type",
    )
    assert note.normalized == raw and note.labels == ()
    assert note.topic == "fact"


def test_import_does_not_accept_a_changed_destination_body(tmp_path: Path) -> None:
    external, vault = tmp_path / "source", tmp_path / "vault"
    external.mkdir()
    _ = (external / "note.txt").write_bytes(b"Original imported body")
    first = run_init(plan_init(vault, import_dir=external), apply=True)
    destination = vault / first.import_documents[0]
    edited = destination.read_bytes().replace(b"Original imported body", b"Owner changed this body")
    _ = destination.write_bytes(edited)
    with pytest.raises(MemoryIndexError):
        _ = plan_init(vault, import_dir=external)
    assert destination.read_bytes() == edited
