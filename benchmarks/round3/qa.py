#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# How to run: python benchmarks/round3/qa.py --feature consolidation
# Alternatively install uv and run: uv run benchmarks/round3/qa.py
"""Real public-API scenarios, temporary resources paired with cleanup."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from birkin_mnemosyne import Answer, Consolidation, ReviewError, VaultMemory
from birkin_mnemosyne.identity_reader import IdentityReader, IdentityReadError


def consolidation() -> dict[str, str | int | float]:
    """PASS requires read-only questions, explicit merge, undo and stale refusal."""
    with tempfile.TemporaryDirectory(prefix="mnemosyne-round3-") as directory:
        vault = Path(directory)
        memory = VaultMemory({"vault_path": directory})
        memory.write_note("Release rule", "Review a release before publishing.",
                          source="user:one", zone="identity")
        memory.write_note("Release reminder", "Review a release before publishing.",
                          source="user:two", zone="workflow")
        before = {p.relative_to(vault): p.read_bytes() for p in vault.rglob("*.md")}
        service = Consolidation(vault)
        start = time.perf_counter()
        question, = service.questions()
        question_ms = (time.perf_counter() - start) * 1000
        assert before == {p.relative_to(vault): p.read_bytes()
                          for p in vault.rglob("*.md")}
        start = time.perf_counter()
        receipt = service.apply(question, Answer(
            question.id, "merge", "Review releases; publishing requires approval.",
        ))
        apply_ms = (time.perf_counter() - start) * 1000
        assert len(service.dex.search("release")) == 1
        manifest = json.loads((vault / receipt.journal_path).read_text("utf-8"))
        assert manifest["question_id"] == question.id
        assert manifest["merged_body"] == "Review releases; publishing requires approval."
        start = time.perf_counter()
        service.undo(receipt.transaction_id)
        undo_ms = (time.perf_counter() - start) * 1000
        assert before == {p.relative_to(vault): p.read_bytes()
                          for p in vault.rglob("*.md")}
        memory.write_note("Release rule", "A new decision supersedes the question.")
        try:
            service.apply(question, Answer(question.id, "keep-first"))
        except ReviewError:
            pass
        else:
            raise AssertionError("stale answer applied")
    assert not Path(directory).exists()
    return {"feature": "consolidation", "result": "PASS", "checks": 5,
            "question_ms": question_ms, "apply_ms": apply_ms, "undo_ms": undo_ms,
            "cleanup": f"temporary vault removed: {directory}"}


def identity() -> dict[str, str | int | float]:
    """PASS requires accurate partial context, revision refusal and fresh full read."""
    with tempfile.TemporaryDirectory(prefix="mnemosyne-identity-") as directory:
        root = Path(directory)
        path = root / "AGENTS.md"
        text = "# Agent\n## Conversation\nLanguage: Korean\n## Obsolete\nLanguage: English\n"
        text += "".join(f"## Topic {i}\nFictional background {i}: " +
                        "Unrelated reference details. " * 30 + "\n" for i in range(40))
        path.write_bytes(text.encode("utf-8"))
        reader = IdentityReader(root)
        start = time.perf_counter()
        result = reader.search("AGENTS.md", "Conversation language", limit=1)
        cold_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        warm = reader.search("AGENTS.md", "Conversation language", limit=1)
        warm_ms = (time.perf_counter() - start) * 1000
        assert warm.revision == result.revision
        assert "Language: Korean" in result.context
        assert "Language: English" not in result.context
        assert not result.complete_file
        path.write_bytes(text.replace("Korean", "Japanese").encode("utf-8"))
        try:
            reader.read_section("AGENTS.md", result.sections[0].anchor, result.revision)
        except IdentityReadError:
            pass
        else:
            raise AssertionError("stale anchor revision accepted")
        current = reader.read_full("AGENTS.md", force_refresh=True)
        assert "Japanese" in current.context and current.complete_file
        assert reader.search("AGENTS.md", "unfindable-zebra").context == ""
    assert not Path(directory).exists()
    return {"feature": "identity-reader", "result": "PASS", "checks": 6,
            "cold_ms": cold_ms, "warm_ms": warm_ms,
            "full_chars": len(text), "excerpt_chars": len(result.context),
            "full_tokens_estimated_chars_div_4": len(text) / 4,
            "excerpt_tokens_estimated_chars_div_4": len(result.context) / 4,
            "cleanup": f"temporary identity root removed: {directory}"}


def main() -> None:
    scenarios = {"consolidation": consolidation, "identity": identity}
    args = sys.argv[1:]
    if args:
        if len(args) != 2 or args[0] != "--feature" or args[1] not in scenarios:
            raise SystemExit("usage: qa.py [--feature consolidation|identity]")
        scenarios = {args[1]: scenarios[args[1]]}
    for scenario in scenarios.values():
        print(json.dumps(scenario(), ensure_ascii=True))


if __name__ == "__main__":
    main()
