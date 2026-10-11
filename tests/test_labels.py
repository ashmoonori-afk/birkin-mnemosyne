"""Deterministic normalization, label inference and the strict read boundary."""

from collections.abc import Callable
from pathlib import Path

import pytest

from birkin_mnemosyne.labels import (
    LabelContext,
    LabelError,
    LabelEdit,
    annotate_labels,
    normalize_labels,
    read_labels,
    suggest_labels,
)

dynamic_normalize: Callable[..., tuple[str, ...]] = normalize_labels
dynamic_annotate: Callable[..., LabelEdit] = annotate_labels

FAMILY_RAW = (
    b"---\n"
    b"title: Alpha Project\n"
    b"type: project\n"
    b"zone: research\n"
    b"topic: kubernetes\n"
    b"project: phoenix\n"
    b"people: [ana, bob]\n"
    b"entities: [service-x]\n"
    b"created: 2026-10-11\n"
    b"language: ko\n"
    b"---\n"
    b"[[project:acme]] wired up 2026-10-11 and 2026-02-30 postponed.\n"
)
FAMILY_CONTEXT = LabelContext("vault/alpha.md", index_topics=("kubernetes", "storage"))



# -- normalization ----


def test_normalize_sorts_and_deduplicates() -> None:
    assert normalize_labels(["b:y", "a:x", "b:y"]) == ("a:x", "b:y")


def test_normalize_lowercases_namespace_keeps_value_case() -> None:
    assert normalize_labels(["Project:Alpha", "PROJ-2:Beta"]) == (
        "proj-2:Beta", "project:Alpha")


def test_normalize_applies_nfc_and_trims_outer_whitespace() -> None:
    assert normalize_labels(["  topic:  cafe\u0301  "]) == ("topic:caf\u00e9",)


def test_normalize_accepts_tuple() -> None:
    assert normalize_labels(("a:x",)) == ("a:x",)


def test_normalize_empty_iterable_is_explicit_clear() -> None:
    assert normalize_labels(()) == ()


@pytest.mark.parametrize("raw", ["project:x", b"project:x", "", b""])
def test_normalize_rejects_bare_string_or_bytes(raw: object) -> None:
    with pytest.raises(LabelError):
        dynamic_normalize(raw)


@pytest.mark.parametrize("entry", ["", "plain", ":x", "a:", "1abc:x", "my ns:x",
                                   "a:b\x00c", "\x1f:d", "a:b\x7f", 123, None,
                                   ["nested"]])
def test_normalize_rejects_malformed_entries(entry: object) -> None:
    with pytest.raises(LabelError):
        dynamic_normalize([entry])



# -- read_labels ----


def test_read_labels_absent_is_none() -> None:
    assert read_labels(b"# no frontmatter") is None
    assert read_labels(b"---\ntitle: T\n---\nbody") is None
    assert read_labels(b"") is None


def test_read_labels_explicit_empty_is_owned() -> None:
    assert read_labels(b"---\nlabels: []\n---\n") == ()


def test_read_labels_returns_existing_verbatim() -> None:
    raw = b'---\nlabels: ["Project:Alpha", "beta:1"]\n---\n'
    assert read_labels(raw) == ("Project:Alpha", "beta:1")


def test_read_labels_rejects_block_list() -> None:
    raw = b"---\nlabels:\n  - project:x\n  - topic:y\n---\n"
    with pytest.raises(LabelError):
        read_labels(raw)


def test_read_labels_bare_key_is_explicit_empty() -> None:
    assert read_labels(b"---\ntitle: T\nlabels:\n---\nbody") == ()


@pytest.mark.parametrize("raw", [
    b"---\nlabels: project:x\n---\n",
    b"---\nlabels: [no-colon]\n---\n",
    b"---\nlabels: [ok:x, 123]\n---\n",
    b"---\nlabels: [true]\n---\n",
    b"---\nlabels: {a: b}\n---\n",
    b"---\ntitle: T\nlabels: [project:x]\nlabels: [topic:y]\n---\n",
    b"---\ntitle: T\ntitle: Dup\nlabels: [project:x]\n---\n",
    b"---\ntitle: T\nbase: &shared\n  value: x\n---\n",
    b"---\ntitle: T\nlabels: [project:x]\nbody without closing fence",
])
def test_read_labels_raises_on_invalid_metadata(raw: bytes) -> None:
    with pytest.raises(LabelError):
        read_labels(raw)



# -- suggest families ----


def test_suggest_covers_all_metadata_families() -> None:
    assert suggest_labels(FAMILY_RAW, FAMILY_CONTEXT) == (
        "date:2026-10-11",
        "entity:service-x",
        "lang:ko",
        "person:ana",
        "person:bob",
        "project:Alpha Project",
        "project:acme",
        "project:phoenix",
        "topic:kubernetes",
        "topic:storage",
        "type:project",
        "zone:research",
    )


def test_person_type_derives_person_value_from_title() -> None:
    raw = b"---\ntype: person\ntitle: Ada Lovelace\n---\nnotes"
    assert suggest_labels(raw, LabelContext("people/ada.md")) == (
        "person:Ada Lovelace", "type:person", "zone:people")


def test_project_type_falls_back_to_path_stem() -> None:
    raw = b"---\ntype: project\n---\nnotes"
    assert suggest_labels(raw, LabelContext("a/broken-project.md")) == (
        "project:broken-project", "type:project", "zone:a")


def test_path_zone_used_only_without_explicit_zone() -> None:
    raw = b"---\ntopic: x\n---\nbody"
    only_path = suggest_labels(raw, LabelContext("knowledge/policy.md"))
    explicit = suggest_labels(b"---\nzone: vault\n---\n",
                              LabelContext("knowledge/policy.md"))
    assert "zone:knowledge" in only_path
    assert "zone:vault" in explicit and "zone:knowledge" not in explicit


def test_suggest_ignores_existing_labels_field() -> None:
    raw = b'---\ntitle: T\nlabels: ["user:tag"]\n---\n[[project:x]]'
    suggestions = suggest_labels(raw, LabelContext("z/a.md"))
    assert "user:tag" not in suggestions and "project:x" in suggestions


def test_menu_scalar_and_list_person_entities() -> None:
    raw = b"---\nperson: solo\nentity: thing\n---\n"
    assert suggest_labels(raw, LabelContext("z/a.md")) == (
        "entity:thing", "person:solo", "zone:z")


def test_index_topics_become_topic_labels() -> None:
    assert "topic:storage" in suggest_labels(b"---\n---\nbody", FAMILY_CONTEXT)


def test_import_source_and_format_labels() -> None:
    raw = b"Plain text import body\n"
    ctx = LabelContext("imports/export.json.md", source="export.json", format="json")
    assert suggest_labels(raw, ctx) == (
        "format:json", "source:export.json", "zone:imports")



# -- languages ----


@pytest.mark.parametrize(("body", "expected"), [
    ("\uc548\ub155\ud558\uc138\uc694 \uc138\uacc4", "ko"),
    ("\u3053\u3093\u306b\u3061\u306f", "ja"),
    ("\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440", "ru"),
    ("\u0627\u0644\u0633\u0644\u0627\u0645 \u0639\u0644\u064a\u0643\u0645", "ar"),
])
def test_script_evidence_detects_language(body: str, expected: str) -> None:
    raw = f"---\n---\n{body}".encode("utf-8")
    assert ("lang:" + expected) in suggest_labels(raw, LabelContext("z/a.md"))


def test_latin_text_alone_stays_unknown() -> None:
    raw = b"---\n---\nJust an ordinary English-looking Latin sentence."
    assert not any(label.startswith("lang:") for label in suggest_labels(raw, LabelContext("z/a.md")))


def test_mixed_scripts_stay_unknown() -> None:
    body = "\uc548\ub155\ud558\uc138\uc694 \u3053\u3093\u306b\u3061\u306f"
    raw = f"---\n---\n{body}".encode("utf-8")
    assert not any(label.startswith("lang:") for label in suggest_labels(raw, LabelContext("z/a.md")))


def test_explicit_language_wins_over_script() -> None:
    raw = ("---\nlanguage: fr\n---\n\uc548\ub155\ud558\uc138\uc694").encode("utf-8")
    assert "lang:fr" in suggest_labels(raw, LabelContext("z/a.md"))
    assert not any(label == "lang:ko" for label in suggest_labels(raw, LabelContext("z/a.md")))


def test_lang_metadata_key_is_accepted() -> None:
    raw = b"---\nlang: ja\n---\nbody"
    assert "lang:ja" in suggest_labels(raw, LabelContext("z/a.md"))



# -- dates ----


def test_impossible_dates_are_not_suggested() -> None:
    raw = b"---\ncreated: 2026-02-30\n---\n2026-02-30 never happened 2026-13-01"
    assert "date:2026-02-30" not in suggest_labels(raw, LabelContext("z/a.md"))
    assert "date:2026-13-01" not in suggest_labels(raw, LabelContext("z/a.md"))


def test_iso_datetime_mentions_yield_date_labels() -> None:
    raw = b"---\nupdated: 2026-10-11T12:00:00+09:00\n---\ndeadline 2026-12-31T23:59"
    assert "date:2026-10-11" in suggest_labels(raw, LabelContext("z/a.md"))
    assert "date:2026-12-31" in suggest_labels(raw, LabelContext("z/a.md"))


def test_multiple_real_dates_are_all_suggested() -> None:
    raw = b"---\n---\n2026-01-02 then 2026-03-04"
    suggestions = suggest_labels(raw, LabelContext("z/a.md"))
    assert "date:2026-01-02" in suggestions and "date:2026-03-04" in suggestions



# -- determinism and annotate high level ----


def test_suggestions_are_deterministic_on_rerun() -> None:
    first = suggest_labels(FAMILY_RAW, FAMILY_CONTEXT)
    assert suggest_labels(FAMILY_RAW, FAMILY_CONTEXT) == first
    edited = annotate_labels(FAMILY_RAW, FAMILY_CONTEXT).raw
    assert suggest_labels(edited, FAMILY_CONTEXT) == first


def test_annotate_without_labels_preserves_existing_field() -> None:
    raw = b'---\ntitle: T\nlabels: ["user:tag"]\n---\nbody'
    edit = annotate_labels(raw, LabelContext("z/a.md"))
    assert edit.raw == raw and edit.labels == ("user:tag",) and edit.warning is None


def test_annotate_suggestion_edit_is_round_trippable(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"# Policy\n\nNo header yet.\n")
    edit = annotate_labels(path.read_bytes(), FAMILY_CONTEXT)
    path.write_bytes(edit.raw)
    assert read_labels(path.read_bytes()) == edit.labels
    assert edit.labels == edit.suggestions


def test_annotate_explicit_replacement_is_normalized() -> None:
    raw = b'---\nlabels: ["Old:tag"]\n---\nbody'
    edit = annotate_labels(raw, LabelContext("z/a.md"), labels=("New:x", "b:y"))
    assert edit.raw == b'---\nlabels: ["b:y", "new:x"]\n---\nbody'
    assert edit.labels == ("b:y", "new:x")


def test_annotate_explicit_empty_clears_to_list() -> None:
    raw = b'---\nlabels: ["a:x"]\n---\nbody'
    edit = annotate_labels(raw, LabelContext("z/a.md"), labels=())
    assert b'labels: []' in edit.raw and edit.labels == ()


@pytest.mark.parametrize("bad", ["project:x", [""], ["no-colon"]])
def test_annotate_rejects_malformed_explicit_labels(bad: object) -> None:
    with pytest.raises(LabelError):
        dynamic_annotate(b"---\n---\nbody", LabelContext("z/a.md"), labels=bad)


def test_annotate_ambiguous_header_is_retained_with_warning() -> None:
    raw = b"---\ntitle: a\ntitle: b\n---\nbody"
    edit = annotate_labels(raw, LabelContext("z/a.md"), labels=("x:y",))
    assert edit.raw == raw and edit.warning is not None and edit.labels == ()


def test_label_edit_fields_are_concrete() -> None:
    edit = annotate_labels(b"---\n---\n", LabelContext("z/a.md"))
    assert isinstance(edit.raw, bytes)
    assert isinstance(edit.labels, tuple)
    assert isinstance(edit.suggestions, tuple)
    assert edit.warning is None
