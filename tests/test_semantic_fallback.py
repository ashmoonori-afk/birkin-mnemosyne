"""BM25-only fallback of the optional semantic leg: runs without numpy,
safetensors or huggingface_hub installed (the core, zero-dependency CI job)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from birkin_mnemosyne import mnemosyne, semantic


def _note(vault: Path, slug: str, title: str, body: str) -> None:
    (vault / f"{slug}.md").write_text(f"---\ntitle: {title}\n---\n\n{body}\n",
                                      encoding="utf-8")


def _vault(tmp_path: Path) -> Path:
    _note(tmp_path, "car", "garage", "the car needs new brake pads")
    _note(tmp_path, "dog", "pets", "walk the dog every morning")
    _note(tmp_path, "tax", "paperwork", "file the tax form by may")
    return tmp_path


def test_semantic_false_is_plain_bm25(tmp_path):
    vault = _vault(tmp_path)
    assert mnemosyne.Mnemosyne(vault, semantic=False).search("vehicle") == []
    assert [h["slug"] for h in mnemosyne.Mnemosyne(vault, semantic=False)
            .search("brake pads")] == ["car"]


def test_missing_extra_falls_back_to_bm25(tmp_path, monkeypatch, caplog):
    vault = _vault(tmp_path)
    monkeypatch.setattr(semantic, "available", lambda: False)
    with caplog.at_level(logging.WARNING):
        hits = mnemosyne.Mnemosyne(vault, semantic=True).search("brake pads")
    assert [h["slug"] for h in hits] == ["car"]
    assert "not installed" in caplog.text
    assert not (vault / semantic.VECTORS_FILE).exists()


def test_env_opt_out_wins_over_installed_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "available", lambda: True)
    monkeypatch.setenv("MNEMOSYNE_SEMANTIC", "0")
    dex = mnemosyne.Mnemosyne(_vault(tmp_path))
    assert dex._semantic_index() is None


def test_semantic_mode_is_opt_in(tmp_path, monkeypatch):
    # installed extra, nothing asked for: the default stays the core ranking
    monkeypatch.setattr(semantic, "available", lambda: True)
    monkeypatch.delenv("MNEMOSYNE_SEMANTIC", raising=False)
    assert mnemosyne.Mnemosyne(_vault(tmp_path))._semantic_index() is None


def test_rrf_sums_reciprocal_ranks():
    fused = mnemosyne._rrf([[("a", 2.0), ("b", 1.0)], [("b", 0.9), ("c", 0.5)]], k=10)
    assert fused["b"] == pytest.approx(1 / 12 + 1 / 11)
    assert fused["a"] == pytest.approx(1 / 11)
    assert max(fused, key=fused.get) == "b"


def test_rrf_equal_scores_share_a_rank():
    fused = mnemosyne._rrf([[("a", 1.0), ("b", 1.0), ("c", 0.5)]], k=10)
    assert fused["a"] == fused["b"] == pytest.approx(1 / 11)
    assert fused["c"] == pytest.approx(1 / 13)


def test_rrf_weights_scale_a_lists_vote():
    fused = mnemosyne._rrf([[("a", 2.0)], [("b", 1.0)]], k=5, weights=[1.0, 0.4])
    assert fused["a"] == pytest.approx(1 / 6)
    assert fused["b"] == pytest.approx(0.4 / 6)


def test_mostly_cjk_counts_han_and_kana_letters_only():
    assert mnemosyne._mostly_cjk("車検の期限はいつ")
    assert mnemosyne._mostly_cjk("回滚 規定")
    assert not mnemosyne._mostly_cjk("rollback error rate 值班")
    assert not mnemosyne._mostly_cjk("tax deadline 2024")
    assert not mnemosyne._mostly_cjk("2024")


def test_full_lexical_match_keeps_first_place_under_fusion(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "available", lambda: False)
    _note(tmp_path, "full", "garage", "brake pads")
    _note(tmp_path, "half", "garage two", "brake fluid and brake lines")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    # "half" is second in the lexical leg and first in the semantic one: its
    # two votes beat the single vote of "full", which alone holds both words.
    monkeypatch.setattr(dex, "_semantic_ranking", lambda query: [("half", 0.9)])
    fused = mnemosyne._rrf([[("full", 2.0), ("half", 1.0)], [("half", 0.9)]],
                           weights=[1.0, mnemosyne.SEM_WEIGHT])
    assert fused["half"] > fused["full"]
    assert [h["slug"] for h in dex.search("brake pads")] == ["full", "half"]


@pytest.mark.parametrize("old, new", [("a", "b"), ("b", "a")])
def test_equal_full_matches_keep_the_core_order_newer_first(tmp_path, monkeypatch, old, new):
    # either scan order: the date decides, not the position in the index
    monkeypatch.setattr(semantic, "available", lambda: False)
    for slug, day in ((old, "2026-01-01"), (new, "2026-02-01")):
        (tmp_path / f"{slug}.md").write_text(
            f"---\ntitle: garage\nupdated: {day}\n---\n\nbrake pads\n", encoding="utf-8")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    core = [h["slug"] for h in dex.search("brake pads")]
    assert core == [new, old]
    monkeypatch.setattr(dex, "_semantic_ranking", lambda query: [(old, 0.9)])
    assert [h["slug"] for h in dex.search("brake pads")] == core


def test_a_lone_han_character_is_an_original_query_unit(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "available", lambda: False)
    _note(tmp_path, "short", "garage", "車")
    _note(tmp_path, "long", "garage", "車 and a list of other things to check later")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    core = [h["slug"] for h in dex.search("車")]
    assert core == ["short", "long"]
    # two votes for "long" would win the fusion; both notes hold the whole query
    monkeypatch.setattr(dex, "_semantic_ranking", lambda query: [("long", 0.9)])
    assert [h["slug"] for h in dex.search("車")] == core


def test_a_note_missing_the_lone_han_character_is_not_a_full_match(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "available", lambda: False)
    _note(tmp_path, "both", "garage", "車 brake")
    _note(tmp_path, "latin", "garage", "brake brake lines")
    _note(tmp_path, "han", "garage", "車 and a list of other things to check later")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    core = [h["slug"] for h in dex.search("車 brake")]
    assert core == ["both", "latin", "han"]
    # only "both" holds the whole query; the other two are ordered by fusion
    monkeypatch.setattr(dex, "_semantic_ranking", lambda query: [("han", 0.9)])
    assert [h["slug"] for h in dex.search("車 brake")] == ["both", "han", "latin"]


def test_usage_boost_ranks_the_lexical_leg_not_the_fused_score(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "available", lambda: False)
    _note(tmp_path, "used", "notes", "brake service log")
    _note(tmp_path, "fresh", "notes", "brake service log")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    for _ in range(3):
        dex.record_access("used")
    monkeypatch.setattr(dex, "_semantic_ranking", lambda query: [("fresh", 0.9)])
    hits = dex.search("brake repair")
    # lexical leg: used first (boosted), fresh second; semantic leg: fresh only
    assert [h["slug"] for h in hits] == ["fresh", "used"]
    assert hits[1]["score"] == pytest.approx(1 / (mnemosyne.RRF_K + 1))


def test_chunk_text_splits_on_paragraphs_and_repeats_title():
    body = "\n\n".join(["x" * 150] * 4)
    chunks = semantic.chunk_text("T", body, max_chars=320)
    assert len(chunks) == 2
    assert all(c.startswith("T\n") for c in chunks)
    assert semantic.chunk_text("T", "") == ["T"]


def test_chunk_text_cuts_a_paragraph_longer_than_a_chunk():
    chunks = semantic.chunk_text("T", "x" * 1000, max_chars=400)
    assert [len(c) for c in chunks] == [402, 402, 202]
