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
from birkin_mnemosyne.kibitzer import KibitzerAdapter, RecallNudge, admit, render_recall
from birkin_mnemosyne.startup import StartupReader


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


def kibitzer() -> dict[str, str | int | float]:
    """PASS requires described export, selection exclusions and admitted envelope."""
    with tempfile.TemporaryDirectory(prefix="mnemosyne-kibitzer-") as directory:
        root = Path(directory)
        vault = root / "vault"
        memory = VaultMemory({"vault_path": str(vault)})
        memory.write_note("Release guard", "Releases require approval.", source="user:rule")
        memory.write_note("Build logs", "Build logs retain diagnostic details.")
        memory.write_note("System guidance", "Releases require approval.", zone="system")
        adapter = KibitzerAdapter(vault)
        start = time.perf_counter()
        candidate, = adapter.select("release approval", limit=1)
        select_ms = (time.perf_counter() - start) * 1000
        assert candidate.path == "knowledge/release-guard.md"
        assert set(candidate.__dataclass_fields__) == {"path", "description", "excerpt", "score"}
        assert adapter.select("release approval", surfaced=[candidate.path]) == ()
        paths = adapter.export(root / "export")
        assert len(paths) == 2
        exported = (root / "export" / candidate.path).read_text("utf-8")
        assert exported.startswith("---\ndescription:")
        hint = "The note records that releases require approval."
        decision = admit([RecallNudge(candidate.path, hint)],
                         offered=[candidate.path], max_items=1)
        assert len(decision.accepted) == 1
        block = render_recall(decision.accepted[0])
        assert '<recalled-memory source="[[knowledge/release-guard.md]]">' in block
        assert admit([RecallNudge("forged.md", hint)],
                     offered=[candidate.path]).accepted == ()
    assert not Path(directory).exists()
    return {"feature": "kibitzer-adapter", "result": "PASS", "checks": 6,
            "select_ms": select_ms, "exported_notes": len(paths),
            "cleanup": f"temporary vault/export root removed: {directory}"}


def startup() -> dict[str, str | int | float]:
    """PASS requires all raw material, transitive closure, fresh hashes and mutation refusal."""
    with tempfile.TemporaryDirectory(prefix="mnemosyne-startup-") as directory:
        root = Path(directory)
        (root / "profile").mkdir()
        sources = {
            "MODE.md": "# Boot\nMUST READ: handoff.md\nMUST READ: profile/soul.md\n" +
                       "MUST READ: registry.json\n" +
                       "".join(f"Rule {i}: retain original evidence for operation {i}.\n"
                               for i in range(120)) + "Pending: final coverage check\n",
            "handoff.md": "TOP NOTE 2026-09-01\nPort: 4100\n" +
                          "TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nPort: 4200\n",
            "profile/soul.md": "# Soul\nMUST READ: human.md\nVoice: direct\n",
            "profile/human.md": "# Human\nApproval: publication requires consent\n",
            "registry.json": '{"jobs":[{"state":"active","pending":"capture CI receipt"}]}\n',
        }
        for path, text in sources.items():
            (root / path).write_bytes(text.encode("utf-8"))
        reader = StartupReader(root)
        start = time.perf_counter()
        result = reader.read(["MODE.md"])
        cold_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        warm = reader.read(["MODE.md"])
        warm_ms = (time.perf_counter() - start) * 1000
        assert warm.cache_hit and result.coverage.complete
        assert result.coverage.files == 5
        payload = json.loads(result.context)
        for path, text in sources.items():
            blocks = sorted((b for b in payload["blocks"] if b["path"] == path),
                            key=lambda b: b["start_byte"])
            assert "".join(b["text"] for b in blocks) == text
        notes = [b for b in payload["blocks"] if b["heading"].startswith("TOP NOTE")]
        assert notes[0]["heading"] == "TOP NOTE 2026-10-01"
        payload["blocks"].pop()
        assert not reader.verify(json.dumps(payload), ["MODE.md"]).complete
        (root / "handoff.md").write_bytes(sources["handoff.md"].replace("4200", "4300").encode())
        assert not reader.read(["MODE.md"]).cache_hit
        assert not reader.verify(result.context, ["MODE.md"]).complete
    assert not Path(directory).exists()
    return {"feature": "complete-startup", "result": "PASS", "checks": 7,
            "cold_ms": cold_ms, "warm_ms": warm_ms, "source_files": result.coverage.files,
            "covered_lines": result.coverage.lines, "source_bytes": result.coverage.bytes,
            "complete_payload_chars": len(result.context),
            "cleanup": f"temporary startup root removed: {directory}"}


def main() -> None:
    scenarios = {"consolidation": consolidation, "identity": identity,
                 "startup": startup, "kibitzer": kibitzer}
    args = sys.argv[1:]
    if args:
        if len(args) != 2 or args[0] != "--feature" or args[1] not in scenarios:
            raise SystemExit("usage: qa.py [--feature consolidation|identity|startup|kibitzer]")
        scenarios = {args[1]: scenarios[args[1]]}
    for scenario in scenarios.values():
        print(json.dumps(scenario(), ensure_ascii=True))


if __name__ == "__main__":
    main()
