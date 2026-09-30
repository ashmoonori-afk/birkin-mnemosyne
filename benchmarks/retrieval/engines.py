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
        self.dex = Mnemosyne(vault)

    def build(self) -> None:
        self.dex.rebuild()

    def search(self, query: str, k: int) -> list[str]:
        return [h["slug"] for h in self.dex.search(query, limit=k)]


ENGINES: dict[str, type] = {"bm25": BM25Engine}
