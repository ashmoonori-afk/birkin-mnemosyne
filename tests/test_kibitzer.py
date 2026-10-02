from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict

import pytest

from birkin_mnemosyne import VaultMemory
from birkin_mnemosyne.kibitzer import (
    KibitzerAdapter,
    RecallNudge,
    admit,
    render_recall,
    utf16_length,
)


def test_description_ranks_and_export_produces_described_note(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "guard.md").write_text(
        "---\ndescription: release publication approval guard\n---\n"
        "The final step needs a human decision.\n", encoding="utf-8",
    )
    adapter = KibitzerAdapter(vault)
    candidate, = adapter.select("publication approval", limit=1)
    assert candidate.path == "guard.md"
    assert candidate.description == "release publication approval guard"
    assert set(asdict(candidate)) == {"path", "description", "excerpt", "score"}
    exported = adapter.export(tmp_path / "export")
    assert exported == ("guard.md",)
    text = (tmp_path / "export" / "guard.md").read_text("utf-8")
    assert 'description: "release publication approval guard"' in text
    assert "The final step needs a human decision." in text
    with pytest.raises(FileExistsError):
        adapter.export(tmp_path / "export")


def test_root_system_archive_and_expiry_are_excluded_not_nested_system(tmp_path):
    for relative in ("system/private.md", "_archive/old.md", "reference/system/live.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ndescription: deploy guard\n---\ndeploy rule\n", "utf-8")
    (tmp_path / "expired.md").write_text(
        "---\nexpires_at: 2000-01-01\n---\ndeploy rule\n", "utf-8",
    )
    documents = KibitzerAdapter(tmp_path).documents()
    assert [d.path for d in documents] == ["reference/system/live.md"]


def test_exclusions_precede_cap_and_cache_sees_edits(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("First guard", "Release approval.")
    memory.write_note("Second guard", "Release approval.")
    adapter = KibitzerAdapter(tmp_path)
    first = adapter.select("release", limit=1)[0]
    second, = adapter.select("release", limit=1, surfaced=[first.path])
    assert second.path != first.path
    assert adapter.select("no-match-zebra") == ()
    memory.write_note("First guard", "Fresh distinct word: meridian.")
    assert adapter.select("meridian", limit=1)[0].path.endswith("first-guard.md")


def test_scores_are_ascending_and_excerpt_utf16_budget(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("Rocket rule", "rocket " + "🚀" * 150 + " release rule")
    memory.write_note("Release overview", "release details")
    candidates = KibitzerAdapter(tmp_path).select("rocket release")
    assert [c.score for c in candidates] == sorted(c.score for c in candidates)
    assert all(utf16_length(c.excerpt) <= 200 for c in candidates)


@pytest.mark.parametrize("hint", [
    "", " \t", "Two\nlines", "You should revise this.", "Never publish that.",
    "The memory is not relevant.", "이 기록을 확인하세요.", "기록을 공개하지 마라.",
    "Fact\x00invalid", "Fact\ud800invalid",
])
def test_admission_rejects_non_factual_shapes(tmp_path, hint):
    result = admit([RecallNudge("rule.md", hint)], offered=["rule.md"])
    assert result.accepted == ()
    assert len(result.rejected) == 1


def test_admission_uses_js_units_at_emoji_boundary():
    prefix = "The note records "
    hint = prefix + "x" * (200 - len(prefix) - 3) + "🚀."
    assert utf16_length(hint) == 200
    assert len(admit([RecallNudge("a.md", hint)], offered=["a.md"]).accepted) == 1
    assert admit([RecallNudge("a.md", hint + "x")], offered=["a.md"]).accepted == ()


def test_offered_path_surfaced_duplicate_and_cap_are_authoritative():
    fact = "The note records that releases require approval."
    result = admit([
        RecallNudge("forged.md", fact), RecallNudge("system/private.md", fact),
        RecallNudge("seen.md", fact), RecallNudge("a.md", fact),
        RecallNudge("a.md", fact), RecallNudge("b.md", fact), RecallNudge("c.md", fact),
    ], offered=["system/private.md", "seen.md", "a.md", "b.md", "c.md"],
        surfaced=["seen.md"], max_items=2)
    assert [n.path for n in result.accepted] == ["a.md", "b.md"]
    assert len(result.rejected) == 5


@pytest.mark.parametrize("path", ["../escape.md", "/absolute.md", "C:/outside.md", "C:relative.md"])
def test_even_offered_foreign_paths_are_not_admitted(path):
    fact = "The note records that releases require approval."
    assert admit([RecallNudge(path, fact)], offered=[path]).accepted == ()


def test_candidate_and_hint_redaction_never_emits_secret_like_values(tmp_path):
    fake = "sk-" + "fixture" * 8
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("Credential incident", "Credential incident token: " + fake)
    documents = KibitzerAdapter(tmp_path).documents()
    assert all(fake not in d.body + d.description for d in documents)
    result = admit([RecallNudge("a.md", "The note records token: " + fake)],
                   offered=["a.md"])
    assert result.accepted == ()
    assert result.rejected[0][1] == "secret-like"


def test_envelope_escapes_path_and_hint_as_data():
    path = 'reference/A & "B".md'
    hint = "The note records that A < B & C remains true."
    accepted = admit([RecallNudge(path, hint)], offered=[path]).accepted[0]
    block = render_recall(accepted)
    parsed = ET.fromstring(block)
    assert parsed.tag == "recalled-memory"
    assert parsed.attrib["source"] == f"[[{path}]]"
    assert hint in parsed.text
