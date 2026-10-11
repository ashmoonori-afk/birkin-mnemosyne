"""The installed CLI offers a no-write plan and explicitly verified apply."""

import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest


def cli(*args: str, cwd: Path, console: bool = False) -> subprocess.CompletedProcess[bytes]:
    if console:
        suffix = ".exe" if os.name == "nt" else ""
        command = [str(Path(sysconfig.get_path("scripts")) / ("mnemosyne" + suffix))]
    else:
        command = [sys.executable, "-m", "birkin_mnemosyne.memory_index_cli"]
    return subprocess.run([*command, *args], cwd=cwd, capture_output=True, check=False)


def files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_console_empty_preview_creates_no_vault(tmp_path: Path) -> None:
    # Given an absent vault path containing spaces and CJK characters.
    root = tmp_path / "메모 日本語"

    # When the installed console command previews initialization.
    result = cli("init", "--vault", str(root), cwd=tmp_path, console=True)

    # Then it reports a plan without creating the directory.
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "preview" and payload["verification"] == "planned"
    assert payload["notes"] == payload["topics"] == 0
    assert not root.exists()


def test_console_empty_apply_verifies_and_opts_in(tmp_path: Path) -> None:
    # Given an absent vault.
    root = tmp_path / "vault"

    # When the installed console command receives explicit apply.
    result = cli("init", "--vault", str(root), "--apply", cwd=tmp_path, console=True)

    # Then the resident INDEX is really verified and persists.
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] and payload["verification"] == "passed"
    assert payload["verification_scope"] == "resident-index"
    assert (root / ".mnemosyne-memory-index" / "index.json").is_file()


def test_legacy_vault_prefix_and_default_current_vault_are_supported(tmp_path: Path) -> None:
    # Given an existing vault with an ordinary note.
    (tmp_path / "policy.md").write_bytes(b"Approval is required.")
    before = files(tmp_path)

    # When the original dispatcher receives its existing prefix syntax.
    result = cli("--vault", str(tmp_path), "init", cwd=tmp_path)

    # Then the same preview surface works without file changes.
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["notes"] == 1
    assert files(tmp_path) == before


def test_init_without_vault_uses_current_directory_read_only(tmp_path: Path) -> None:
    # Given one note in the current directory.
    (tmp_path / "policy.md").write_bytes(b"Approval is required.")
    before = files(tmp_path)

    # When init omits the optional vault argument.
    result = cli("init", cwd=tmp_path)

    # Then the current directory is previewed without writing.
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["notes"] == 1
    assert files(tmp_path) == before


@pytest.mark.parametrize("args", [
    ("--vault", ".", "init", "--vault", "."),
    ("init", "--vault", ".", "--vault", "."),
    ("init", "--vault=.", "--vault=."),
    ("init", "--max-tokens", "0"),
    ("init", "--import", "."),
])
def test_invalid_init_input_exits_two_without_file_changes(
    tmp_path: Path, args: tuple[str, ...],
) -> None:
    # Given a vault whose bytes must stay unchanged.
    (tmp_path / "policy.md").write_bytes(b"Owner policy.")
    before = files(tmp_path)

    # When an invalid or ambiguous request reaches the command boundary.
    result = cli(*args, cwd=tmp_path)

    # Then it refuses without creating locks, INDEX or derived documents.
    assert result.returncode == 2 and result.stderr
    assert files(tmp_path) == before


def test_console_multilingual_plan_is_utf8_with_ascii_host_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given non-ASCII Markdown under an ASCII host output default.
    (tmp_path / "日本語.md").write_bytes("한국어 원문과 日本語のメモ".encode())
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")

    # When the installed console command previews the note.
    result = cli("init", cwd=tmp_path, console=True)

    # Then its machine-readable output retains the actual Unicode path.
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["sources"][0]["path"] == "日本語.md"
