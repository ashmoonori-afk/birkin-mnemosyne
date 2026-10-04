"""Memory-lean runtime for a model2vec-style static embedding model.

The reference stack (model2vec + HF ``tokenizers``) keeps the 500k-piece
Unigram tokenizer of ``potion-multilingual-128M`` in ~770 MB of RAM and its
float32 table in another 512 MB. This module needs neither:

- :func:`prepare` converts a downloaded snapshot once into a directory of
  ``.npy`` files: a sorted table of 64-bit piece hashes (vocabulary lookup
  without a Python dict), piece scores, and the embedding table as int8 with
  one float scale per row. It runs in a child process
  (:func:`prepare_isolated`) so its transient memory never stays resident.
- :class:`StaticModel` memory-maps the int8 table (only rows of tokens that
  are actually encoded are paged in) and tokenizes with a Viterbi search that
  reproduces the Unigram tokenizer: NFKC normalization, ASCII punctuation
  split off, whitespace collapsed, ``▁`` word prefix, best-scoring
  segmentation per word, consecutive unknown characters fused into one
  ``[UNK]``. On the benchmark corpus its token ids match ``tokenizers``
  exactly.

A text vector is the sum of its token rows (the reference model's mean,
before normalization; retrieval here only compares directions).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    import numpy.typing as npt

    _Json = dict[str, "_Json"] | list["_Json"] | str | int | float | bool | None

MAX_PIECE_CHARS = 24          # longer pieces are too rare to matter
MAX_TOKENS = 512              # as model2vec's default encode()
_PUNCT = re.compile(r'([!"#$%&\'()*+,\-./:;<=>?@\[\\\]^_`{|}~])')
_SPACES = re.compile(r"\s+")
_WORD_MARK = "\u2581"


class _Meta(TypedDict):
    unk_id: int
    min_score: float
    dim: int


class _Slice(Protocol):
    def get_shape(self) -> list[int]: ...
    def __getitem__(self, key: slice, /) -> npt.NDArray[np.generic]: ...


class _SafeFile(Protocol):
    def get_slice(self, name: str, /) -> _Slice: ...


class _SafeOpen(Protocol):
    def __call__(self, filename: str, framework: str) -> AbstractContextManager[_SafeFile]: ...


class _Loads(Protocol):
    def __call__(self, s: str, /) -> _Json: ...


def _safe_open() -> _SafeOpen:
    from safetensors import safe_open

    return safe_open


def _json_loads() -> _Loads:
    return json.loads


def _load_unigram(path: Path) -> tuple[int, list[tuple[str, float]]]:
    raw = _json_loads()(path.read_text(encoding="utf-8"))
    spec = raw.get("model") if isinstance(raw, dict) else None
    if not isinstance(spec, dict):
        raise TypeError("malformed tokenizer.json")
    if spec.get("type") != "Unigram":
        raise ValueError(f"unsupported tokenizer model {spec.get('type')!r}")
    unk_id = spec.get("unk_id")
    raw_vocab = spec.get("vocab")
    if not isinstance(unk_id, int) or not isinstance(raw_vocab, list):
        raise TypeError("malformed tokenizer.json")
    vocab: list[tuple[str, float]] = []
    for entry in raw_vocab:
        if not isinstance(entry, list) or len(entry) != 2:
            raise TypeError("malformed tokenizer.json")
        piece, score = entry
        if not isinstance(piece, str) or not isinstance(score, (int, float)):
            raise TypeError("malformed tokenizer.json")
        vocab.append((piece, score))
    return unk_id, vocab


def _load_meta(path: Path) -> _Meta:
    raw = _json_loads()(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("malformed meta.json")
    unk_id, min_score, dim = raw.get("unk_id"), raw.get("min_score"), raw.get("dim")
    if (not isinstance(unk_id, int) or not isinstance(dim, int)
            or not isinstance(min_score, (int, float))):
        raise TypeError("malformed meta.json")
    return {"unk_id": unk_id, "min_score": min_score, "dim": dim}


def _hash(piece: str) -> int:
    return int.from_bytes(hashlib.blake2b(piece.encode("utf-8"), digest_size=8).digest(),
                          "little")


def prepare(snapshot: Path, out: Path, block: int = 65536) -> None:
    """Convert ``tokenizer.json`` + ``model.safetensors`` into ``out``."""
    open_safe = _safe_open()
    snapshot, out = Path(snapshot), Path(out)
    unk_id, vocab = _load_unigram(snapshot / "tokenizer.json")
    keys = np.fromiter((_hash(p) for p, _ in vocab), dtype=np.uint64, count=len(vocab))
    order = np.argsort(keys, kind="stable")
    if len(np.unique(keys)) != len(keys):
        raise ValueError("piece hash collision")
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "keys.npy", keys[order])
    np.save(out / "ids.npy", order.astype(np.int32))
    np.save(out / "scores.npy", np.array([s for _, s in vocab], dtype=np.float32))
    n = len(vocab)
    with open_safe(str(snapshot / "model.safetensors"), framework="numpy") as f:
        rows = f.get_slice("embeddings")
        dim = rows.get_shape()[1]
        table: npt.NDArray[np.int8] = np.lib.format.open_memmap(out / "emb_int8.npy", mode="w+",
                                          dtype=np.int8, shape=(n, dim))
        scale = np.empty(n, dtype=np.float32)
        for start in range(0, n, block):
            chunk: npt.NDArray[np.float32] = rows[start:min(start + block, n)].astype(np.float32)
            sc: npt.NDArray[np.float32] = np.asarray(np.abs(chunk).max(axis=1) / 127.0,
                                                      dtype=np.float32)
            sc[sc == 0] = 1.0
            table[start:start + len(chunk)] = np.round(chunk / sc[:, None]).astype(np.int8)
            scale[start:start + len(chunk)] = sc
        table.flush()
        del table
    np.save(out / "scale.npy", scale)
    meta: _Meta = {"unk_id": unk_id, "min_score": min(s for _, s in vocab), "dim": dim}
    _ = (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def prepare_isolated(snapshot: Path, out: Path, python: str | None = None) -> None:
    """Run :func:`prepare` in a child process into a temp dir, then move it
    into place, so a half-written model directory is never visible."""
    out = Path(out)
    tmp = out.with_name(out.name + f".tmp{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    package_root = str(Path(__file__).resolve().parents[1])
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(filter(None, [package_root,
                                                       os.environ.get("PYTHONPATH")]))}
    try:
        proc = subprocess.run([python or sys.executable, "-m", __name__, str(snapshot), str(tmp)],
                              check=False, capture_output=True, text=True, env=env)
        try:
            proc.check_returncode()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"model conversion failed: {proc.stderr.strip()[-500:]}") from exc
        if out.exists():
            shutil.rmtree(out)
        os.replace(tmp, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def normalize(text: str) -> str:
    text = _PUNCT.sub(r" \1 ", unicodedata.normalize("NFKC", text))
    return _SPACES.sub(" ", text).strip()


class StaticModel:
    """Tokenizer + int8 embedding table loaded from a :func:`prepare` dir."""

    def __init__(self, path: Path):
        path = Path(path)
        meta = _load_meta(path / "meta.json")
        self.path: Path = path
        self.dim: int = meta["dim"]
        self._unk: int = meta["unk_id"]
        self._unk_score: float = float(meta["min_score"]) - 10.0   # tokenizers' penalty
        self._keys: npt.NDArray[np.uint64] = np.load(path / "keys.npy")
        self._ids: npt.NDArray[np.int32] = np.load(path / "ids.npy")
        self._scores: npt.NDArray[np.float32] = np.load(path / "scores.npy")
        self._scale: npt.NDArray[np.float32] = np.load(path / "scale.npy")
        self._table: npt.NDArray[np.int8] | None = None
        self._word: Callable[[str], tuple[int, ...]] = lru_cache(maxsize=65536)(self._segment)

    def _rows(self) -> npt.NDArray[np.int8]:
        table = self._table
        if table is None:
            loaded: npt.NDArray[np.int8] = np.asarray(
                np.load(self.path / "emb_int8.npy", mmap_mode="r"), dtype=np.int8)
            table = loaded
            self._table = table
        return table

    @property
    def released(self) -> bool:
        return self._table is None

    def release(self) -> None:
        """Unmap the table so pages touched by a bulk encode leave RSS."""
        self._table = None

    def _segment(self, word: str) -> tuple[int, ...]:
        n = len(word)
        spans = [(i, j) for i in range(n) for j in range(i + 1, min(n, i + MAX_PIECE_CHARS) + 1)]
        hashes = np.fromiter((_hash(word[i:j]) for i, j in spans), dtype=np.uint64,
                             count=len(spans))
        pos = np.searchsorted(self._keys, hashes)
        pos[pos >= len(self._keys)] = 0
        ends: dict[int, list[tuple[int, int]]] = {}
        hit_mask = np.asarray(self._keys[pos] == hashes, dtype=np.bool_).tobytes()
        pos_view = memoryview(pos.astype(np.int64).tobytes()).cast("q")
        for (i, j), hit, p in zip(spans, hit_mask, pos_view):
            if hit:
                ends.setdefault(j, []).append((i, int(np.asarray(self._ids[p], dtype=np.int32))))
        best: list[tuple[float, int, int]] = [(0.0, -1, -1)]
        for j in range(1, n + 1):
            cand = (best[j - 1][0] + self._unk_score, j - 1, self._unk)
            for i, pid in ends.get(j, ()):
                score = best[i][0] + float(np.asarray(self._scores[pid], dtype=np.float32))
                if score > cand[0]:
                    cand = (score, i, pid)
            best.append(cand)
        out: list[int] = []
        j = n
        while j > 0:
            _, i, pid = best[j]
            if not (pid == self._unk and out and out[-1] == self._unk):
                out.append(pid)
            j = i
        return tuple(reversed(out))

    def tokenize(self, text: str) -> list[int]:
        text = normalize(text)
        if not text:
            return []
        ids: list[int] = []
        for word in text.split(" "):
            ids.extend(self._word(_WORD_MARK + word))
        return ids[:MAX_TOKENS]

    def encode(self, texts: list[str]) -> npt.NDArray[np.float32]:
        rows = self._rows()
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for k, text in enumerate(texts):
            ids = self.tokenize(text)
            if ids:
                prod: npt.NDArray[np.float32] = (
                    rows[ids].astype(np.float32) * self._scale[ids, None])
                acc: npt.NDArray[np.float32] = np.asarray(prod.sum(axis=0), dtype=np.float32)
                out[k] = acc
        return out


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
