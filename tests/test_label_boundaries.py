"""Malformed label input must not corrupt or reinterpret a note."""

import pytest

from birkin_mnemosyne.labels import (
    LabelContext,
    LabelError,
    annotate_labels,
    normalize_labels,
    read_labels,
    suggest_labels,
)

CONTEXT = LabelContext("notes/example.md")


@pytest.mark.parametrize("control", ["\x80", "\x85", "\x9e", "\u2028", "\u2029", "\t", "\n"])
@pytest.mark.parametrize("position", ["before", "inside", "after"])
def test_reject_controls_before_whitespace_normalization(
    control: str, position: str,
) -> None:
    value = {
        "before": control + "topic:owner",
        "inside": "topic:own" + control + "er",
        "after": "topic:owner" + control,
    }[position]
    with pytest.raises(LabelError):
        normalize_labels((value,))


@pytest.mark.parametrize("value", [
    "2026-10-111", "2026-10-11junk", "2026-10-11T99:00",
    "2026-10-11T12:99", "2026-10-11T", "２０２６-１０-１１",
])
def test_malformed_metadata_dates_are_not_suggested(value: str) -> None:
    raw = f"---\ncreated: {value}\n---\nbody".encode()
    assert not any(label.startswith("date:") for label in suggest_labels(raw, CONTEXT))


@pytest.mark.parametrize("value", [
    "2026-10-11", "2026-10-11T12:00:00Z", "2026-10-11T12:00:00+09:00",
])
def test_complete_iso_date_or_datetime_is_accepted(value: str) -> None:
    raw = f"---\ncreated: {value}\n---\nbody".encode()
    assert "date:2026-10-11" in suggest_labels(raw, CONTEXT)


def test_typed_wikilinks_use_target_not_alias_or_fragment() -> None:
    raw = b"[[person:Ada#Career|Ada Lovelace]] [[project:Alpha|display]] [[entity:Unit#API]]"
    assert suggest_labels(raw, CONTEXT) == (
        "entity:Unit", "person:Ada", "project:Alpha", "zone:notes",
    )


@pytest.mark.parametrize("header", [
    "title: T\nlabels:\n\n  - topic:owner\n",
    "title: T\nlabels:\n# keep this comment\n  - topic:owner\n",
    "title: T\nlabels:\n- topic:owner\n",
    "title: T\nlabels: # manual\n  - topic:owner\n",
    "title: T\nunparseable header line\n",
    "description: |\n  labels: [topic:owner]\n",
    "description: >\n  labels: [topic:owner]\n",
    "title: T\u0085labels: [topic:owner]\n",
    "title: T\u2028labels: [topic:owner]\n",
    "title: T\u2029labels: [topic:owner]\n",
])
def test_ambiguous_header_is_preserved_without_guessing(header: str) -> None:
    raw = ("---\n" + header + "---\nbody").encode()
    for replacement in (None, ("topic:new",)):
        result = annotate_labels(raw, CONTEXT, labels=replacement)
        assert result.raw == raw
        assert result.warning is not None
    with pytest.raises(LabelError):
        read_labels(raw)


@pytest.mark.parametrize("eol", [b"\r\n", b"\r", b"\n"])
def test_insert_at_eof_closing_fence_preserves_newline_style(eol: bytes) -> None:
    raw = eol.join((b"---", b"title: T", b"---"))
    result = annotate_labels(raw, CONTEXT, labels=("topic:new",))
    assert result.raw == eol.join((b"---", b"title: T", b'labels: ["topic:new"]', b"---"))
    assert result.labels == ("topic:new",)


@pytest.mark.parametrize("eol", [b"\r\n", b"\r", b"\n"])
def test_added_header_follows_body_newline_style(eol: bytes) -> None:
    raw = b"# Body" + eol + b"Exact body bytes"
    result = annotate_labels(raw, CONTEXT, labels=())
    assert result.raw == eol.join((b"---", b"labels: []", b"---", raw))


def test_nested_mixed_containers_warn_instead_of_crashing() -> None:
    raw = b"---\nmetadata:\n  name: value\n  - incompatible list\n---\nbody"
    result = annotate_labels(raw, CONTEXT)
    assert result.raw == raw
    assert result.warning is not None
