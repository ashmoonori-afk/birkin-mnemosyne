"""Mnemosyne — a zero-dependency memory palace + safe curation for LLM agents.

Two things, both built from the Python standard library alone:

- **Retrieval** (:class:`Mnemosyne`): Markdown notes in zone directories, an
  Okapi-BM25 inverted index with a Unicode-aware tokenizer (CJK and Hangul
  bigrams, accent folding), and a usage-driven
  Ebbinghaus decay wired into the ranking.
- **Curation** (:func:`run_curation_pass`): the *CurationPlan/1* interface —
  the model emits a typed JSON plan, a deterministic executor validates,
  clamps, and applies it under file-safety invariants enforced in code, so a
  weak or adversarial model cannot delete, mass-archive, escape, or archive a
  protected note.

Quick start::

    from birkin_mnemosyne import Mnemosyne, run_curation_pass, get_completer

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

from importlib import import_module
from typing import Any

__version__ = "0.4.0"

_EXPORTS = {
    "KibitzerAdapter": "birkin_mnemosyne.kibitzer",
    "RecallDocument": "birkin_mnemosyne.kibitzer",
    "RecallCandidate": "birkin_mnemosyne.kibitzer",
    "RecallNudge": "birkin_mnemosyne.kibitzer",
    "Admission": "birkin_mnemosyne.kibitzer",
    "admit": "birkin_mnemosyne.kibitzer",
    "render_recall": "birkin_mnemosyne.kibitzer",
    "StartupReader": "birkin_mnemosyne.startup",
    "StartupBundle": "birkin_mnemosyne.startup",
    "StartupError": "birkin_mnemosyne.startup",
    "Coverage": "birkin_mnemosyne.startup_coverage",
    "IdentityReader": "birkin_mnemosyne.identity_reader",
    "IdentityReadError": "birkin_mnemosyne.identity_reader",
    "ReadResult": "birkin_mnemosyne.identity_reader",
    "Section": "birkin_mnemosyne.identity_reader",
    "Answer": "birkin_mnemosyne.consolidation",
    "Consolidation": "birkin_mnemosyne.consolidation",
    "Question": "birkin_mnemosyne.consolidation",
    "ReviewError": "birkin_mnemosyne.review_journal",
    "Receipt": "birkin_mnemosyne.review_journal",
    "ARCHIVE_CAP_FRACTION": "birkin_mnemosyne.curation_contract",
    "ARCHIVE_CAP_MIN": "birkin_mnemosyne.curation_contract",
    "ARCHIVE_ZONE": "birkin_mnemosyne.mnemosyne",
    "OPS": "birkin_mnemosyne.curation_contract",
    "PLAN_VERSION": "birkin_mnemosyne.curation_contract",
    "PROFILE_DESCRIPTIONS": "birkin_mnemosyne.profiles",
    "CurationOutcome": "birkin_mnemosyne.curation_contract",
    "Mnemosyne": "birkin_mnemosyne.mnemosyne",
    "ProfileAction": "birkin_mnemosyne.profiles",
    "ProfileExchange": "birkin_mnemosyne.profiles",
    "ProfileMemory": "birkin_mnemosyne.profiles",
    "ProfileProposal": "birkin_mnemosyne.profiles",
    "ProfileReviewError": "birkin_mnemosyne.profiles",
    "ProfileReviewer": "birkin_mnemosyne.profiles",
    "ProfileSaver": "birkin_mnemosyne.profiles",
    "VaultMemory": "birkin_mnemosyne.memory",
    "VersionMismatchError": "birkin_mnemosyne.memory",
    "bm25_scores": "birkin_mnemosyne.mnemosyne",
    "build_plan_prompt": "birkin_mnemosyne.curation_prompt",
    "default_dynamics": "birkin_mnemosyne.mnemosyne",
    "effective_strength": "birkin_mnemosyne.mnemosyne",
    "evaluate_plan": "birkin_mnemosyne.curation",
    "extract_plan": "birkin_mnemosyne.curation_prompt",
    "get_completer": "birkin_mnemosyne.providers",
    "mechanical_catalog": "birkin_mnemosyne.curation_prompt",
    "potentiate": "birkin_mnemosyne.mnemosyne",
    "run_curation_pass": "birkin_mnemosyne.curation",
    "slug": "birkin_mnemosyne.mnemosyne",
    "tokenize": "birkin_mnemosyne.mnemosyne",
    "validate_clamp": "birkin_mnemosyne.curation_gate",
}

__all__ = [*_EXPORTS, "__version__"]


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name])
    value = getattr(module, name)
    globals()[name] = value
    return value
