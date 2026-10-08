from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from birkin_mnemosyne.identity_reader import IdentityReader, IdentityReadError


def fixture(tmp_path, text):
    path = tmp_path / "AGENTS.md"
    path.write_bytes(text.encode("utf-8"))
    return path, IdentityReader(tmp_path)


def test_ranked_context_answers_current_section_not_obsolete_sibling(tmp_path):
    _, reader = fixture(tmp_path, (
        "# Agent\n## Conversation\nLanguage: Korean\n"
        "## Archive\nLanguage: English\n"
    ))
    result = reader.search("AGENTS.md", "Conversation language", limit=1)
    assert result.sections[0].heading == "Conversation"
    assert "Language: Korean" in result.context
    assert "Language: English" not in result.context
    assert not result.complete_file


def test_frontmatter_fences_and_setext_have_exact_source_spans(tmp_path):
    text = (
        "\ufeff---\r\ndescription: identity\r\n---\r\n"
        "Global rule precedes headings.\r\n"
        "Root\r\n====\r\n"
        "## Voice\r\nLanguage: Korean\r\n"
        "~~~~markdown\r\n## Fake\r\n~~~~\r\n"
        "Tools\r\n-----\r\nBuild: make\r\n"
        "```text\r\n# False\r\n```\r\n"
    )
    _, reader = fixture(tmp_path, text)
    result = reader.sections("AGENTS.md")
    assert [s.heading for s in result.sections] == ["Preamble", "Root", "Voice", "Tools"]
    lines = text.splitlines(keepends=True)
    for section in result.sections:
        assert section.text == "".join(lines[section.line_start - 1:section.line_end])
    assert reader.read_full("AGENTS.md").context == text


@pytest.mark.parametrize(("text", "headings"), [
    ("\ufeff# Root\nRule: live\n## Child\nBody\n", ["Root", "Child"]),
    ("\ufeff```\n# Fake\n```\n# Real\nBody\n", ["Preamble", "Real"]),
    ("\ufeffRoot\n====\nBody\n", ["Root"]),
])
def test_bom_syntax_keeps_raw_spans_and_revision(tmp_path, text, headings):
    _, reader = fixture(tmp_path, text)
    result = reader.read_full("AGENTS.md")
    assert [section.heading for section in result.sections] == headings
    assert result.context == text
    assert result.revision == hashlib.sha256(text.encode()).hexdigest()
    assert "".join(section.text for section in result.sections) == text
    lines = text.splitlines(keepends=True)
    for section in result.sections:
        assert section.text == "".join(lines[section.line_start - 1:section.line_end])


def test_global_preamble_is_included_but_no_match_stays_empty(tmp_path):
    _, reader = fixture(tmp_path, "Never publish credentials.\n## Tools\nBuild: make\n")
    result = reader.search("AGENTS.md", "Tools build", limit=1)
    assert "Never publish credentials." in result.context
    assert reader.search("AGENTS.md", "unfindable-zebra").context == ""


def test_body_edit_keeps_anchor_and_invalidates_revision(tmp_path):
    path, reader = fixture(tmp_path, "# Agent\n## Voice\nLanguage: Korean\n")
    before = reader.search("AGENTS.md", "Voice", limit=1)
    path.write_bytes(b"# Agent\n## Voice\nLanguage: Japanese\n")
    after = reader.search("AGENTS.md", "Voice", limit=1)
    assert after.sections[0].anchor == before.sections[0].anchor
    assert after.revision != before.revision
    assert "Japanese" in after.context
    with pytest.raises(IdentityReadError, match="stale"):
        reader.read_section("AGENTS.md", before.sections[0].anchor, before.revision)


def test_duplicate_heading_insertions_are_revision_bound(tmp_path):
    path, reader = fixture(tmp_path, "# One\n## Rule\nA\n# Two\n## Rule\nB\n")
    before = reader.sections("AGENTS.md")
    assert len({s.anchor for s in before.sections}) == len(before.sections)
    path.write_bytes(b"# One\n## Rule\nInserted\n## Rule\nA\n# Two\n## Rule\nB\n")
    with pytest.raises(IdentityReadError, match="stale"):
        reader.read_section("AGENTS.md", before.sections[1].anchor, before.revision)


def test_force_refresh_reads_bytes_even_with_identical_stat(tmp_path, monkeypatch):
    path, reader = fixture(tmp_path, "# Root\nValue: alpha\n")
    before = reader.read_full("AGENTS.md")
    stat = path.stat()
    path.write_bytes(b"# Root\nValue: omega\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    original_stat = Path.stat

    def preserved_stat(self, *args, **kwargs):
        return stat if self == path else original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", preserved_stat)
    assert reader.read_full("AGENTS.md").revision == before.revision
    assert "omega" in reader.read_full("AGENTS.md", force_refresh=True).context


def test_deletion_and_recreation_do_not_reuse_deleted_context(tmp_path):
    path, reader = fixture(tmp_path, "# Agent\nOwner: Mara\n")
    reader.read_full("AGENTS.md")
    path.unlink()
    with pytest.raises(FileNotFoundError):
        reader.read_full("AGENTS.md")
    path.write_bytes(b"# New agent\nOwner: Ivo\n")
    assert "Ivo" in reader.read_full("AGENTS.md").context


def test_full_section_can_include_child_rules_and_exceptions(tmp_path):
    _, reader = fixture(tmp_path, (
        "# Agent\n## Release\nApproval: required\n"
        "### Exceptions\nEmergency: approval still required\n"
        "## Other\nUnrelated: noise\n"
    ))
    catalog = reader.sections("AGENTS.md")
    release = next(s for s in catalog.sections if s.heading == "Release")
    result = reader.read_section("AGENTS.md", release.anchor, catalog.revision,
                                 include_children=True)
    assert "approval still required" in result.context
    assert "Unrelated: noise" not in result.context


def test_skipped_levels_and_unicode_keep_ancestry(tmp_path):
    _, reader = fixture(tmp_path, "# Agent\n#### 연락\n방식: 메시지\n")
    result = reader.search("AGENTS.md", "연락 방식", limit=1)
    assert result.sections[0].ancestry == ("Agent",)
    assert "방식: 메시지" in result.context


def test_path_escape_and_oversized_file_are_rejected(tmp_path):
    reader = IdentityReader(tmp_path)
    with pytest.raises(IdentityReadError, match="outside"):
        reader.read_full("../escape.md")
    (tmp_path / "big.md").write_bytes(b"x" * 1_048_577)
    with pytest.raises(IdentityReadError, match="budget"):
        reader.read_full("big.md")


def test_lru_total_source_budget_is_bounded(tmp_path):
    reader = IdentityReader(tmp_path)
    for i in range(5):
        (tmp_path / f"{i}.md").write_bytes(b"# Root\nfield: content\n")
        reader.read_full(f"{i}.md")
    assert len(reader._cache) == 4
    assert sum(d.fingerprint[2] for d in reader._cache.values()) <= 1_048_576


@pytest.mark.parametrize("relative", [
    ".mnemosyne-reviews/x.json", ".env", "sub/.hidden.md", "sub/../.env", "./.env",
])
def test_hidden_and_dot_parts_are_refused(tmp_path, relative):
    for target in (".mnemosyne-reviews/x.json", ".env", "sub/.hidden.md"):
        (tmp_path / target).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / target).write_text("# Secret\nbody\n", encoding="utf-8")
    reader = IdentityReader(tmp_path)
    with pytest.raises(IdentityReadError) as caught:
        reader.read_full(relative)
    assert str(tmp_path) not in str(caught.value)


def test_normal_files_in_subdirectories_still_read(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "AGENTS.md").write_text("# Agent\nrule\n", encoding="utf-8")
    assert "rule" in IdentityReader(tmp_path).read_full("sub/AGENTS.md").context


def test_symlink_to_hidden_file_is_refused(tmp_path):
    (tmp_path / ".env").write_text("# Secret\nbody\n", encoding="utf-8")
    try:
        (tmp_path / "link.md").symlink_to(tmp_path / ".env")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported here")
    with pytest.raises(IdentityReadError, match="refusing hidden path 'link.md'"):
        IdentityReader(tmp_path).read_full("link.md")
