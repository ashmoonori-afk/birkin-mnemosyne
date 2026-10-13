"""Nested vault discovery and zone-path contracts (mn-nested-vault).

The core scanner must see nested folders at any depth (14 shallow + 3 nested
notes), prune hidden/cache entries at every depth, never follow symlinks,
pick deterministic duplicate winners, and treat any ``_archive`` descendant
as archived. Zone names are complete POSIX relative parents; human-named and
nested folders are accepted with their spelling preserved, while traversal,
absolute/drive/UNC/backslash, hidden/cache components, controls and
Windows-invalid names are refused.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from birkin_mnemosyne import mnemosyne
from birkin_mnemosyne.consolidation import Answer, Consolidation
from birkin_mnemosyne.vault_paths import archived_zone

NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)

SHALLOW = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
]


def _note(vault: Path, rel: str, body: str = "body text") -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntitle: {p.stem}\n---\n\n{body}\n", encoding="utf-8")
    return p


def test_nested_archive_and_restore_keep_mixed_case_filename(tmp_path: Path) -> None:
    original = _note(tmp_path, "Work/Team/Original.MD")
    before = original.read_bytes()
    engine = mnemosyne.Mnemosyne(tmp_path)
    archived = engine.rezone("Original", "_archive")
    assert archived.relative_to(tmp_path).as_posix() == "_archive/Work/Team/Original.MD"
    assert archived.read_bytes() == before
    restored = engine.rezone("Original", "Work/Restored")
    assert restored.relative_to(tmp_path).as_posix() == "Work/Restored/Original.MD"
    assert restored.read_bytes() == before


def test_nested_review_journal_preserves_mixed_case_extensions(tmp_path: Path) -> None:
    paths = [_note(tmp_path, relative, "review every release before publication")
             for relative in ("Work/Team/first.MD", "Work/Team/second.Md")]
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in paths}
    review = Consolidation(tmp_path)
    question, = review.questions()
    receipt = review.apply(question, Answer(question.id, "drop-first"))
    assert (tmp_path / "_archive" / question.first.path).read_bytes() == before[question.first.path]
    assert review.undo(receipt.transaction_id).state == "undone"
    assert {relative: (tmp_path / relative).read_bytes() for relative in before} == before


# ---------------- recursive discovery ---------------------------------------


def test_recursive_scan_finds_fourteen_shallow_and_three_nested(tmp_path):
    vault = tmp_path
    for i, name in enumerate(SHALLOW):
        _note(vault, f"{name}.md" if i % 2 == 0 else f"zones/{name}.md")
    _note(vault, "projects/active/roadmap.md", "nested roadmap")
    _note(vault, "knowledge/2024/history.md", "nested history")
    _note(vault, "notes/deep/deeper/design.md", "deeply nested design")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    entries = eng.entries()
    assert len(entries) == 17
    for name in SHALLOW:
        assert name in entries
    assert entries["roadmap"]["rel"] == "projects/active/roadmap.md"
    assert entries["roadmap"]["zone"] == "projects/active"
    assert entries["history"]["rel"] == "knowledge/2024/history.md"
    assert entries["history"]["zone"] == "knowledge/2024"
    assert entries["design"]["rel"] == "notes/deep/deeper/design.md"
    assert entries["design"]["zone"] == "notes/deep/deeper"


def test_scan_prunes_hidden_and_cache_dirs_at_every_depth(tmp_path):
    vault = tmp_path
    _note(vault, "visible.md", "keep me")
    for rel in (
        ".secret.md",
        ".obsidian/scratch.md",
        "node_modules/direct.md",
        "node_modules/pkg/note.md",
        "__pycache__/direct.md",
        "projects/.git/notes.md",
        "projects/node_modules/inner.md",
        "a/b/__pycache__/deep.md",
        "a/b/.hidden-note.md",
        "a/.obsidian/x.md",
    ):
        _note(vault, rel, "pruned body")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    assert set(eng.entries()) == {"visible"}


def test_scan_never_follows_symlinks(tmp_path):
    vault = tmp_path
    _note(vault, "real.md", "real body")
    (vault / "linked-dir").mkdir()
    _note(vault, "linked-dir/inner.md", "inside")
    try:
        (vault / "alias.md").symlink_to(vault / "real.md")
        (vault / "dir-link").symlink_to(vault / "linked-dir", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not supported here")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    assert eng.resolve_rel("real") == "real.md"
    assert eng.resolve_rel("alias") is None
    assert eng.note_meta("inner") is not None  # the real dir's file
    assert "dir-link/inner.md" not in [e["rel"] for e in eng.entries().values()]


# ---------------- duplicate stems -------------------------------------------


def test_duplicate_stems_keep_newest_mtime_and_warn(tmp_path, caplog):
    vault = tmp_path
    older = _note(vault, "notes/dup.md")
    _note(vault, "projects/dup.md")
    t = older.stat().st_mtime - 200
    os.utime(older, (t, t))
    eng = mnemosyne.Mnemosyne(vault)
    with caplog.at_level(logging.WARNING, logger="birkin_mnemosyne.mnemosyne"):
        eng.refresh()
    assert eng.resolve_rel("dup") == "projects/dup.md"
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "dup" in joined and "projects/dup.md" in joined
    assert "notes/dup.md" in joined  # the loser is named too


def test_duplicate_ties_break_on_relative_path(tmp_path):
    vault = tmp_path
    a = _note(vault, "z-zone/dup.md")
    _note(vault, "a-zone/dup.md")
    _note(vault, "m-zone/dup.md")
    t = a.stat().st_mtime
    for p in (
        vault / "z-zone/dup.md",
        vault / "a-zone/dup.md",
        vault / "m-zone/dup.md",
    ):
        os.utime(p, (t, t))
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    assert eng.resolve_rel("dup") == "a-zone/dup.md"
    assert eng._scan()["dup"][0] == "a-zone/dup.md"


def test_note_written_keeps_the_duplicate_winner(tmp_path):
    vault = tmp_path
    winner = _note(vault, "a-zone/dup.md")
    loser = _note(vault, "b-zone/dup.md")
    future = winner.stat().st_mtime + 4000
    os.utime(winner, (future, future))
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    assert eng.resolve_rel("dup") == "a-zone/dup.md"

    # a targeted write to the LOSING path must not steal the selected entry
    loser.write_text("---\ntitle: dup\n---\nloser supersedes\n", encoding="utf-8")
    eng.note_written(loser)
    notes = eng._notes
    assert notes is not None and notes["dup"]["rel"] == "a-zone/dup.md"
    assert eng.resolve_rel("dup") == "a-zone/dup.md"

    # writing the WINNER path still updates the entry in place
    winner.write_text("---\ntitle: dup\n---\nfresh winner body\n", encoding="utf-8")
    eng.note_written(winner)
    meta = eng.note_meta("dup")
    assert meta is not None
    assert meta["rel"] == "a-zone/dup.md"
    assert meta["summary"] == "fresh winner body"


# ---------------- cache / read paths ----------------------------------------


def test_fresh_engine_reads_nested_cache_without_reparsing(tmp_path, monkeypatch):
    vault = tmp_path
    for rel in ("root.md", "projects/active/nested.md", "deep/a/b/c.md"):
        _note(vault, rel, "shared cached body")
    mnemosyne.Mnemosyne(vault).rebuild()

    def boom(path, rel):
        raise AssertionError(f"re-parsed {rel}")

    monkeypatch.setattr(mnemosyne, "_note_entry", boom)
    eng = mnemosyne.Mnemosyne(vault)
    entries = eng.entries()
    assert set(entries) == {"root", "nested", "c"}
    assert entries["nested"]["zone"] == "projects/active"
    assert eng.resolve_rel("c") == "deep/a/b/c.md"


# ---------------- archive discovery / active filters -------------------------


def test_nested_archive_keeps_subpath_and_queries(tmp_path):
    vault = tmp_path
    _note(vault, "keep.md", "shared body words")
    _note(vault, "projects/dead.md", "shared body words")
    _note(vault, "knowledge/yearly.md", "shared body words")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    assert {h["slug"] for h in eng.search("shared", now=NOW)} == {
        "keep",
        "dead",
        "yearly",
    }

    eng.rezone("dead", mnemosyne.ARCHIVE_ZONE)
    meta = eng.note_meta("dead")
    assert meta is not None
    assert meta["rel"] == "_archive/projects/dead.md"
    assert meta["zone"] == "_archive/projects"
    assert archived_zone(meta["zone"])

    # archived descendants are hidden from active search, include_archive
    # still shows them, and the archive root zone finds every descendant
    assert {h["slug"] for h in eng.search("shared", now=NOW)} == {"keep", "yearly"}
    assert {h["slug"] for h in eng.search("shared", now=NOW, include_archive=True)} == {
        "keep",
        "dead",
        "yearly",
    }
    assert {
        h["slug"] for h in eng.search("shared", now=NOW, zone=mnemosyne.ARCHIVE_ZONE)
    } == {"dead"}

    # a legacy flat archive keeps the old one-level shape and fallback
    eng.rezone("keep", mnemosyne.ARCHIVE_ZONE)
    keep_meta = eng.note_meta("keep")
    assert keep_meta is not None
    assert keep_meta["rel"] == "_archive/keep.md"
    assert keep_meta["zone"] == mnemosyne.ARCHIVE_ZONE

    # restore returns the nested note to its original parent
    eng.rezone("dead", "projects")
    dead_meta = eng.note_meta("dead")
    assert dead_meta is not None
    assert dead_meta["rel"] == "projects/dead.md"


def test_stale_skips_nested_archive_descendants(tmp_path):
    vault = tmp_path
    _note(vault, "live.md")
    _note(vault, "projects/dead.md")
    _note(vault, "_archive/projects/old.md")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    old = {
        "strength": 1.0,
        "stability": 7.0,
        "access_count": 1,
        "last_access": (NOW - timedelta(days=200)).isoformat(),
    }
    for s in ("live", "dead", "old"):
        eng.set_dynamics(s, dict(old))
    stale = {s["slug"] for s in eng.stale(now=NOW)}
    assert stale == {"live", "dead"}  # archived skipped


# ---------------- zone normalization ----------------------------------------


@pytest.mark.parametrize(
    "raw, want",
    [
        ("", ""),
        ("inbox", ""),
        ("Inbox", ""),
        ("Projects", "projects"),  # legacy one component
        ("projects", "projects"),
        ("deep-work", "deep-work"),
        ("deep_work", "deep_work"),  # human-named folder
        ("Projects/Active", "Projects/Active"),
        ("My Projects/Deep Work", "My Projects/Deep Work"),
        ("knowledge/2024/reviews", "knowledge/2024/reviews"),
        ("People/김광훈", "People/김광훈"),
    ],
)
def test_normalize_zone_expands_canonical_forms(raw, want):
    assert mnemosyne.normalize_zone(raw) == want


@pytest.mark.parametrize(
    "bad",
    [
        "/",
        "/abs",
        "abs/",
        "a//b",
        "a/./b",
        "a/../b",
        "../x",
        ".",
        "..",
        ".hidden",
        "node_modules",
        "__pycache__",
        ".obsidian",
        "a/.git/b",
        "a/node_modules/c",
        "a/__pycache__/d",
        "a/.obsidian/b",
        "a\\b",
        "C:/x",
        "C:\\x",
        "\\\\server\\share",
        "A:b",
        "a<b",
        "a>b",
        'a"b',
        "a|b",
        "a?b",
        "a*b",
        "a\tb",
        "a\nb",
        "a/name /x",
        "a /b",
        "a/name.",
    ],
)
def test_normalize_zone_rejects_invalid_paths(bad):
    with pytest.raises(ValueError, match="invalid zone name"):
        mnemosyne.normalize_zone(bad)


def test_normalize_zone_refuses_archive_without_allowance():
    for bad in ("_archive", "a/_archive/b"):
        with pytest.raises(ValueError):
            mnemosyne.normalize_zone(bad)


def test_normalize_zone_allows_archive_components_when_requested():
    assert mnemosyne.normalize_zone("_archive", allow_archive=True) == "_archive"
    assert (
        mnemosyne.normalize_zone("knowledge/_archive", allow_archive=True)
        == "knowledge/_archive"
    )
    assert (
        mnemosyne.normalize_zone("_archive/knowledge", allow_archive=True)
        == "_archive/knowledge"
    )


# ---------------- nested zones through the engine ----------------------------


def test_search_nested_zone_filter_and_spaced_folders(tmp_path):
    vault = tmp_path
    _note(vault, "Projects/Active Things/roadmap.md", "nested planning doc")
    _note(vault, "Knowledge/2024/review.md", "yearly planning doc")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    roadmap = eng.note_meta("roadmap")
    assert roadmap is not None
    assert roadmap["zone"] == "Projects/Active Things"
    assert [
        h["slug"]
        for h in eng.search("planning", now=NOW, zone="Projects/Active Things")
    ] == ["roadmap"]
    assert [
        h["slug"] for h in eng.search("planning", now=NOW, zone="Knowledge/2024")
    ] == ["review"]


def test_rezone_to_nested_and_human_named_zones(tmp_path):
    vault = tmp_path
    _note(vault, "knowledge/move.md", "moving around")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    eng.rezone("move", "projects/2024/planning")
    meta = eng.note_meta("move")
    assert meta is not None
    assert meta["rel"] == "projects/2024/planning/move.md"
    assert meta["zone"] == "projects/2024/planning"
    assert (vault / "projects/2024/planning/move.md").is_file()
    eng.rezone("move", "Deep Work")
    moved = eng.note_meta("move")
    assert moved is not None
    assert moved["rel"] == "Deep Work/move.md"


def test_rezone_rejects_windows_shaped_zones(tmp_path):
    vault = tmp_path
    _note(vault, "knowledge/move.md", "moved around")
    eng = mnemosyne.Mnemosyne(vault)
    eng.refresh()
    for bad in ("C:\\zones\\move", "zones\\deep\\x", "a\\b", "\\\\server\\share"):
        with pytest.raises(ValueError, match="invalid zone name"):
            eng.rezone("move", bad)
