"""Optional semantic leg: static multilingual embeddings fused with BM25.

Installed with ``pip install birkin-mnemosyne[semantic]`` (numpy,
safetensors, huggingface_hub). The core package never imports this module's dependencies at import
time; when they are missing, or the model cannot be loaded (offline first
run, disk full, ...), :class:`Mnemosyne` keeps its BM25-only path and logs
one warning. The mode is opt-in: ``Mnemosyne(vault, semantic=True)`` or
``MNEMOSYNE_SEMANTIC=1``.

Design (every choice measured in benchmarks/retrieval, dev split):

- Model: ``minishlab/potion-multilingual-128M`` (static embeddings, no
  transformer at query time). English-only potion models could not bridge
  Korean questions about English notes. It is downloaded once (~530 MB),
  converted once in a child process into a compact form (int8 table,
  hashed vocabulary; see :mod:`.static_model`) under the user cache dir, and
  from then on loads in ~0.1 s with a few tens of MB resident.
- Storage: each note is cut into ~400-character chunks (title prefixed); a
  chunk is stored as the SIGN bits of its first 256 dimensions (32 bytes).
  Binary vectors scored as well as float32 on the benchmark.
- Scoring: the float query vector is dotted with the +-1 chunk vectors; a
  note scores its best chunk. The chunk vectors stay packed (32 bytes): per
  query, a 32 x 256 table holds the partial dot product of every possible
  byte at every byte position, and a chunk's score is the sum of 32 lookups.
- Fusion: reciprocal-rank fusion of the BM25 and semantic rankings.

Sidecar ``.mnemosyne-vectors.npz`` is a rebuildable cache keyed by model
name, dimension and chunk size, refreshed by stat fingerprint like the BM25
index.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import zipfile
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from . import frontmatter
from .atomic import atomic_write_bytes

log = logging.getLogger(__name__)

MODEL_NAME = "minishlab/potion-multilingual-128M"
DIM = 256
CHUNK_CHARS = 400
# the repo also ships a 512 MB ONNX export that is never read
MODEL_FILES = ["model.safetensors", "tokenizer.json"]
VECTORS_FILE = ".mnemosyne-vectors.npz"
FORMAT_VERSION = 2
ENCODE_BATCH = 2048     # chunks embedded per call while indexing
SCORE_BLOCK = 4096      # chunks scored per lookup block (bounds the temporary)


def available() -> bool:
    """True when the optional dependencies are installed. They are located,
    not imported: importing huggingface_hub alone is ~150 ms of a cold start
    and is only needed for the one-time model download."""
    return all(find_spec(name) is not None
               for name in ("numpy", "safetensors", "huggingface_hub"))


def model_dir(model_name: str = MODEL_NAME) -> Path:
    """Where the compact form of ``model_name`` lives (see :func:`prepare`)."""
    root = Path(os.environ.get("MNEMOSYNE_MODEL_CACHE")
                or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
                / "birkin-mnemosyne")
    return root / f"{model_name.replace('/', '--')}-v{FORMAT_VERSION}"


def prepared(model_name: str = MODEL_NAME) -> bool:
    return (model_dir(model_name) / "meta.json").exists()


def prepare(model_name: str = MODEL_NAME) -> Path:
    """Download ``model_name`` (~530 MB, once) and convert it to its compact
    form. Run it explicitly (``python -m birkin_mnemosyne.semantic``): a search
    never downloads or converts, it uses BM25 until the model is prepared."""
    out = model_dir(model_name)
    if not prepared(model_name):
        from huggingface_hub import snapshot_download

        from .static_model import prepare_isolated

        snapshot = snapshot_download(model_name, allow_patterns=MODEL_FILES)
        prepare_isolated(Path(snapshot), out)
    return out


def chunk_text(title: str, body: str, max_chars: int | None = None) -> list[str]:
    """Split a note into paragraph-aligned chunks of about ``max_chars``
    (default :data:`CHUNK_CHARS`); every chunk after the first repeats the
    title for context."""
    max_chars = CHUNK_CHARS if max_chars is None else max_chars
    # a paragraph longer than a chunk is cut, or its tail would never be embedded
    paras = [p[i:i + max_chars] for p in (p.strip() for p in body.split("\n\n"))
             for i in range(0, len(p), max_chars)]
    if not paras:
        return [title]
    chunks: list[str] = []
    cur = title
    for p in paras:
        if cur != title and len(cur) + len(p) > max_chars:
            chunks.append(cur)
            cur = f"{title}\n{p}"
        else:
            cur = f"{cur}\n{p}"
    chunks.append(cur)
    return chunks


class SemanticIndex:
    """Binary chunk vectors for one vault. Thread-safe via one lock."""

    def __init__(self, vault: Path, model_name: str = MODEL_NAME, dim: int = DIM):
        import numpy as np

        self._np = np
        self.vault = Path(vault)
        self.model_name = model_name
        self.dim = dim
        self._lock = threading.Lock()
        self._model: Any = None
        self._fp: dict[str, tuple[float, int]] = {}
        self._chunks: dict[str, Any] = {}          # slug -> packed bits (n, dim/8)
        self._bits: Any = None                     # all chunks, slug order (N, dim/8)
        self._slugs: list[str] = []
        self._starts: Any = None                   # first chunk row of each slug
        # the 8 signs (+-1) each byte value stands for, most significant bit first
        self._byte_signs = np.unpackbits(
            np.arange(256, dtype=np.uint8)[:, None], axis=1).astype(np.float32) * 2.0 - 1.0
        self._loaded = False

    @property
    def path(self) -> Path:
        return self.vault / VECTORS_FILE

    def _meta(self) -> dict[str, Any]:
        return {"version": FORMAT_VERSION, "model": self.model_name,
                "dim": self.dim, "chunk": CHUNK_CHARS}

    # -- model / encoding ---------------------------------------------------

    def _encoder(self) -> Any:
        if self._model is None:
            if not prepared(self.model_name):
                raise RuntimeError(
                    "the semantic model is not prepared; run "
                    "`python -m birkin_mnemosyne.semantic` once")
            from .static_model import StaticModel

            self._model = StaticModel(model_dir(self.model_name))
        return self._model

    def _encode(self, texts: list[str]) -> Any:
        return self._encoder().encode(texts)[:, :self.dim]

    def _pack(self, vecs: Any) -> Any:
        return self._np.packbits(vecs > 0, axis=1)

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        self._loaded = True
        np = self._np
        try:
            with np.load(self.path, allow_pickle=False) as data:
                if json.loads(str(data["meta"])) != self._meta():
                    return
                slugs = [str(s) for s in data["slugs"].reshape(-1)]
                counts, fps, bits = data["counts"], data["fps"], data["bits"]
        except (OSError, KeyError, ValueError, TypeError, EOFError, zipfile.BadZipFile):
            return   # missing, empty, truncated or foreign file: re-embed
        if (counts.ndim != 1 or counts.dtype.kind not in "iu" or len(counts) != len(slugs)
                or fps.ndim != 2 or fps.shape != (len(slugs), 2) or fps.dtype.kind not in "fiu"
                or bits.ndim != 2 or bits.dtype != np.uint8
                or bits.shape[1] != self.dim // 8 or not np.isfinite(fps).all()
                or int(counts.sum()) != len(bits) or (len(counts) and int(counts.min()) < 1)):
            return   # wrong shapes, types or totals: re-embed
        counts, fps = counts.tolist(), fps.tolist()
        start = 0
        for s, n, (mtime, size) in zip(slugs, counts, fps):
            self._chunks[s] = bits[start:start + n]
            self._fp[s] = (float(mtime), int(size))
            start += n

    def _save(self) -> None:
        np = self._np
        slugs = sorted(self._chunks)
        buf = io.BytesIO()
        np.savez(
            buf, meta=np.array(json.dumps(self._meta())),
            slugs=np.array(slugs, dtype=str),
            counts=np.array([len(self._chunks[s]) for s in slugs], dtype=np.int32),
            fps=np.array([self._fp[s] for s in slugs], dtype=np.float64).reshape(-1, 2),
            bits=(np.concatenate([self._chunks[s] for s in slugs])
                  if slugs else np.zeros((0, self.dim // 8), dtype=np.uint8)))
        try:
            atomic_write_bytes(self.path, buf.getvalue())
        except OSError:
            pass   # cache flush is best-effort; rebuilt on next sync

    # -- sync / search ---------------------------------------------------------

    def sync(self, entries: dict[str, dict[str, Any]]) -> None:
        """Embed new/changed notes, drop removed ones (``entries`` is
        :meth:`Mnemosyne.entries`)."""
        with self._lock:
            if not self._loaded:
                self._load()
            changed = False
            for s in [s for s in self._chunks if s not in entries]:
                del self._chunks[s]
                self._fp.pop(s, None)
                changed = True
            todo: list[tuple[str, tuple[float, int], list[str]]] = []
            for s, e in entries.items():
                fp = (float(e["mtime"]), int(e["size"]))
                if self._fp.get(s) == fp:
                    continue
                try:
                    text = (self.vault / e["rel"]).read_text(encoding="utf-8",
                                                             errors="replace")
                except OSError:
                    continue
                _, body = frontmatter.parse(text)
                todo.append((s, fp, chunk_text(e["title"], body)))
            if todo:
                flat = [c for _, _, cs in todo for c in cs]
                release = getattr(self._encoder(), "release", None)
                parts = []
                for i in range(0, len(flat), ENCODE_BATCH):
                    parts.append(self._pack(self._encode(flat[i:i + ENCODE_BATCH])))
                    if release is not None:
                        release()
                bits = self._np.concatenate(parts)
                start = 0
                for s, fp, cs in todo:
                    self._chunks[s] = bits[start:start + len(cs)]
                    self._fp[s] = fp
                    start += len(cs)
                changed = True
            if changed or self._bits is None:
                self._rebuild_bits()
            if changed:
                self._save()

    def _rebuild_bits(self) -> None:
        np = self._np
        self._slugs = sorted(self._chunks)
        counts = [len(self._chunks[s]) for s in self._slugs]
        self._starts = np.cumsum([0] + counts[:-1])
        self._bits = (np.concatenate([self._chunks[s] for s in self._slugs])
                      if self._slugs else np.zeros((0, self.dim // 8), dtype=np.uint8))

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Top ``limit`` notes by best-chunk similarity to ``query``."""
        np = self._np
        with self._lock:
            if self._bits is None or not self._slugs:
                return []
            q = self._encode([query])[0].astype(np.float32)
            q /= float(np.linalg.norm(q)) or 1.0
            # table[j, v]: dot product of byte value v at byte position j with q
            table = q.reshape(-1, 8) @ self._byte_signs.T
            positions = np.arange(table.shape[0])
            sims = np.empty(len(self._bits), dtype=np.float32)
            for i in range(0, len(sims), SCORE_BLOCK):
                sims[i:i + SCORE_BLOCK] = table[
                    positions, self._bits[i:i + SCORE_BLOCK]].sum(axis=1)
            best = np.maximum.reduceat(sims, self._starts)
            top = np.argsort(-best, kind="stable")[:limit]
            return [(self._slugs[i], float(best[i])) for i in top.tolist()]


def enabled_by_env() -> bool | None:
    """``MNEMOSYNE_SEMANTIC=1`` turns the semantic mode on for
    ``Mnemosyne(semantic=None)``; ``=0`` or unset leaves it off (None)."""
    raw = os.environ.get("MNEMOSYNE_SEMANTIC", "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    if raw in ("1", "true", "on", "yes"):
        return True
    return None


if __name__ == "__main__":
    print(prepare())
