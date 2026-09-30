"""Retrieval engines under benchmark. Kept free of corpus imports so the
cold-start probe (``_probe.py``) times only what a real caller would load."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from birkin_mnemosyne.mnemosyne import Mnemosyne

HERE = Path(__file__).resolve().parent


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


class ExpandedEngine(BM25Engine):
    """The core ranking plus search-time query expansions, replayed from
    ``expansions_<writer>.json``: what a model that saw only the query text
    wrote for it (never the notes). A query without an entry is searched as
    it is."""

    writer = ""

    def __init__(self, vault: Path):
        super().__init__(vault)
        self._expansions: dict[str, dict[str, Any]] | None = None

    def search(self, query: str, k: int) -> list[str]:
        if self._expansions is None:
            path = HERE / f"expansions_{self.writer}.json"
            self._expansions = json.loads(path.read_text(encoding="utf-8"))
        return [h["slug"] for h in self.dex.search(
            query, limit=k, expansions=self._expansions.get(query))]


class ExpandedClaudeEngine(ExpandedEngine):
    name = "expanded-claude"
    writer = "claude-sonnet-5.5"


class ExpandedGptEngine(ExpandedEngine):
    name = "expanded-gpt"
    writer = "gpt-6.1-sol"


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
                            "semantic": SemanticEngine,
                            "expanded-claude": ExpandedClaudeEngine,
                            "expanded-gpt": ExpandedGptEngine}
