"""Optional semantic leg (``[semantic]`` extra) and its BM25-only fallback.

The real model (a 512 MB download) is never loaded here: a deterministic
"concept" encoder stands in, so fusion, persistence and load failures are
tested wherever numpy is installed (fallback-only tests live in
test_semantic_fallback.py and need nothing).
"""

from __future__ import annotations

import json
import logging
import sys
import types
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
    calls = concept_model.calls
    idx = semantic.SemanticIndex(vault, model_name="other/model")
    idx.sync(mnemosyne.Mnemosyne(vault, semantic=False).entries())
    assert concept_model.calls == calls + 1          # re-embedded, not reused
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


def test_prepare_pins_the_default_revision_and_records_it(tmp_path, monkeypatch):
    seen = []
    hub = types.ModuleType("huggingface_hub")

    def fake_snapshot(repo_id, **kwargs):
        seen.append((repo_id, kwargs))
        return str(tmp_path / "snap")

    def fake_convert(snapshot, out):
        out.mkdir(parents=True, exist_ok=True)
        (out / "meta.json").write_text("{}", encoding="utf-8")

    hub.snapshot_download = fake_snapshot
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)   # never downloads
    monkeypatch.setattr("birkin_mnemosyne.static_model.prepare_isolated", fake_convert)
    monkeypatch.setenv("MNEMOSYNE_MODEL_CACHE", str(tmp_path / "cache"))
    semantic.prepare()
    assert seen[-1][0] == semantic.MODEL_NAME
    assert seen[-1][1]["revision"] == semantic.MODEL_REVISION
    assert semantic.prepared_revision() == semantic.MODEL_REVISION
    semantic.prepare()
    assert len(seen) == 1                                   # prepared once, not again
    semantic.prepare("someone/else")                        # no pin known: unchanged
    assert seen[-1][1]["revision"] is None
    semantic.prepare("someone/else", revision="c" * 40)     # explicit pin wins
    assert seen[-1][1]["revision"] == "c" * 40
    assert semantic.prepared_revision("someone/else") == "c" * 40
    semantic.prepare("someone/else", revision="c" * 40)
    assert len(seen) == 3


def test_default_model_revision_is_a_full_commit_sha():
    assert len(semantic.MODEL_REVISION) == 40
    assert set(semantic.MODEL_REVISION) <= set("0123456789abcdef")


def _set_prepared_revision(tmp_path, monkeypatch, revision):
    monkeypatch.setenv("MNEMOSYNE_MODEL_CACHE", str(tmp_path / "cache"))
    out = semantic.model_dir()
    out.mkdir(parents=True, exist_ok=True)
    meta = {} if revision is None else {"revision": revision}
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


@pytest.mark.parametrize("built_with", [None, "a" * 40], ids=["no-revision", "other-revision"])
def test_vectors_from_another_model_revision_are_reembedded(
        tmp_path, concept_model, monkeypatch, built_with):
    (tmp_path / "vault").mkdir()
    vault = _vault(tmp_path / "vault")
    _set_prepared_revision(tmp_path, monkeypatch, built_with)
    mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    calls = concept_model.calls
    mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    assert concept_model.calls == calls + 1                 # same revision: reused
    _set_prepared_revision(tmp_path, monkeypatch, "b" * 40)
    hits = mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    assert concept_model.calls == calls + 3                 # rebuilt (not an error) + query
    assert hits[0]["slug"] == "car"
    with np.load(vault / semantic.VECTORS_FILE) as data:
        assert json.loads(str(data["meta"]))["revision"] == "b" * 40


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
    # car is first in the BM25 leg only, dog first in the semantic leg only.
    # With equal votes both score 1/(k+1), and "zebra" keeps car out of the
    # full-match tier; dog is newer, so only the BM25 tie-break keeps car.
    monkeypatch.setattr(mnemosyne, "SEM_WEIGHT", 1.0)
    monkeypatch.setattr(dex, "_semantic_ranking", lambda query: [("dog", 0.9)])
    hits = dex.search("brake zebra")
    assert hits[0]["score"] == hits[1]["score"]
    assert [h["slug"] for h in hits] == ["car", "dog"]


@pytest.mark.parametrize("junk", [b"", b"PK\x03\x04 truncated archive"])
def test_corrupt_vector_sidecar_is_rebuilt(tmp_path, concept_model, junk):
    vault = _vault(tmp_path)
    (vault / semantic.VECTORS_FILE).write_bytes(junk)
    hits = mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    assert hits[0]["slug"] == "car"
    with np.load(vault / semantic.VECTORS_FILE) as data:
        assert len(data["slugs"]) == 3


def test_inconsistent_vector_sidecar_is_rebuilt(tmp_path, concept_model):
    vault = _vault(tmp_path)
    meta = semantic.SemanticIndex(vault)._meta()
    # Fingerprints are the real ones, so sync() would trust this cache; its
    # counts claim five chunk rows where the file holds three.
    entries = mnemosyne.Mnemosyne(vault, semantic=False).entries()
    slugs = sorted(entries)
    np.savez(vault / semantic.VECTORS_FILE, meta=np.array(json.dumps(meta)),
             slugs=np.array(slugs), counts=np.array([3, 1, 1], dtype=np.int32),
             fps=np.array([(entries[s]["mtime"], entries[s]["size"]) for s in slugs]),
             bits=np.zeros((3, semantic.DIM // 8), dtype=np.uint8))
    hits = mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    assert hits[0]["slug"] == "car"
    with np.load(vault / semantic.VECTORS_FILE) as data:
        assert data["counts"].tolist() == [1, 1, 1]


@pytest.mark.parametrize("wrong", [
    {"counts": np.array([1.0, 1.0, 1.0])},
    {"bits": np.zeros((3, semantic.DIM // 8), dtype=np.float32)},
    {"bits": np.array(0, dtype=np.uint8)},
    {"fps": np.full((3, 2), np.nan)},
], ids=["float-counts", "float-bits", "scalar-bits", "nan-fingerprints"])
def test_vector_sidecar_with_wrong_types_is_rebuilt(tmp_path, concept_model, wrong):
    vault = _vault(tmp_path)
    meta = semantic.SemanticIndex(vault)._meta()
    entries = mnemosyne.Mnemosyne(vault, semantic=False).entries()
    slugs = sorted(entries)
    # a cache that sync() would trust (real fingerprints, matching totals)
    # except for one array of the wrong type or shape
    arrays = {"meta": np.array(json.dumps(meta)), "slugs": np.array(slugs),
              "counts": np.array([1, 1, 1], dtype=np.int32),
              "fps": np.array([(entries[s]["mtime"], entries[s]["size"]) for s in slugs]),
              "bits": np.zeros((3, semantic.DIM // 8), dtype=np.uint8)}
    np.savez(vault / semantic.VECTORS_FILE, **{**arrays, **wrong})
    hits = mnemosyne.Mnemosyne(vault, semantic=True).search("vehicle")
    assert hits[0]["slug"] == "car"
    with np.load(vault / semantic.VECTORS_FILE) as data:
        assert data["counts"].tolist() == [1, 1, 1]
        assert data["bits"].dtype == np.uint8 and data["bits"].any()


def test_packed_scoring_equals_the_sign_dot_product_of_the_best_chunk(tmp_path, concept_model):
    filler = "lorem " * 60
    _note(tmp_path, "long", "notes", f"{filler}\n\n{filler} the car is here")
    _note(tmp_path, "dog", "pets", "walk the dog every morning")
    idx = semantic.SemanticIndex(tmp_path)
    idx.sync(mnemosyne.Mnemosyne(tmp_path, semantic=False).entries())
    assert len(idx._chunks["long"]) == 2          # the match is in the second chunk
    q = concept_model.encode(["vehicle"])[0]
    q = q / np.linalg.norm(q)
    expected = {slug: max(float((np.unpackbits(row, count=semantic.DIM)
                                 .astype(np.float32) * 2 - 1) @ q) for row in rows)
                for slug, rows in idx._chunks.items()}
    found = idx.search("vehicle", 10)
    assert dict(found) == pytest.approx(expected, abs=1e-5)
    assert found[0][0] == "long"


def test_hybrid_keeps_warm_twin_above_cold_twin(tmp_path, concept_model):
    for name in ("warm", "cold"):
        _note(tmp_path, name, "car notes", "the car needs new brake pads")
    dex = mnemosyne.Mnemosyne(tmp_path, semantic=True)
    for _ in range(3):
        dex.record_access("warm")
    assert [h["slug"] for h in dex.search("vehicle brake")][:2] == ["warm", "cold"]
