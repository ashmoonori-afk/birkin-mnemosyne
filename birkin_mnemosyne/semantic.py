"""Optional semantic leg: static multilingual embeddings fused with BM25.

Installed with ``pip install birkin-mnemosyne[semantic]`` (model2vec +
numpy). The core package never imports this module's dependencies at import
time; when they are missing, or the model cannot be loaded (offline first
run, disk full, ...), :class:`Mnemosyne` silently keeps its BM25-only path.

Design (every choice measured in benchmarks/retrieval, dev split):

- Model: ``minishlab/potion-multilingual-128M`` (static embeddings, no
  transformer at query time). English-only potion models could not bridge
  Korean questions about English notes.
- Storage: each note is cut into ~400-character chunks (title prefixed); a
  chunk is stored as the SIGN bits of its first 256 dimensions (32 bytes).
  Binary vectors scored as well as float32 on the benchmark.
- Scoring: the float query vector is dotted with the +-1 chunk vectors; a
  note scores its best chunk.
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
from pathlib import Path
from typing import Any

from . import frontmatter
from .atomic import atomic_write_bytes

log = logging.getLogger(__name__)

MODEL_NAME = "minishlab/potion-multilingual-128M"
DIM = 256
CHUNK_CHARS = 400
VECTORS_FILE = ".mnemosyne-vectors.npz"
FORMAT_VERSION = 1


def available() -> bool:
    """True when the optional dependencies are importable."""
    try:
        import model2vec  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def chunk_text(title: str, body: str, max_chars: int | None = None) -> list[str]:
    """Split a note into paragraph-aligned chunks of about ``max_chars``
    (default :data:`CHUNK_CHARS`); every chunk after the first repeats the
    title for context."""
    max_chars = CHUNK_CHARS if max_chars is None else max_chars
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
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
        self._matrix: Any = None                   # cached +-1 float32 (N, dim)
        self._owners: list[str] = []
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
            from model2vec import StaticModel

            self._model = StaticModel.from_pretrained(self.model_name,
                                                      force_download=False)
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
                slugs = [str(s) for s in data["slugs"]]
                counts = data["counts"].tolist()
                fps = data["fps"].tolist()
                bits = data["bits"]
        except (OSError, KeyError, ValueError):
            return
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
                bits = self._pack(self._encode(flat))
                start = 0
                for s, fp, cs in todo:
                    self._chunks[s] = bits[start:start + len(cs)]
                    self._fp[s] = fp
                    start += len(cs)
                changed = True
            if changed or self._matrix is None:
                self._rebuild_matrix()
            if changed:
                self._save()

    def _rebuild_matrix(self) -> None:
        np = self._np
        slugs = sorted(self._chunks)
        self._owners = [s for s in slugs for _ in range(len(self._chunks[s]))]
        if not slugs:
            self._matrix = np.zeros((0, self.dim), dtype=np.float32)
            return
        bits = np.concatenate([self._chunks[s] for s in slugs])
        signs = np.unpackbits(bits, axis=1, count=self.dim).astype(np.float32)
        self._matrix = signs * 2.0 - 1.0

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Top ``limit`` notes by best-chunk similarity to ``query``."""
        np = self._np
        with self._lock:
            if self._matrix is None or not len(self._owners):
                return []
            q = self._encode([query])[0].astype(np.float32)
            q /= float(np.linalg.norm(q)) or 1.0
            sims = self._matrix @ q
            best: dict[str, float] = {}
            for owner, sim in zip(self._owners, sims.tolist()):
                if sim > best.get(owner, -1e9):
                    best[owner] = sim
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]


def enabled_by_env() -> bool | None:
    """``MNEMOSYNE_SEMANTIC=0`` disables, ``=1`` requires; unset = auto."""
    raw = os.environ.get("MNEMOSYNE_SEMANTIC", "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    if raw in ("1", "true", "on", "yes"):
        return True
    return None
