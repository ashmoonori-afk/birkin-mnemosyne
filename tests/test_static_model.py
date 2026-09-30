from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
st = pytest.importorskip("safetensors.numpy")

from birkin_mnemosyne import static_model  # noqa: E402

VOCAB = [["[PAD]", -20.0], ["[UNK]", -20.0], ["\u2581", -3.0], ["\u2581ab", -1.0],
         ["\u2581a", -2.0], ["b", -2.5], ["c", -2.0], [",", -1.5], ["\u2581,", -1.2],
         ["\u2581c", -1.8], ["\u2581김치", -1.0], ["\u2581김", -2.0], ["치", -2.0]]


def _snapshot(tmp_path: Path, dim: int = 4) -> tuple[Path, Any]:
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "tokenizer.json").write_text(json.dumps(
        {"model": {"type": "Unigram", "unk_id": 1, "vocab": VOCAB}}), encoding="utf-8")
    emb = np.random.default_rng(0).normal(size=(len(VOCAB), dim)).astype(np.float32)
    st.save_file({"embeddings": emb}, str(snap / "model.safetensors"))
    return snap, emb


def _prepared(tmp_path: Path) -> tuple[static_model.StaticModel, Any]:
    snap, emb = _snapshot(tmp_path)
    out = tmp_path / "prepared"
    static_model.prepare(snap, out)
    return static_model.StaticModel(out), emb


def _pieces(model, text: str) -> list[str]:
    return [VOCAB[i][0] for i in model.tokenize(text)]


def test_viterbi_picks_the_best_scoring_segmentation(tmp_path):
    model, _ = _prepared(tmp_path)
    assert _pieces(model, "ab") == ["\u2581ab"]              # -1.0 beats -2.0 + -2.5
    assert _pieces(model, "abc") == ["\u2581ab", "c"]
    assert _pieces(model, "김치") == ["\u2581김치"]


def test_punctuation_is_split_and_unknown_runs_fuse(tmp_path):
    model, _ = _prepared(tmp_path)
    assert _pieces(model, "ab,c") == ["\u2581ab", "\u2581,", "\u2581c"]
    assert _pieces(model, "ab  xyz") == ["\u2581ab", "\u2581", "[UNK]"]


def test_encode_sums_dequantized_rows(tmp_path):
    model, emb = _prepared(tmp_path)
    vec = model.encode(["abc", ""])
    want = emb[3] + emb[6]
    assert vec.shape == (2, 4)
    assert np.allclose(vec[0], want, atol=0.05)
    assert not vec[1].any()


def test_prepare_runs_in_a_child_process(tmp_path):
    snap, _ = _snapshot(tmp_path)
    out = tmp_path / "prepared"
    static_model.prepare_isolated(snap, out, python=sys.executable)
    assert static_model.StaticModel(out).tokenize("ab")
    assert not list(tmp_path.glob("prepared.tmp*"))
