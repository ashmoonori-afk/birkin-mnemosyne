"""Retrieval engines under benchmark. Kept free of corpus imports so the
cold-start probe (``_probe.py``) times only what a real caller would load."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from birkin_mnemosyne.mnemosyne import Mnemosyne


class Engine(Protocol):
    name: str

    def build(self) -> None: ...

    def search(self, query: str, k: int) -> list[str]: ...


class BM25Engine:
    """The library's own search path (BM25 + dynamics/zone boosts)."""

    name = "bm25"

    def __init__(self, vault: Path):
        self.vault = vault
        self.dex = Mnemosyne(vault, semantic=False)

    def build(self) -> None:
        self.dex.rebuild()

    def search(self, query: str, k: int) -> list[str]:
        return [h["slug"] for h in self.dex.search(query, limit=k)]


class HybridEngine(BM25Engine):
    """BM25 + the optional semantic leg fused by RRF (needs ``[semantic]``)."""

    name = "hybrid"

    def __init__(self, vault: Path):
        self.vault = vault
        self.dex = Mnemosyne(vault, semantic=True)

    def build(self) -> None:
        self.dex.rebuild()
        sem = self.dex._semantic_index()
        if sem is None:
            raise RuntimeError("hybrid engine needs the [semantic] extra")
        sem.sync(self.dex.entries())


class SemanticEngine:
    """The semantic leg alone (diagnostic; needs ``[semantic]``)."""

    name = "semantic"

    def __init__(self, vault: Path):
        from birkin_mnemosyne.semantic import SemanticIndex

        self.dex = Mnemosyne(vault, semantic=False)
        self.index = SemanticIndex(vault)

    def build(self) -> None:
        self.dex.rebuild()
        self.index.sync(self.dex.entries())

    def search(self, query: str, k: int) -> list[str]:
        self.index.sync(self.dex.entries())
        return [s for s, _ in self.index.search(query, k)]


ENGINES: dict[str, type] = {"bm25": BM25Engine, "hybrid": HybridEngine,
                            "semantic": SemanticEngine}
