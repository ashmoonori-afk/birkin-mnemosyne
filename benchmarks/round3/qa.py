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


def main() -> None:
    if sys.argv[1:] not in ([], ["--feature", "consolidation"]):
        raise SystemExit("usage: qa.py [--feature consolidation]")
    print(json.dumps(consolidation(), ensure_ascii=True))


if __name__ == "__main__":
    main()
