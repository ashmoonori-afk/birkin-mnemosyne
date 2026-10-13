"""Recursive init/integrity discovery keeps nested notes and excludes infra."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from birkin_mnemosyne.memory_index import MemoryIndexError
from birkin_mnemosyne.memory_index_integrity import check_index
from birkin_mnemosyne.memory_index_migration import split_note
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_notes import inventory
from birkin_mnemosyne.onboarding_plan import plan_init


def seed_tree(root: Path) -> Path:
    for relative in (
        "alpha/a1.md", "alpha/a2.md", "beta/b1.md",
        "knowledge/nested/k1.md", "knowledge/nested/deeper/k2.md",
        "projects/deep/d1.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(f"# {relative}\nbody\n".encode())
    return root


def excluded_tree(root: Path) -> Path:
    for relative in (
        ".hidden/old.md",
        "knowledge/.temporary.md",
        "knowledge/nested/_archive/old.md",
        "_archive/old.md",
        "knowledge/node_modules/pkg/packed.md",
        "knowledge/nested/__pycache__/cached.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(f"excluded {relative}\n".encode())
    return root


def test_recursive_traversal_finds_every_depth_and_skips_archive_everywhere(
    tmp_path: Path,
) -> None:
    # Given nested notes plus archives and hidden files at mixed depths.
    root = seed_tree(tmp_path)
    _ = excluded_tree(root)

    # When the init inventory and the integrity audit scan the tree.
    sources = inventory(root)
    checked = check_index(root)

    # Then every visible nested note is present and infra never leaks.
    assert {source.path for source in sources} == {
        "alpha/a1.md", "alpha/a2.md", "beta/b1.md",
        "knowledge/nested/k1.md", "knowledge/nested/deeper/k2.md",
        "projects/deep/d1.md",
    }
    assert checked.documents == 6
    assert checked.orphan_documents == (
        "alpha/a1.md", "alpha/a2.md", "beta/b1.md",
        "knowledge/nested/deeper/k2.md", "knowledge/nested/k1.md",
        "projects/deep/d1.md",
    )


def test_node_modules_and_pycache_are_excluded_at_every_depth(tmp_path: Path) -> None:
    # Given cache/package trees at depth beside visible nested notes.
    root = seed_tree(tmp_path)
    for relative in (
        "knowledge/node_modules/pkg/packed.md",
        "knowledge/nested/__pycache__/cached.md",
        "projects/deep/node_modules/installed.md",
        "beta/__pycache__/compiled.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(f"excluded {relative}\n".encode())

    # When both discovery surfaces run.
    paths = tuple(source.path for source in inventory(root))
    checked = check_index(root)

    # Then only the six visible notes are reported anywhere.
    assert paths == (
        "alpha/a1.md", "alpha/a2.md", "beta/b1.md",
        "knowledge/nested/deeper/k2.md", "knowledge/nested/k1.md",
        "projects/deep/d1.md",
    )
    assert checked.documents == 6
    assert checked.orphan_documents == paths


def test_linked_nested_sources_stay_refused(tmp_path: Path) -> None:
    # Given a symlinked file and a symlinked directory below the root.
    root = seed_tree(tmp_path)
    (root / "knowledge" / "alias.md").symlink_to(root / "alpha" / "a1.md")
    (root / "knowledge" / "linked").symlink_to(
        root / "projects", target_is_directory=True)

    # When the init inventory scans the tree, then any link is refused.
    with pytest.raises(MemoryIndexError):
        _ = inventory(root)


def test_inventory_is_deterministic_across_duplicate_timestamps(
    tmp_path: Path,
) -> None:
    # Given two notes in one zone with identical mtimes.
    root = seed_tree(tmp_path)
    first, second = root / "alpha" / "a1.md", root / "alpha" / "a2.md"
    stamp = first.stat()
    os.utime(second, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    # When the tree is inventoried, then both exact POSIX identities survive.
    assert [source.path for source in inventory(root)] == [
        "alpha/a1.md", "alpha/a2.md", "beta/b1.md",
        "knowledge/nested/deeper/k2.md", "knowledge/nested/k1.md",
        "projects/deep/d1.md",
    ]


def test_split_receipt_protection_survives_recursive_discovery(
    tmp_path: Path,
) -> None:
    # Given a nested source bound to an existing split receipt.
    root = seed_tree(tmp_path)
    source = "knowledge/nested/k1.md"
    split = split_note(root, source, apply=True)
    protected = (source, *(topic.document for topic in split.topics))
    before = {name: (root / name).read_bytes() for name in protected}

    # When init plans and applies labeling across the recursive tree.
    report = run_init(plan_init(root), apply=True)

    # Then receipt-bound bytes stay exact and no additions target them.
    assert report.ok
    assert {name: (root / name).read_bytes() for name in protected} == before
    assert all(not item.frontmatter_additions
               for item in report.sources if item.path in protected)


def test_index_routes_keep_full_nested_document_paths(tmp_path: Path) -> None:
    # Given nested notes with an opted-in grouping namespace.
    root = seed_tree(tmp_path)
    _ = (root / "knowledge" / "nested" / "k1.md").write_bytes(
        b"---\nproject: Zed\n---\nbody\n")

    # When the plan groups by the project namespace.
    plan = plan_init(root, group_by_label="project")

    # Then every route points at the exact nested POSIX path.
    routed = {entry.document for entry in plan.routes}
    assert "knowledge/nested/k1.md" in routed
    assert "knowledge/nested/deeper/k2.md" in routed
    assert "projects/deep/d1.md" in routed
    assert "Zed" in {entry.trigger for entry in plan.routes}
    for entry in plan.routes:
        assert "/" not in entry.document or ".." not in entry.document