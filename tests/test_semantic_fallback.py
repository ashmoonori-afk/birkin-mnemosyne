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


def test_rrf_sums_reciprocal_ranks():
    fused = mnemosyne._rrf([[("a", 2.0), ("b", 1.0)], [("b", 0.9), ("c", 0.5)]], k=10)
    assert fused["b"] == pytest.approx(1 / 12 + 1 / 11)
    assert fused["a"] == pytest.approx(1 / 11)
    assert max(fused, key=fused.get) == "b"


def test_rrf_equal_scores_share_a_rank():
    fused = mnemosyne._rrf([[("a", 1.0), ("b", 1.0), ("c", 0.5)]], k=10)
    assert fused["a"] == fused["b"] == pytest.approx(1 / 11)
    assert fused["c"] == pytest.approx(1 / 13)


def test_chunk_text_splits_on_paragraphs_and_repeats_title():
    body = "\n\n".join(["x" * 150] * 4)
    chunks = semantic.chunk_text("T", body, max_chars=320)
    assert len(chunks) == 2
    assert all(c.startswith("T\n") for c in chunks)
    assert semantic.chunk_text("T", "") == ["T"]
