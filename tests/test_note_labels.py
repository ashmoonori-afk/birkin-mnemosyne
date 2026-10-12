"""Labels at the normal note write and read/search seams (plan todo 16).

``write_note`` gains ``labels: list[str] | None``: ``None`` keeps the
existing user-owned labels field verbatim (spelling, order and an explicit
``[]`` included) or infers deterministic suggestions when the field is
absent; an explicit list replaces (``[]`` clears).  Malformed explicit
values or malformed on-disk label metadata raise :class:`LabelError` before
any byte changes.  ``search`` forwards the AND filter to the engine and both
``search`` and ``list_notes`` expose the actual labels without changing
established titles or snippets.  Label values never feed tags, body or any
scoring text, and the inference path is provider- and network-free.
"""

from __future__ import annotations

from datetime import date

import pytest

from birkin_mnemosyne import frontmatter, memory
from birkin_mnemosyne.memory import VaultMemory, VersionMismatchError
from birkin_mnemosyne.label_values import LabelError
from birkin_mnemosyne.memory_index import MemoryIndex


def _mem(tmp_path) -> VaultMemory:
    return VaultMemory({"vault_path": str(tmp_path / "v")})


def _labels(m: VaultMemory, title: str) -> list[str] | None:
    text = m.get_note(title)
    assert text is not None
    return frontmatter.parse(text)[0].get("labels")


# -- write seam: inference ------------------------------------------------


def test_create_infers_deterministic_labels_from_completed_note(tmp_path, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return date(2026, 10, 11)

    monkeypatch.setattr(memory, "date", FixedDate)
    monkeypatch.setattr(memory, "_now_iso", lambda: "2026-10-11T12:00:00+00:00")
    m = _mem(tmp_path)
    m.write_note("FlowerPlus GTM", "Corporate welfare flowers plan.",
                 note_type="project", zone="projects")
    labels = _labels(m, "FlowerPlus GTM")
    assert labels is not None
    assert "type:project" in labels
    assert "project:FlowerPlus GTM" in labels
    assert "zone:projects" in labels
    assert any(label.startswith("date:") for label in labels)
    assert not any(label.startswith("lang:") for label in labels)
    m2 = VaultMemory({"vault_path": str(tmp_path / "w")})
    m2.write_note("FlowerPlus GTM", "Corporate welfare flowers plan.",
                  note_type="project", zone="projects")
    assert _labels(m2, "FlowerPlus GTM") == labels


def test_inference_uses_metadata_body_path_and_index_triggers(tmp_path):
    m = _mem(tmp_path)
    note = m.vault / "projects" / "apollo.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntitle: Apollo\ntype: topic\ncreated: 2026-01-02\n"
        "updated: 2026-01-02\nconfidence: 0.7\npolarity: positive\n"
        "version: 1\nsources: []\ntags: []\n---\n\n"
        "launch window 2026-03-05 mentions [[person:Mina]]\n",
        encoding="utf-8")
    MemoryIndex(m.vault).register("apollo-mission", "projects/apollo.md")
    m.write_note("Apollo", "updated launch details", append=True)
    labels = _labels(m, "Apollo")
    assert labels is not None
    assert "date:2026-01-02" in labels
    assert "date:2026-03-05" in labels
    assert "person:Mina" in labels
    assert "topic:apollo-mission" in labels
    assert "zone:projects" in labels


def test_language_suggestion_from_script_evidence(tmp_path):
    m = _mem(tmp_path)
    m.write_note("한글 메모", "한국어 메모 본문입니다", note_type="fact")
    labels = _labels(m, "한글 메모")
    assert labels is not None and "lang:ko" in labels


def test_label_values_survive_quotes_and_backslashes(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Quoted Labels", "body", labels=['topic:a"b', "zone:C\\D"])
    assert _labels(m, "Quoted Labels") == ['topic:a"b', "zone:C\\D"]
    m.write_note("Quoted Labels", "again", append=True)
    assert _labels(m, "Quoted Labels") == ['topic:a"b', "zone:C\\D"]


# -- write seam: preserve / replace ----------------------------------------


def test_omitted_labels_preserve_values_and_order(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Keep", "first", labels=["topic:seed", "zone:house"])
    m.write_note("Keep", "second", append=True)
    assert _labels(m, "Keep") == ["topic:seed", "zone:house"]


def test_explicit_empty_stays_empty_across_writes(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Cleared", "first", labels=["topic:x"])
    m.write_note("Cleared", "second", labels=[])
    assert _labels(m, "Cleared") == []
    m.write_note("Cleared", "third", append=True)
    assert _labels(m, "Cleared") == []


def test_manual_label_edits_are_preserved_verbatim(tmp_path):
    m = _mem(tmp_path)
    p = m.write_note("Manual", "first body", labels=["topic:seed"])
    p.write_text(
        "---\ntitle: Manual\ntype: topic\ncreated: 2026-01-02\n"
        "updated: 2026-01-03\nconfidence: 0.7\npolarity: positive\n"
        "version: 1\nsources: []\ntags: []\n"
        'labels: ["topic:beta", "ZONE:A", "Person:Beta"]\n'
        "---\n\nmanual body\n", encoding="utf-8")
    m.write_note("Manual", "second body", append=True)
    assert _labels(m, "Manual") == ["topic:beta", "ZONE:A", "Person:Beta"]


def test_explicit_replace_is_normalized(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Replaced", "first", labels=["ZONE:Beta", "topic:a", "topic:a"])
    assert _labels(m, "Replaced") == ["topic:a", "zone:Beta"]
    m.write_note("Replaced", "second", append=True, labels=["person:Ada"])
    assert _labels(m, "Replaced") == ["person:Ada"]


# -- malformed input: no file changes --------------------------------------


@pytest.mark.parametrize("bad", [["no-colon"], [""], ["topic:"],
                                 ["topic:has\nnewline"]])
def test_malformed_explicit_labels_leave_existing_note_untouched(tmp_path, bad):
    m = _mem(tmp_path)
    p = m.write_note("Guarded", "first", labels=["topic:ok"], source="s")
    before = p.read_bytes()
    with pytest.raises(LabelError):
        m.write_note("Guarded", "second", append=True, labels=bad)
    assert p.read_bytes() == before
    assert frontmatter.parse(p.read_text(encoding="utf-8"))[0]["version"] == 1


def test_malformed_explicit_labels_do_not_create_a_note(tmp_path):
    m = _mem(tmp_path)
    before = set(m.vault.rglob("*"))
    with pytest.raises(LabelError):
        m.write_note("Never", "body", labels=["broken"])
    assert set(m.vault.rglob("*")) == before


@pytest.mark.parametrize("line", ['labels: not-a-list', "labels: [broken]"])
def test_malformed_existing_label_metadata_rejected_before_rewrite(tmp_path,
                                                                   line):
    m = _mem(tmp_path)
    p = m.vault / "broken.md"
    p.write_text(
        "---\ntitle: Broken\ntype: topic\ncreated: 2026-01-02\n"
        "updated: 2026-01-03\nconfidence: 0.7\npolarity: positive\n"
        "version: 2\nsources: []\ntags: []\n" + line + "\n"
        "---\n\nbody\n", encoding="utf-8")
    before = p.read_bytes()
    with pytest.raises(LabelError):
        m.write_note("Broken", "changed", append=True)
    assert p.read_bytes() == before


# -- existing Memory-OS contracts stay intact ------------------------------


def test_version_evidence_ttl_and_tags_survive_labeled_writes(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Compat", "first", source="s1", tags=["t"],
                 labels=["topic:x"], ttl_days=30)
    meta1 = frontmatter.parse(m.get_note("Compat"))[0]
    assert meta1["version"] == 1 and meta1["labels"] == ["topic:x"]
    expiry = meta1["expires_at"]
    m.write_note("Compat", "second", append=True, source="s2",
                 expected_version=1)
    meta2 = frontmatter.parse(m.get_note("Compat"))[0]
    assert meta2["version"] == 2
    assert meta2["sources"] == ["s1", "s2"]
    assert meta2["expires_at"] == expiry
    assert meta2["tags"] == ["t"]
    assert meta2["labels"] == ["topic:x"]
    with pytest.raises(VersionMismatchError):
        m.write_note("Compat", "third", append=True, expected_version=99)


def test_evidence_gate_still_guards_labeled_writes(tmp_path):
    vault = tmp_path / "v"
    m = VaultMemory({"vault_path": str(vault), "evidence_required": True})
    m.write_note("Sourced", "body", labels=["topic:x"], source="manual")
    assert 'labels: ["topic:x"]' in m.get_note("Sourced")
    before = {path.relative_to(vault).as_posix(): path.read_bytes()
              for path in vault.rglob("*.md")}
    with pytest.raises(ValueError):
        m.write_note("Sourceless", "body", labels=["topic:y"])
    assert {path.relative_to(vault).as_posix(): path.read_bytes()
            for path in vault.rglob("*.md")} == before


def test_add_link_preserves_labels_tags_and_expiry(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Source", "body a", labels=["topic:keep"], tags=["t"],
                 ttl_days=30)
    m.write_note("Target", "body b")
    before = frontmatter.parse(m.get_note("Source"))[0]
    assert m.add_link("Source", "Target") is True
    after = frontmatter.parse(m.get_note("Source"))[0]
    assert after["labels"] == ["topic:keep"]
    assert after["tags"] == ["t"]
    assert after["expires_at"] == before["expires_at"]


# -- read/search seams -----------------------------------------------------


def test_list_notes_and_search_expose_actual_labels(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Alpha", "shared keyword", labels=["project:alpha", "lang:ko"])
    m.write_note("Beta", "shared keyword", labels=["project:alpha"])
    listed = {n["title"]: n["labels"] for n in m.list_notes()}
    assert listed["Alpha"] == ["lang:ko", "project:alpha"]
    assert listed["Beta"] == ["project:alpha"]
    hit = next(h for h in m.search("shared keyword") if h["title"] == "alpha")
    assert hit["labels"] == ["lang:ko", "project:alpha"]
    assert hit["title"] == "alpha" and "snippet" in hit


def test_search_labels_filter_is_and_and_public(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Both", "shared keyword", labels=["project:alpha", "lang:ko"])
    m.write_note("One", "shared keyword", labels=["project:alpha"])
    m.write_note("Other", "shared keyword", labels=["lang:ko"])
    by_project = {h["title"] for h in
                  m.search("shared keyword", labels=["project:alpha"])}
    by_lang = {h["title"] for h in
               m.search("shared keyword", labels=["lang:ko"])}
    by_both = [h["title"] for h in m.search(
        "shared keyword", labels=["project:alpha", "lang:ko"])]
    assert by_project == {"both", "one"}
    assert by_lang == {"both", "other"}
    assert by_both == ["both"]


def test_missing_and_empty_filters_preserve_results(tmp_path):
    m = _mem(tmp_path)
    m.write_note("A", "shared keyword", labels=["project:x"])
    m.write_note("B", "shared keyword", labels=["project:y"])
    base = m.search("shared keyword")
    assert {h["title"] for h in base} == {"a", "b"}
    assert m.search("shared keyword", labels=None) == base
    assert m.search("shared keyword", labels=[]) == base


def test_labels_never_feed_tags_body_or_scoring_text(tmp_path):
    m = _mem(tmp_path)
    m.write_note("Scored", "plain body", labels=["project:needle"])
    text = m.get_note("Scored")
    assert text is not None
    meta, body = frontmatter.parse(text)
    assert meta["tags"] == []
    assert body.strip() == "plain body"
    assert m.search("needle") == []
    entry = m.dex.note_meta("scored")
    assert entry is not None and "needle" not in entry["terms"]
