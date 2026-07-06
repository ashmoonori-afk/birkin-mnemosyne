"""Mnemosyne — a zero-dependency memory palace + safe curation for LLM agents.

Two things, both built from the Python standard library alone:

- **Retrieval** (:class:`Mnemosyne`): Markdown notes in zone directories, an
  Okapi-BM25 inverted index with a Hangul-bigram tokenizer, and a usage-driven
  Ebbinghaus decay wired into the ranking.
- **Curation** (:func:`run_curation_pass`): the *CurationPlan/1* interface —
  the model emits a typed JSON plan, a deterministic executor validates,
  clamps, and applies it under file-safety invariants enforced in code, so a
  weak or adversarial model cannot delete, mass-archive, escape, or archive a
  protected note.

Quick start::

    from mnemosyne import Mnemosyne, run_curation_pass, get_completer

    mem = Mnemosyne("my_vault")
    mem.refresh()
    hits = mem.search("kubernetes ingress dns")

    # nightly reorganization, safe on any model:
    complete = get_completer("codex")            # or "claude" / "api" / ...
    run_curation_pass("my_vault", complete, provider="codex")

Any ``complete(prompt: str) -> str`` works as the model surface — including
your own client from openclaw, hermes, or a raw HTTP call.
"""

from __future__ import annotations

from .mnemosyne import (
    ARCHIVE_ZONE,
    Mnemosyne,
    bm25_scores,
    default_dynamics,
    effective_strength,
    potentiate,
    slug,
    tokenize,
)
from .memory import VaultMemory, VersionMismatchError
from .curation import run_curation_pass
from .curation_contract import (
    ARCHIVE_CAP_FRACTION,
    ARCHIVE_CAP_MIN,
    OPS,
    PLAN_VERSION,
    CurationOutcome,
)
from .curation_gate import validate_clamp
from .curation_prompt import build_plan_prompt, extract_plan, mechanical_catalog
from .providers import get_completer

__version__ = "0.1.0"

__all__ = [
    # retrieval
    "Mnemosyne", "VaultMemory", "VersionMismatchError",
    "slug", "tokenize", "bm25_scores",
    "default_dynamics", "effective_strength", "potentiate", "ARCHIVE_ZONE",
    # curation
    "run_curation_pass", "CurationOutcome", "validate_clamp",
    "build_plan_prompt", "extract_plan", "mechanical_catalog",
    "OPS", "PLAN_VERSION", "ARCHIVE_CAP_FRACTION", "ARCHIVE_CAP_MIN",
    # providers
    "get_completer",
    "__version__",
]
