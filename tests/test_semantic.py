"""Optional semantic leg (``[semantic]`` extra) and its BM25-only fallback.

The real model (a 512 MB download) is never loaded here: a deterministic
"concept" encoder stands in, so fusion, persistence and load failures are
tested wherever numpy is installed (fallback-only tests live in
test_semantic_fallback.py and need nothing).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from birkin_mnemosyne import mnemosyne, semantic

CONCEPTS = [("car", "vehicle", "auto", "자동차"), ("dog", "puppy", "hound", "강아지"),
            ("tax", "levy", "duty", "세금")]


def _note(vault: Path, slug: str, title: str, body: str) -> None:
    (vault / f"{slug}.md").write_text(f"---\ntitle: {title}\n---\n\n{body}\n",
                                      encoding="utf-8")


def _vault(tmp_path: Path) -> Path:
    _note(tmp_path, "car", "garage", "the car needs new brake pads")
    _note(tmp_path, "dog", "pets", "walk the dog every morning")
    _note(tmp_path, "tax", "paperwork", "file the tax form by may")
    return tmp_path


np = pytest.importorskip("numpy")


class ConceptEncoder:
    """Bag-of-concepts vectors: synonyms share one dimension (+ a hashed
    word dimension so unrelated words are not all zero)."""

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        out = np.full((len(texts), semantic.DIM), -0.01, dtype=np.float32)
        for i, text in enumerate(texts):
            for word in text.lower().split():
                for d, group in enumerate(CONCEPTS):
                    if word.strip(".,?") in group:
                        out[i, d] = 1.0
        return out


@pytest.fixture
def concept_model(monkeypatch):
    enc = ConceptEncoder()
    monkeypatch.setattr(semantic, "available", lambda: True)
    monkeypatch.setattr(semantic.SemanticIndex, "_encoder", lambda self: enc)
    return enc


def test_semantic_leg_finds_synonym_bm25_misses(tmp_path, concept_model):
    vault = _vault(tmp_path)
    assert mnemosyne.Mnemosyne(vault, semantic=False).search("vehicle") == []
    hits = mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    assert hits[0]["slug"] == "car"


def test_env_switch_turns_the_mode_on(tmp_path, concept_model, monkeypatch):
    monkeypatch.setenv("MNEMOSYNE_SEMANTIC", "1")
    hits = mnemosyne.Mnemosyne(_vault(tmp_path)).search("vehicle")
    assert hits[0]["slug"] == "car"


def test_cross_language_query_reaches_english_note(tmp_path, concept_model):
    hits = mnemosyne.Mnemosyne(_vault(tmp_path), semantic=True).search("강아지 산책")
    assert hits[0]["slug"] == "dog"


def test_vectors_persist_and_only_changed_notes_reembed(tmp_path, concept_model):
    vault = _vault(tmp_path)
    mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    assert (vault / semantic.VECTORS_FILE).exists()
    calls = concept_model.calls
    dex = mnemosyne.Mnemosyne(vault, semantic=True)
    dex.search("vehicle")
    assert concept_model.calls == calls + 1                 # query only
    _note(vault, "dog", "pets", "the puppy sleeps all afternoon, a long body text")
    dex.search("hound")
    assert concept_model.calls == calls + 3                 # one note + query
    (vault / "tax.md").unlink()
    assert "tax" not in [h["slug"] for h in dex.search("levy")]


def test_stale_sidecar_from_other_model_is_rebuilt(tmp_path, concept_model):
    vault = _vault(tmp_path)
    mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    idx = semantic.SemanticIndex(vault, model_name="other/model")
    idx.sync(mnemosyne.Mnemosyne(vault, semantic=False).entries())
    assert idx.search("vehicle", 1)[0][0] == "car"


def test_unprepared_model_falls_back_to_bm25(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(semantic, "available", lambda: True)
    monkeypatch.setenv("MNEMOSYNE_MODEL_CACHE", str(tmp_path / "cache"))
    dex = mnemosyne.Mnemosyne(_vault(tmp_path), semantic=True)
    with caplog.at_level(logging.WARNING):
        hits = dex.search("brake pads")
    assert [h["slug"] for h in hits] == ["car"]
    assert "not prepared" in caplog.text


def test_model_is_prepared_explicitly_and_only_once(tmp_path, monkeypatch):
    hub = pytest.importorskip("huggingface_hub")
    st = pytest.importorskip("safetensors.numpy")
    snap = tmp_path / "snap"
    snap.mkdir()
    vocab = [["[PAD]", -20.0], ["[UNK]", -20.0], ["\u2581car", -1.0], ["\u2581", -3.0]]
    (snap / "tokenizer.json").write_text(
        json.dumps({"model": {"type": "Unigram", "unk_id": 1, "vocab": vocab}}),
        encoding="utf-8")
    st.save_file({"embeddings": np.eye(4, semantic.DIM, dtype=np.float32)},
                 str(snap / "model.safetensors"))
    calls = []

    def fake_snapshot(repo_id, **kwargs):
        calls.append(kwargs)
        return str(snap)

    monkeypatch.setattr(hub, "snapshot_download", fake_snapshot)
    monkeypatch.setenv("MNEMOSYNE_MODEL_CACHE", str(tmp_path / "cache"))
    with pytest.raises(RuntimeError, match="not prepared"):
        semantic.SemanticIndex(tmp_path)._encoder()
    assert calls == []                                  # a search never downloads
    assert semantic.prepare() == semantic.prepare()
    assert len(calls) == 1
    assert not any("onnx" in p for p in calls[0]["allow_patterns"])
    assert semantic.SemanticIndex(tmp_path)._encoder().tokenize("car") == [2]


def test_model_failure_falls_back_to_bm25_with_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(semantic, "available", lambda: True)

    def boom(self):
        raise OSError("offline")

    monkeypatch.setattr(semantic.SemanticIndex, "_encoder", boom)
    dex = mnemosyne.Mnemosyne(_vault(tmp_path), semantic=True)
    with caplog.at_level(logging.WARNING):
        hits = dex.search("brake pads")
    assert [h["slug"] for h in hits] == ["car"]
    assert "offline" in caplog.text
    assert dex._semantic_index() is None


def test_fused_ties_go_to_the_bm25_pick(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "available", lambda: False)
    _note(tmp_path, "car", "garage", "brake pads")
    (tmp_path / "dog.md").write_text(
        "---\ntitle: pets\nupdated: 2099-01-01\n---\n\nwalk the dog\n",
        encoding="utf-8")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    # car is first in the BM25 leg only, dog first in the semantic leg only:
    # equal fused scores, and dog is newer, so only the BM25 tie-break keeps car.
    monkeypatch.setattr(dex, "_semantic_ranking", lambda query: [("dog", 0.9)])
    assert [h["slug"] for h in dex.search("brake")] == ["car", "dog"]


def test_hybrid_keeps_warm_twin_above_cold_twin(tmp_path, concept_model):
    for name in ("warm", "cold"):
        _note(tmp_path, name, "car notes", "the car needs new brake pads")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=True)
    for _ in range(3):
        dex.record_access("warm")
    assert [h["slug"] for h in dex.search("vehicle brake")][:2] == ["warm", "cold"]
