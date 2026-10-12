"""Byte-exact label field edits: BOM, CRLF, comments, bodies and ambiguity."""

from pathlib import Path

import pytest

from birkin_mnemosyne.labels import (
    LabelContext,
    LabelError,
    annotate_labels,
    read_labels,
)

CTX = LabelContext("docs/note.md")


def test_insert_keeps_other_header_bytes_and_body() -> None:
    raw = b"---\ntitle: T\n# keep this comment\nzone: z\n---\nBody without newline"
    edit = annotate_labels(raw, CTX, labels=("a:x",))
    assert edit.raw == (
        b"---\ntitle: T\n# keep this comment\nzone: z\nlabels: [\"a:x\"]\n---\n"
        b"Body without newline"
    )
    assert edit.warning is None


def test_replace_changes_only_the_labels_line() -> None:
    raw = b"---\r\ntitle: T\r\n# comment\r\nlabels: [\"old:v\"]\r\nzone: z\r\n---\r\nbody\r\n"
    edit = annotate_labels(raw, CTX, labels=("new:x",))
    assert edit.raw == raw.replace(b'labels: ["old:v"]\r\n', b'labels: ["new:x"]\r\n')
    assert edit.raw.count(b"\r\n") == raw.count(b"\r\n")


def test_crlf_insert_uses_crlf_framing() -> None:
    raw = b"---\r\ntitle: T\r\n---\r\nbody\r\n"
    edit = annotate_labels(raw, CTX, labels=())
    assert edit.raw == b"---\r\ntitle: T\r\nlabels: []\r\n---\r\nbody\r\n"


def test_bom_and_crlf_are_preserved_on_insert() -> None:
    raw = b"\xef\xbb\xbf---\r\ntitle: T\r\n---\r\nbody"
    edit = annotate_labels(raw, CTX, labels=("a:x",))
    assert edit.raw == b"\xef\xbb\xbf---\r\ntitle: T\r\nlabels: [\"a:x\"]\r\n---\r\nbody"


def test_bom_stays_at_byte_zero_when_header_is_added() -> None:
    raw = b"\xef\xbb\xbf# Body only\n"
    edit = annotate_labels(raw, CTX, labels=("a:x",))
    assert edit.raw == (b"\xef\xbb\xbf---\nlabels: [\"a:x\"]\n---\n" + b"# Body only\n")
    assert edit.raw.startswith(b"\xef\xbb\xbf")


def test_header_is_added_when_absent() -> None:
    raw = b"Plain body, no final newline"
    edit = annotate_labels(raw, CTX, labels=("a:x",))
    assert edit.raw == b"---\nlabels: [\"a:x\"]\n---\n" + raw
    assert edit.raw.endswith(raw)


def test_empty_scalar_labels_is_owned_and_replaceable() -> None:
    raw = b"---\ntitle: T\nlabels:\n---\nbody"
    assert read_labels(raw) == ()
    edit = annotate_labels(raw, CTX, labels=("a:x",))
    assert edit.raw == b'---\ntitle: T\nlabels: ["a:x"]\n---\nbody'


def test_multiline_block_is_retained_with_warning() -> None:
    raw = b"---\ntitle: T\nlabels:\n  - old:v\n---\nbody"
    kept = annotate_labels(raw, CTX)
    assert kept.raw == raw and kept.warning is not None and kept.labels == ()
    refused = annotate_labels(raw, CTX, labels=("new:x",))
    assert refused.raw == raw and refused.warning is not None


def test_duplicate_keys_are_retained_with_warning() -> None:
    raw = b"---\ntitle: a\ntitle: b\n---\nbody"
    edit = annotate_labels(raw, CTX, labels=("x:y",))
    assert edit.raw == raw and edit.warning is not None and edit.labels == ()


def test_anchor_ambiguous_header_is_retained_with_warning() -> None:
    raw = b"---\nbase: &shared\n  value: x\n---\nbody"
    edit = annotate_labels(raw, CTX)
    assert edit.raw == raw and edit.warning is not None


def test_unterminated_frontmatter_is_retained_with_warning() -> None:
    raw = b"---\ntitle: T\nbody text without closing fence"
    edit = annotate_labels(raw, CTX, labels=("x:y",))
    assert edit.raw == raw and edit.warning is not None


def test_invalid_existing_field_is_retained_with_warning() -> None:
    raw = b'---\nlabels: "a scalar"\n---\nbody'
    edit = annotate_labels(raw, CTX)
    assert edit.raw == raw and edit.warning is not None and edit.labels == ()


def test_preserved_manual_labels_keep_verbatim_spelling() -> None:
    raw = b'---\nlabels: ["Project:Alpha", "beta:1"]\n---\nbody'
    kept = annotate_labels(raw, CTX)
    assert kept.raw == raw and kept.labels == ("Project:Alpha", "beta:1")


def test_annotate_never_mutates_input_bytes() -> None:
    raw = b"---\ntitle: T\n---\nbody"
    before = bytes(raw)
    annotate_labels(raw, CTX, labels=("a:x",))
    assert raw == before


def test_comments_and_other_keys_survive_labels_edits() -> None:
    raw = (
        b"---\n"
        b"title: T\n"
        b"# section comment\n"
        b"metadata:\n"
        b"  nested: [1, 2]\n"
        b"polarity: negative\n"
        b'labels: ["old:v"]\n'
        b"---\n"
        b"# Body heading\n"
        b"content\n"
    )
    edit = annotate_labels(raw, CTX, labels=("new:v",))
    assert b"# section comment" in edit.raw
    assert b"metadata:\n  nested: [1, 2]\n" in edit.raw
    assert b"polarity: negative\n" in edit.raw
    assert edit.raw.endswith(b"# Body heading\ncontent\n")


def test_quoted_value_round_trips_through_yaml() -> None:
    raw = b'---\nlabels: ["a:say \\"hi\\""]\n---\nbody'
    assert read_labels(raw) == ('a:say "hi"',)
    edit = annotate_labels(raw, CTX, labels=('a:say "hi"',))
    assert edit.raw == raw and edit.warning is None


def test_labels_edits_never_touch_no_frontmatter_body() -> None:
    raw = "한국어 본문\r\n끝".encode()
    edit = annotate_labels(raw, CTX, labels=("a:x",))
    assert edit.raw.endswith(raw)


def test_unicode_and_control_rejected_values_warn_not_fail() -> None:
    raw = b"---\nlabels: [bad_tab\x01, ok:x]\n---\nbody"
    edit = annotate_labels(raw, CTX)
    assert edit.raw == raw and edit.warning is not None


def test_real_file_round_trip_preserves_bytes(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    original = b"---\r\ntitle: T\r\n# comment\r\n---\r\nbody\r\n"
    path.write_bytes(original)
    edit = annotate_labels(path.read_bytes(), CTX, labels=("a:x", "b:y"))
    path.write_bytes(edit.raw)
    assert read_labels(path.read_bytes()) == ("a:x", "b:y")
    assert path.read_bytes().startswith(b"---\r\ntitle: T\r\n# comment\r\n")
    assert path.read_bytes().endswith(b"body\r\n")


def test_explicit_empty_writes_bare_list_field() -> None:
    raw = b"---\ntitle: T\n---\nbody"
    edit = annotate_labels(raw, CTX, labels=())
    assert edit.raw == b"---\ntitle: T\nlabels: []\n---\nbody"
    assert read_labels(edit.raw) == ()


@pytest.mark.parametrize("raw", [
    b"---\ntitle: T\nlabels: [project:x]\n",
    b"labels: []\nno frontmatter fence",
    b"---\nlabels: []\n---\n",
])
def test_suggestions_do_not_require_header_structure(raw: bytes) -> None:
    edit = annotate_labels(raw, CTX)
    assert isinstance(edit.raw, bytes) and isinstance(edit.suggestions, tuple)


def test_label_error_is_value_error() -> None:
    assert issubclass(LabelError, ValueError)