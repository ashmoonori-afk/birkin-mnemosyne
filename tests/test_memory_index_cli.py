"""The INDEX CLI proves its contracts through real subprocesses and files."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from birkin_mnemosyne import MemoryIndex
from birkin_mnemosyne.startup_coverage import digest

REPO_ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\| (\d+) \|")

# Explicit UTF-8 bytes: BOM + CRLF + a unicode heading + a final line with no
# trailing newline. Never re-encoded through platform newline translation.
SOURCE = (
    "\ufeff---\r\ntitle: Original\r\n---\r\n\r\n# Rules\r\n"
    "Owner: Fictional operator\r\n\r\n## Deploy\r\n"
    "Rule: keep approval.\r\n"
    "## 연락\r\nRule: 비동기 메시지\r\n"
    "Last line without newline"
).encode("utf-8")


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "birkin_mnemosyne.memory_index_cli", *args],
        cwd=cwd, capture_output=True, env=env, check=False,
    )


def note(root: Path, raw: bytes = SOURCE) -> Path:
    path = root / "memory.md"
    path.write_bytes(raw)
    return path


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def data_rows(stdout: bytes) -> list[int]:
    return [int(m.group(1)) for line in stdout.decode("utf-8").splitlines()
            if (m := ROW.match(line))]


def test_check_on_clean_vault_is_json_ok_and_exit_zero(tmp_path):
    before = tree(tmp_path)
    result = run_cli("--vault", str(tmp_path), "check", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["enabled"] is False
    assert payload["entries"] == 0
    assert payload["orphan_documents"] == []
    assert payload["dangling_entries"] == []
    assert payload["errors"] == []
    assert tree(tmp_path) == before


def test_check_reports_orphan_and_dangling_and_exits_one(tmp_path):
    note(tmp_path)
    (tmp_path / "orphan.md").write_bytes(b"Unindexed rule.")
    MemoryIndex(tmp_path).register("main task", "memory.md")
    (tmp_path / "memory.md").unlink()
    before = tree(tmp_path)

    result = run_cli("--vault", str(tmp_path), "check", cwd=tmp_path)
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["orphan_documents"] == ["orphan.md"]
    assert payload["dangling_entries"] == [{"trigger": "main task", "document": "memory.md"}]
    assert tree(tmp_path) == before


def test_split_preview_writes_nothing_and_maps_every_original_line(tmp_path):
    note(tmp_path)
    before = tree(tmp_path)
    result = run_cli("--vault", str(tmp_path), "split", "memory.md", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert tree(tmp_path) == before
    assert "mode: preview" in result.stdout.decode("utf-8")
    assert data_rows(result.stdout) == list(
        range(1, len(SOURCE.decode("utf-8").splitlines(keepends=True)) + 1))


def test_split_apply_preserves_bytes_and_checks_clean(tmp_path):
    path = note(tmp_path)
    result = run_cli("--vault", str(tmp_path), "split", "memory.md", "--apply", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    stdout = result.stdout.decode("utf-8")

    assert f"sha256: {digest(SOURCE)}" in stdout
    assert f"bytes: {len(SOURCE)}" in stdout
    assert "mode: applied" in stdout
    assert data_rows(result.stdout) == list(
        range(1, len(SOURCE.decode("utf-8").splitlines(keepends=True)) + 1))

    receipt_rel = next(line.split(": ", 1)[1] for line in stdout.splitlines()
                       if line.startswith("receipt: "))
    journal_rel = next(line.split(": ", 1)[1] for line in stdout.splitlines()
                       if line.startswith("journal: "))
    receipt = json.loads((tmp_path / receipt_rel).read_bytes().decode("utf-8"))
    assert (tmp_path / journal_rel).is_file()
    assert path.read_bytes() != SOURCE

    recovered = b"".join(
        (tmp_path / topic["document"]).read_bytes()[topic["prefix_bytes"]:]
        for topic in receipt["topics"])
    assert recovered == SOURCE
    assert receipt["source_sha256"] == digest(SOURCE)

    assert run_cli("--vault", str(tmp_path), "check", cwd=tmp_path).returncode == 0


def test_split_unsafe_source_exits_two_without_writes(tmp_path):
    while_clean = tree(tmp_path)
    result = run_cli("--vault", str(tmp_path), "split", "../escape.md", cwd=tmp_path)
    assert result.returncode == 2
    assert result.stderr.strip()
    assert tree(tmp_path) == while_clean


def test_split_invalid_budget_exits_two(tmp_path):
    note(tmp_path)
    before = tree(tmp_path)
    result = run_cli(
        "--vault", str(tmp_path), "split", "memory.md", "--max-tokens", "0", cwd=tmp_path)
    assert result.returncode == 2
    assert result.stderr.strip()
    assert tree(tmp_path) == before


def test_coverage_output_is_utf8_even_when_host_encoding_is_ascii(tmp_path, monkeypatch):
    note(tmp_path)
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    result = run_cli("--vault", str(tmp_path), "split", "memory.md", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert data_rows(result.stdout) == list(
        range(1, len(SOURCE.decode("utf-8").splitlines(keepends=True)) + 1))
