"""Opt-in experiment contracts exercised through real vaults and search."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest

from birkin_mnemosyne import mnemosyne

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def note(vault: Path, slug: str, title: str, body: str,
         tags: str = "") -> Path:
    path = vault / f"{slug}.md"
    _ = path.write_text(
        f"---\ntitle: {title}\ntags: [{tags}]\ncreated: 2026-01-01\n"
        f"updated: 2026-01-01\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_field_weight_rewards_title_and_tags_without_changing_length(tmp_path: Path) -> None:
    # Given: equal aggregate token frequencies in different fields.
    note(tmp_path, "body", "memo", "orchard memo")
    note(tmp_path, "title", "orchard", "memo memo")
    note(tmp_path, "tags", "memo", "memo", "orchard")
    plain = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    base = plain.search("orchard", now=NOW)
    # When: title and tag frequencies are weighted.
    weighted = mnemosyne.Mnemosyne(
        tmp_path, semantic=False, field_aware=True, title_weight=2, tag_weight=1.5)
    hits = weighted.search("orchard", now=NOW)
    # Then: field evidence increases saturation score, not document length.
    assert [h["slug"] for h in hits] == ["title", "tags", "body"]
    assert len({h["score"] for h in base}) == 1
    assert {s: e["doclen"] for s, e in weighted.entries().items()} == {
        s: e["doclen"] for s, e in plain.entries().items()}


@pytest.mark.parametrize("query", ["김장 배추", "豚骨スープ", "搬家准备", "orchard deployment"])
def test_unit_field_weights_have_exact_score_parity(tmp_path: Path, query: str) -> None:
    # Given: multilingual fields with repeats and script transitions.
    note(tmp_path, "a", "김장 豚骨スープ", "배추 搬家准备 orchard deployment", "김장, orchard")
    note(tmp_path, "b", "orchard", "deployment 배추 배추 豚骨スープ")
    plain = mnemosyne.Mnemosyne(tmp_path, semantic=False).search(query, now=NOW)
    # When: separate frequencies all receive unit weights.
    unit = mnemosyne.Mnemosyne(
        tmp_path, semantic=False, field_aware=True, title_weight=1, tag_weight=1)
    # Then: serialized hits are exactly identical, including scores.
    assert json.dumps(unit.search(query, now=NOW)) == json.dumps(plain)


def test_field_cache_is_backfilled_and_default_entries_remain_original(tmp_path: Path) -> None:
    # Given: a legacy cache created by the default parser.
    note(tmp_path, "a", "orchard", "deployment", "project")
    original = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    original.rebuild()
    original_entries = original.entries()
    # When: opt-in scoring loads the old cache and then is disabled.
    enabled = mnemosyne.Mnemosyne(tmp_path, semantic=False, field_aware=True)
    enabled.search("orchard", now=NOW)
    disabled = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    # Then: fields are populated only for the opt-in engine.
    assert enabled.entries()["a"]["field_terms"]["title"] == {"orchard": 1, "orcha~": 1}
    assert disabled.entries() == original_entries


@pytest.mark.parametrize("weight", [0, -1, float("inf"), float("nan")])
def test_invalid_field_weights_are_rejected_at_constructor(tmp_path: Path, weight: float) -> None:
    # Given/When: an invalid public configuration.
    with pytest.raises(ValueError, match="finite and positive"):
        mnemosyne.Mnemosyne(tmp_path, field_aware=True, title_weight=weight)


def test_diversity_selects_complementary_evidence_and_keeps_duplicates(tmp_path: Path) -> None:
    # Given: repeated first fact scores above the complementary second fact.
    for i in range(6):
        _ = note(tmp_path, f"alpha-{i}", "alpha",
                 "orchard orchard orchard orchard rollback configuration checklist")
    _ = note(tmp_path, "beta", "beta", "retention policy " + "other " * 20)
    for i in range(20):
        _ = note(tmp_path, f"noise-{i}", "misc", "retention " + "filler " * 100)
    plain = mnemosyne.Mnemosyne(tmp_path, semantic=False).search(
        "orchard retention", limit=32, now=NOW)
    assert "beta" not in [h["slug"] for h in plain[:2]]
    # When: diversity selects from the same scored pool.
    eng = mnemosyne.Mnemosyne(tmp_path, semantic=False, evidence_diversity=True)
    hits = eng.search("orchard retention", limit=32, now=NOW)
    # Then: both facts fit top two and every duplicate remains available.
    assert "beta" in [h["slug"] for h in hits[:2]]
    assert {h["slug"] for h in hits} == {h["slug"] for h in plain}
    assert len(hits) == len(plain)
    assert sum(h.get("diversity_deferred") == "near_duplicate"
               for h in hits if h["slug"].startswith("alpha-")) == 5
    assert {h["slug"]: h["score"] for h in hits} == {
        h["slug"]: h["score"] for h in plain}


def test_diversity_protects_complete_matches_even_if_redundant(tmp_path: Path) -> None:
    # Given: two complete matches and a partial corroborating note.
    for name in ("one", "two"):
        _ = note(tmp_path, name, "orchard retention", "same fact same wording")
    _ = note(tmp_path, "partial", "orchard", "orchard orchard orchard")
    plain = mnemosyne.Mnemosyne(tmp_path, semantic=False).search(
        "orchard retention", now=NOW)
    full = [h for h in plain if h["slug"] in {"one", "two"}]
    # When: duplicate deferral is enabled.
    hits = mnemosyne.Mnemosyne(
        tmp_path, semantic=False, evidence_diversity=True).search(
            "orchard retention", now=NOW)
    # Then: exact matches preserve scored order and unmodified hit dictionaries.
    assert hits[:2] == full
    assert {h["slug"] for h in hits} == {"one", "two", "partial"}


@pytest.mark.parametrize("query", ["", "notfound", "車", "배추"])
def test_diversity_handles_empty_unknown_and_single_script_queries(tmp_path: Path, query: str) -> None:
    # Given: one note, including a lone CJK query unit.
    _ = note(tmp_path, "one", "車", "배추")
    plain = mnemosyne.Mnemosyne(tmp_path, semantic=False).search(query, now=NOW)
    # When/Then: no extra candidate changes a one-note or empty result.
    assert mnemosyne.Mnemosyne(
        tmp_path, semantic=False, evidence_diversity=True).search(query, now=NOW) == plain


def assert_length_parity(eng: mnemosyne.Mnemosyne, vault: Path) -> None:
    """Compare persisted public searches and cached accounting, exactly."""
    entries = eng.entries()
    total = sum(e["doclen"] for e in entries.values())
    assert eng._total_doclen == total
    assert eng._doc_count == len(entries)
    assert eng._avgdl == (total / len(entries) if entries else 0.0)
    baseline = mnemosyne.Mnemosyne(vault, semantic=False)
    for query in ("김장 배추", "豚骨スープ", "搬家准备", "orchard retention"):
        assert json.dumps(eng.search(query, now=NOW)) == json.dumps(
            baseline.search(query, now=NOW))


@pytest.mark.parametrize("operation", ["insert", "edit", "delete", "rezone", "reload", "rebuild"])
def test_incremental_lengths_preserve_scores_after_mutation(
        tmp_path: Path,
        operation: Literal["insert", "edit", "delete", "rezone", "reload", "rebuild"]) -> None:
    # Given: mixed-script note lengths, including excluded Han/kana unigrams.
    path = note(tmp_path, "a", "김장", "배추 豚骨スープ orchard", "搬家准备")
    _ = note(tmp_path, "b", "orchard", "retention")
    eng = mnemosyne.Mnemosyne(tmp_path, semantic=False, incremental_doclen=True)
    _ = eng.rebuild()
    # When: each public index mutation or reconstruction runs.
    match operation:
        case "insert":
            new = note(tmp_path, "c", "搬家准备", "豚骨スープ retention " * 5)
            eng.note_written(new)
        case "edit":
            _ = note(tmp_path, "a", "김장", "배추 " * 30)
            eng.note_written(path)
        case "delete":
            path.unlink()
            eng.refresh()
        case "rezone":
            _ = eng.rezone("a", "food")
        case "reload":
            eng = mnemosyne.Mnemosyne(tmp_path, semantic=False, incremental_doclen=True)
        case "rebuild":
            _ = eng.rebuild()
        case unreachable:
            raise AssertionError(unreachable)
    # Then: every score and the total/count/average equal full recomputation.
    assert_length_parity(eng, tmp_path)


def test_incremental_failed_parse_does_not_change_totals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: an indexed note and a parser failure after an edit.
    path = note(tmp_path, "a", "김장", "배추")
    eng = mnemosyne.Mnemosyne(tmp_path, incremental_doclen=True)
    _ = eng.rebuild()
    before = (eng._total_doclen, eng._doc_count, eng._avgdl, eng.entries())
    _ = note(tmp_path, "a", "김장", "배추 " * 10)
    monkeypatch.setattr(mnemosyne, "_note_entry", lambda path, rel: None)
    # When: the targeted parser cannot produce an entry.
    eng.note_written(path)
    # Then: accounting and the previous entry are unchanged.
    assert (eng._total_doclen, eng._doc_count, eng._avgdl, eng.entries()) == before


def test_incremental_empty_vault_reset_and_reload(tmp_path: Path) -> None:
    # Given: a previously nonempty cache.
    path = note(tmp_path, "a", "車", "車")
    eng = mnemosyne.Mnemosyne(tmp_path, incremental_doclen=True)
    _ = eng.rebuild()
    path.unlink()
    # When: the last note is removed and the cache is reconstructed.
    _ = eng.rebuild()
    # Then: zero totals and an empty search survive reload.
    assert_length_parity(eng, tmp_path)
    reloaded = mnemosyne.Mnemosyne(tmp_path, incremental_doclen=True)
    assert_length_parity(reloaded, tmp_path)


def test_incremental_targeted_write_never_recomputes_all_lengths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: loaded totals and a guard against accidentally retaining the full pass.
    path = note(tmp_path, "a", "orchard", "orchard")
    eng = mnemosyne.Mnemosyne(tmp_path, incremental_doclen=True)
    _ = eng.rebuild()

    def forbidden() -> None:
        raise AssertionError("targeted opt-in mutation recomputed all lengths")

    monkeypatch.setattr(eng, "_recompute_avgdl", forbidden)
    _ = note(tmp_path, "a", "orchard", "orchard retention " * 5)
    # When: an edit updates the real index and full persisted cache.
    eng.note_written(path)
    # Then: the new average and search are correct without the guarded pass.
    assert eng._doc_count == 1
    assert eng._notes is not None
    assert eng._total_doclen == eng._notes["a"]["doclen"]
    assert eng.search("retention", now=NOW)[0]["slug"] == "a"
