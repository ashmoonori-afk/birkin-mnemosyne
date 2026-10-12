"""Labels are eligibility metadata, never retrieval terms or graph links."""

from pathlib import Path

import pytest

from birkin_mnemosyne.labels import LabelContext, annotate_labels
from birkin_mnemosyne.label_frontmatter import scoring_text
from birkin_mnemosyne.mnemosyne import Mnemosyne, _note_entry


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_labels_do_not_change_terms_doclen_or_existing_links(
    tmp_path: Path, bom: bytes,
) -> None:
    path = tmp_path / "note.md"
    raw = bom + (
        b'---\ntitle: Header title\nrelated: "[[metadata-target]]"\n'
        b"---\nRetain body and [[body-target]].\n"
    )
    _ = path.write_bytes(raw)
    before = _note_entry(path, "note.md")
    assert before is not None
    edited = annotate_labels(raw, LabelContext("note.md"), labels=("custom:[[phantom]]",))
    _ = path.write_bytes(edited.raw)
    after = _note_entry(path, "note.md")
    assert after is not None
    assert after["terms"] == before["terms"]
    assert after["doclen"] == before["doclen"]
    assert after["links"] == before["links"] == ["body-target", "metadata-target"]
    assert after["title"] == "Header title"


def test_malformed_label_block_cannot_break_ordinary_recall(tmp_path: Path) -> None:
    _ = (tmp_path / "note.md").write_bytes(
        b"---\ntitle: Header title\nlabels:\n- invalid:block\n---\nordinary recall\n"
    )
    engine = Mnemosyne(tmp_path)
    assert [hit["slug"] for hit in engine.search("ordinary")] == ["note"]
    assert engine.search("ordinary", labels=("invalid:block",)) == []


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_retrieval_keeps_legacy_universal_newline_representation(newline: bytes) -> None:
    raw = newline.join((
        b"---", b"title: Kept", b'labels: ["custom:excluded"]', b"---",
        b"[[multiline", b"target]]", b"",
    ))
    assert scoring_text(raw) == "---\ntitle: Kept\n---\n[[multiline\ntarget]]\n"
