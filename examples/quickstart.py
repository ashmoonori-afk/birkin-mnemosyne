"""Quickstart: write notes, search, and inspect decay — no model, no network.

    python examples/quickstart.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from birkin_mnemosyne import Mnemosyne, VaultMemory

vault = Path(tempfile.mkdtemp()) / "vault"

# 1) write a few notes through the ergonomic API (frontmatter is generated)
mem = VaultMemory({"vault_path": str(vault)})
mem.write_note("K8s ingress DNS", "nginx ingress resolves service dns; "
               "firewall allows 443 to the ingress subnet.", zone="devops")
mem.write_note("Postgres autovacuum", "tune autovacuum so dead tuples do not "
               "bloat the index on write-heavy tables.", zone="devops")
mem.write_note("Sourdough hydration", "raise hydration for an open crumb; "
               "whole-grain flour drinks more water.", zone="baking")

# 2) rank by BM25 (+ usage/zone boosts) through the mechanical engine
eng: Mnemosyne = mem.dex
eng.refresh()
print("query: 'ingress dns firewall'")
for h in eng.search("ingress dns firewall", limit=3):
    print(f"  {h['score']:.2f}  {h['slug']}")

# 3) usage-driven decay: reading a note potentiates it; spaced reads keep it
s = eng.entries()["k8s-ingress-dns"]["rel"].rsplit("/", 1)[-1][:-3]
print("\neffective strength before/after an access:")
print("  before:", round(eng.effective_of(s), 3))
eng.record_access(s)
print("  after :", round(eng.effective_of(s), 3))
