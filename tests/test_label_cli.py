"""The label CLI proves preview/apply/undo and replacements through real processes."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

import pytest

import birkin_mnemosyne
from birkin_mnemosyne.labels import read_labels

# Explicit byte literals so no platform newline translation can touch them.
ALPHA = b"---\ntitle: Alpha\n---\nBody of Alpha.\n"
MANUAL = b'---\nlabels: ["manual:keep"]\n---\nManual body.\n'
EMPTY = b"---\nlabels: []\n---\nEmpty body.\n"
OWNED = b'---\nlabels: ["project:Zed"]\n---\nOwner body.\n'
GAMMA = "---\ntitle: 감마\n---\n한국어 규칙\n".encode("utf-8")


class LabelPayload(TypedDict):
    mode: str
    ok: bool
    notes: int
    changed: int
    warnings: list[str]
    undo_transaction: str | None
    label_counts: list[list[str | int]]


decode_report: Callable[[str], LabelPayload] = json.loads


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    module_file = birkin_mnemosyne.__file__
    assert module_file is not None
    code = """
import pathlib
import runpy
import sys
import birkin_mnemosyne

expected = pathlib.Path(sys.argv.pop(1)).resolve()
actual = birkin_mnemosyne.__file__
if actual is None or pathlib.Path(actual).resolve() != expected:
    print(f"CLI package origin mismatch: expected {expected}, got {actual}", file=sys.stderr)
    raise SystemExit(93)
runpy.run_module("birkin_mnemosyne.memory_index_cli", run_name="__main__", alter_sys=True)
"""
    return subprocess.run(
        [sys.executable, "-c", code, str(Path(module_file).resolve()), *args],
        cwd=cwd, capture_output=True, check=False,
    )


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def notes(root: Path) -> dict[str, bytes]:
    return {relative: data for relative, data in tree(root).items()
            if relative.endswith(".md")}


def write(root: Path, relative: str, raw: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def label_report(result: subprocess.CompletedProcess[bytes]) -> LabelPayload:
    assert result.returncode == 0, result.stderr
    return decode_report(result.stdout.decode("utf-8"))


def seed_vault(root: Path) -> None:
    write(root, "notes/alpha.md", ALPHA)
    write(root, "notes/manual.md", MANUAL)
    write(root, "notes/empty.md", EMPTY)


def test_label_preview_is_read_only_json_and_exit_zero(tmp_path: Path) -> None:
    # Given a vault with one annotatable note and two user-owned label fields.
    root = tmp_path / "vault"
    seed_vault(root)
    before = tree(tmp_path)

    # When the default label command previews.
    result = run_cli("--vault", str(root), "label", cwd=tmp_path)

    # Then one read-only JSON report names the plan and nothing was written.
    assert result.returncode == 0, result.stderr
    report = label_report(result)
    assert report["mode"] == "preview" and report["ok"] is True
    assert report["notes"] == 3 and report["changed"] == 1
    assert report["warnings"] == []
    assert report["undo_transaction"] is None
    assert report["label_counts"] == [
        ["manual:keep", 1],
        ["zone:notes", 1],
    ]
    assert tree(tmp_path) == before
    assert not (root / ".mnemosyne-reviews").exists()
    assert not (root / ".mnemosyne-mcp.lock").exists()


def test_label_apply_journals_and_handoff_undo_restores_exact_bytes(
    tmp_path: Path,
) -> None:
    # Given a vault whose manual and empty fields are user-owned.
    root = tmp_path / "vault"
    seed_vault(root)
    before = notes(root)

    # When apply journals the one annotation.
    report = label_report(run_cli(
        "--vault", str(root), "label", "--apply", cwd=tmp_path))
    assert report["mode"] == "applied" and report["ok"] is True
    assert report["changed"] == 1
    assert report["undo_transaction"]
    assert (root / "notes/manual.md").read_bytes() == MANUAL
    assert (root / "notes/empty.md").read_bytes() == EMPTY
    assert read_labels((root / "notes/alpha.md").read_bytes()) == ("zone:notes",)

    # When the shared journal is undone through the existing handoff undo.
    undone = run_cli("--vault", str(root), "handoff", "undo",
                     "--transaction", report["undo_transaction"], cwd=tmp_path)

    # Then the exact original bytes return through the existing transaction.
    assert undone.returncode == 0, undone.stderr
    receipt = json.loads(undone.stdout.decode("utf-8"))
    assert receipt["state"] == "undone"
    assert notes(root) == before


def test_label_apply_twice_is_byte_stable_noop(tmp_path: Path) -> None:
    # Given a vault annotated once.
    root = tmp_path / "vault"
    seed_vault(root)
    first = label_report(run_cli(
        "--vault", str(root), "label", "--apply", cwd=tmp_path))
    assert first["changed"] == 1 and first["undo_transaction"]
    image = tree(tmp_path)

    # When the same apply runs again without an explicit replacement.
    repeat = label_report(run_cli(
        "--vault", str(root), "label", "--apply", cwd=tmp_path))

    # Then nothing changes: existing fields (including the empty field) stay
    # user-owned and no new transaction is committed.
    assert repeat["ok"] is True and repeat["changed"] == 0
    assert repeat["undo_transaction"] is None
    assert tree(tmp_path) == image


def test_repeated_paths_restrict_selection_and_warn_for_missing(
    tmp_path: Path,
) -> None:
    # Given a vault and a requested subset.
    root = tmp_path / "vault"
    seed_vault(root)

    # When selection is restricted to one note plus one absent path.
    preview = label_report(run_cli(
        "--vault", str(root), "label",
        "--path", "notes/alpha.md", "--path", "nogo.md", cwd=tmp_path))
    applied = label_report(run_cli(
        "--vault", str(root), "label", "--apply",
        "--path", "notes/alpha.md", cwd=tmp_path))

    # Then only the requested note is planned and the missing path warns.
    assert preview["notes"] == 1 and preview["changed"] == 1
    assert any("nogo.md" in warning for warning in preview["warnings"])
    assert applied["changed"] == 1
    assert (root / "notes/manual.md").read_bytes() == MANUAL
    assert read_labels((root / "notes/alpha.md").read_bytes()) == ("zone:notes",)


def test_repeated_explicit_labels_replace_and_normalize(tmp_path: Path) -> None:
    # Given one plain note.
    root = tmp_path / "vault"
    write(root, "a.md", ALPHA)

    # When an explicit replacement is supplied through repeated --label.
    preview = label_report(run_cli(
        "--vault", str(root), "label",
        "--label", "Project:Zed", "--label", "Person:Jane", cwd=tmp_path))
    applied = label_report(run_cli(
        "--vault", str(root), "label", "--apply",
        "--label", "Project:Zed", "--label", "Person:Jane", cwd=tmp_path))

    # Then the labels are normalized, sorted and written as the replacement.
    assert preview["changed"] == 1
    assert preview["label_counts"] == [["person:Jane", 1], ["project:Zed", 1]]
    assert applied["changed"] == 1
    assert read_labels((root / "a.md").read_bytes()) == \
        ("person:Jane", "project:Zed")


def test_clear_preview_writes_nothing_and_apply_is_undoable(tmp_path: Path) -> None:
    # Given a user-owned manual label worth clearing.
    root = tmp_path / "vault"
    write(root, "owned.md", OWNED)
    before = tree(tmp_path)

    # When clearing is previewed first.
    preview = label_report(run_cli(
        "--vault", str(root), "label", "--clear-labels", cwd=tmp_path))

    # Then the preview names the clear but writes nothing.
    assert preview["mode"] == "preview" and preview["changed"] == 1
    assert tree(tmp_path) == before

    # When the clear is applied and then undone.
    applied = label_report(run_cli(
        "--vault", str(root), "label", "--clear-labels", "--apply", cwd=tmp_path))
    assert applied["mode"] == "applied" and applied["changed"] == 1
    assert applied["undo_transaction"] is not None
    assert read_labels((root / "owned.md").read_bytes()) == ()

    undone = run_cli("--vault", str(root), "handoff", "undo",
                     "--transaction", applied["undo_transaction"], cwd=tmp_path)
    assert undone.returncode == 0, undone.stderr

    # Then the manual label comes back byte-exact.
    assert (root / "owned.md").read_bytes() == OWNED


def test_label_and_clear_labels_are_incompatible(tmp_path: Path) -> None:
    # Given a vault whose bytes must stay unchanged.
    root = tmp_path / "vault"
    write(root, "a.md", ALPHA)
    before = tree(tmp_path)

    # When both replacement forms are combined.
    result = run_cli("--vault", str(root), "label",
                     "--label", "project:X", "--clear-labels", cwd=tmp_path)

    # Then the request is refused before any scan or write.
    assert result.returncode == 2
    assert result.stderr
    assert tree(tmp_path) == before


@pytest.mark.parametrize("argument", ["no-colon", ""])
def test_invalid_explicit_label_exits_two_without_writes(
    tmp_path: Path, argument: str,
) -> None:
    root = tmp_path / "vault"
    write(root, "a.md", ALPHA)
    before = tree(tmp_path)

    result = run_cli("--vault", str(root), "label",
                     "--label", argument, cwd=tmp_path)

    assert result.returncode == 2
    assert result.stderr
    assert tree(tmp_path) == before


def test_unsafe_requested_path_exits_two_without_writes(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    write(root, "a.md", ALPHA)
    before = tree(tmp_path)

    result = run_cli("--vault", str(root), "label",
                     "--path", "../escape.md", cwd=tmp_path)

    assert result.returncode == 2
    assert result.stderr
    assert tree(tmp_path) == before


def test_label_on_absent_vault_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "vault"

    preview = label_report(run_cli("--vault", str(root), "label", cwd=tmp_path))
    applied = label_report(run_cli(
        "--vault", str(root), "label", "--apply", cwd=tmp_path))

    assert preview["notes"] == 0 and preview["changed"] == 0
    assert applied["mode"] == "applied" and applied["changed"] == 0
    assert applied["undo_transaction"] is None
    assert not root.exists() and not root.parent.exists()


def test_label_requires_vault(tmp_path: Path) -> None:
    result = run_cli("label", cwd=tmp_path)
    assert result.returncode == 2
    assert result.stderr


def test_label_output_is_utf8_even_when_host_encoding_is_ascii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "vault"
    write(root, "deep/gamma.md", GAMMA)
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")

    result = run_cli("--vault", str(root), "label", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    report = label_report(result)
    assert ["lang:ko", 1] in report["label_counts"]
