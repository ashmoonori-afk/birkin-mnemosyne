"""The handoff CLI proves capture/latest/resume/fold/undo through real processes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import birkin_mnemosyne
from birkin_mnemosyne import HandoffScope, HandoffStore, MemoryIndex
from birkin_mnemosyne.memory_index import INDEX_SOURCE

SCOPE = ("--project-key", "mn-070", "--task-key", "handoff")


def run_cli(*args: str, cwd: Path,
            stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
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
        cwd=cwd, capture_output=True, check=False, input=stdin,
    )


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def cli_capture(vault: Path, cwd: Path, scope: tuple[str, str, str, str],
                capture_id: str, work: str, *extra: str,
                stdin: bytes | None = None) -> dict[str, Any]:
    result = run_cli("--vault", str(vault), "handoff", "capture", *scope,
                     "--capture-id", capture_id, "--work", work, *extra,
                     cwd=cwd, stdin=stdin)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.decode("utf-8"))


def records_only(root: Path) -> dict[str, bytes]:
    return {
        path: data for path, data in tree(root).items()
        if path.startswith((".mnemosyne-handoffs/", ".mnemosyne-reviews/"))
    }


def test_capture_flags_print_receipt_and_latest_roundtrip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    receipt = cli_capture(
        vault, tmp_path, SCOPE, "checkpoint-1",
        "A_ONLY_SENTINEL\nContinue the release.\nKeep all bytes.",
        "--decision", "Keep the INDEX complete.",
        "--open-item", "Check Windows.",
        "--open-question", "Which release gate remains?",
        "--next-step", "Run exact-head review.",
        "--link", "https://example.invalid/42",
    )
    assert receipt["created"] is True
    assert receipt["capture_id"] == "checkpoint-1"
    assert receipt["estimated_tokens"] > 0
    assert receipt["path"].startswith(".mnemosyne-handoffs/")
    assert receipt["sha256"] and len(receipt["sha256"]) == 64

    latest = run_cli("--vault", str(vault), "handoff", "latest", *SCOPE, cwd=tmp_path)
    assert latest.returncode == 0, latest.stderr
    payload = json.loads(latest.stdout.decode("utf-8"))
    assert payload["capture_id"] == "checkpoint-1"
    assert payload["path"] == receipt["path"]
    assert payload["sha256"] == receipt["sha256"]
    assert payload["event"] == "explicit" and payload["source"] == "api"
    assert payload["scope"] == {"project_key": "mn-070", "task_key": "handoff"}
    assert payload["fields"]["work"] == \
        "A_ONLY_SENTINEL\nContinue the release.\nKeep all bytes."
    assert payload["fields"]["next_step"] == "Run exact-head review."
    assert payload["fields"]["decisions"] == ["Keep the INDEX complete."]
    assert payload["fields"]["open_items"] == ["Check Windows."]
    assert payload["fields"]["open_questions"] == ["Which release gate remains?"]
    assert payload["fields"]["links"] == ["https://example.invalid/42"]


def test_json_stdin_capture_maps_fields_and_rejects_bad_payloads(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    compact = run_cli(
        "--vault", str(vault), "handoff", "capture", "--json-stdin", cwd=tmp_path,
        stdin=json.dumps({
            "project_key": "mn-070", "task_key": "handoff",
            "capture_id": "stdin-1", "event": "pre-compress",
            "session_id": "session-one", "work": "COMPACTION_ONLY_SENTINEL",
        }).encode("utf-8"),
    )
    assert compact.returncode == 0, compact.stderr
    compact_receipt = json.loads(compact.stdout.decode("utf-8"))
    assert compact_receipt["created"] is True
    assert compact_receipt["capture_id"] == "stdin-1"
    latest = run_cli("--vault", str(vault), "handoff", "latest", *SCOPE, cwd=tmp_path)
    stored = json.loads(latest.stdout.decode("utf-8"))
    assert stored["fields"]["work"] == "COMPACTION_ONLY_SENTINEL"
    assert stored["fields"]["decisions"] == []
    assert stored["fields"]["open_items"] == []
    assert stored["fields"]["open_questions"] == []
    assert stored["fields"]["links"] == []
    assert stored["event"] == "pre-compress"
    assert stored["session_id"] == "session-one"

    payload = {
        "project_key": "mn-070", "task_key": "handoff",
        "capture_id": "stdin-2", "work": "B_ONLY_SENTINEL\nfrom stdin",
        "next_step": "verify resume", "decisions": ["d1", "d2"],
        "open_items": ["i1"], "open_questions": ["q1"], "links": ["https://example.invalid"],
        "event": "pre-compress", "session_id": "session-1", "source": "test",
    }
    stdout = run_cli(
        "--vault", str(vault), "handoff", "capture", "--json-stdin", cwd=tmp_path,
        stdin=json.dumps(payload).encode("utf-8"),
    )
    assert stdout.returncode == 0, stdout.stderr
    receipt = json.loads(stdout.stdout.decode("utf-8"))
    assert receipt["created"] is True and receipt["capture_id"] == "stdin-2"

    latest = run_cli("--vault", str(vault), "handoff", "latest", *SCOPE, cwd=tmp_path)
    stored = json.loads(latest.stdout.decode("utf-8"))
    assert stored["fields"]["work"] == "B_ONLY_SENTINEL\nfrom stdin"
    assert stored["fields"]["decisions"] == ["d1", "d2"]
    assert stored["fields"]["open_items"] == ["i1"]
    assert stored["fields"]["open_questions"] == ["q1"]
    assert stored["fields"]["links"] == ["https://example.invalid"]
    assert stored["event"] == "pre-compress"
    assert stored["session_id"] == "session-1"
    assert stored["source"] == "test"

    image = tree(vault)
    conflicts = [
        ({"project_key": "mn-070", "capture_id": "b1", "work": "x", "bogus": 1},
         "unknown --json-stdin field"),
        ({"project_key": "mn-070", "capture_id": "b2", "work": "x",
          "decisions": "not-a-list"}, "--json-stdin decisions"),
        ({"project_key": "mn-070", "capture_id": "b3"}, "--json-stdin payload requires"),
        ({"project_key": "mn-070", "capture_id": "b4", "work": "x",
          "task_key": 7}, "--json-stdin task_key"),
    ]
    for bad, message in conflicts:
        result = run_cli("--vault", str(vault), "handoff", "capture",
                         "--json-stdin", cwd=tmp_path,
                         stdin=json.dumps(bad).encode("utf-8"))
        assert result.returncode == 2, (bad, result.stdout)
        assert message in result.stderr.decode("utf-8"), result.stderr
        assert tree(vault) == image

    incompatible = run_cli(
        "--vault", str(vault), "handoff", "capture", "--json-stdin", "--work", "x",
        cwd=tmp_path, stdin=b"{}",
    )
    assert incompatible.returncode == 2
    assert b"--json-stdin cannot be combined with --work" in incompatible.stderr
    assert tree(vault) == image


def test_repeated_id_is_idempotent_and_conflict_creates_nothing_new(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    capture = ["handoff", "capture", *SCOPE, "--capture-id", "compression-1",
               "--work", "A_ONLY_SENTINEL\nKeep the release text."]
    first = run_cli("--vault", str(vault), *capture, cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    first_receipt = json.loads(first.stdout.decode("utf-8"))
    image = tree(vault)

    again = run_cli("--vault", str(vault), *capture, cwd=tmp_path)
    assert again.returncode == 0, again.stderr
    repeat = json.loads(again.stdout.decode("utf-8"))
    assert repeat["created"] is False
    assert repeat["path"] == first_receipt["path"]
    assert repeat["sha256"] == first_receipt["sha256"]
    assert tree(vault) == image

    conflict = list(capture)
    conflict[conflict.index("--work") + 1] = "Conflicting retry"
    failed = run_cli("--vault", str(vault), *conflict, cwd=tmp_path)
    assert failed.returncode == 2, failed.stdout
    assert failed.stderr
    assert tree(vault) == image


def test_fresh_resume_bundle_contains_index_latest_and_isolates_scope(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    MemoryIndex(vault).enable()
    before = run_cli("--vault", str(vault), "handoff", "resume", *SCOPE, cwd=tmp_path)
    assert before.returncode == 0, before.stderr
    bundle = json.loads(before.stdout.decode("utf-8"))
    context = json.loads(bundle["context"])
    assert context["complete"] is True
    assert context["files"][0]["path"] == INDEX_SOURCE
    assert context["handoff_path"] is None
    assert bundle["estimated_tokens"] > 0

    first = cli_capture(
        vault, tmp_path, SCOPE, "compression-1",
        "A_ONLY_SENTINEL\nContinue the release.\u2028Preserve all text.",
    )
    _ = run_cli(
        "--vault", str(vault), "handoff", "capture", "--json-stdin", cwd=tmp_path,
        stdin=json.dumps({
            "project_key": r"C:\Work\foo", "task_key": "release:0.7",
            "capture_id": "compression-1", "work": "B_ONLY_SENTINEL",
        }).encode("utf-8"),
    )
    _ = run_cli(
        "--vault", str(vault), "handoff", "capture",
        "--project-key", r"C:\Work\Foo", "--task-key", "different-task",
        "--capture-id", "compression-1", "--work", "TASK_ONLY_SENTINEL",
        cwd=tmp_path,
    )
    resumed = run_cli("--vault", str(vault), "handoff", "resume", *SCOPE, cwd=tmp_path)
    assert resumed.returncode == 0, resumed.stderr
    bundle = json.loads(resumed.stdout.decode("utf-8"))
    assert bundle["complete"] is True
    assert bundle["coverage"]["complete"] is True
    payload = json.loads(bundle["context"])
    assert payload["files"][0]["path"] == INDEX_SOURCE
    assert payload["handoff_path"] == first["path"]
    blocks = sorted(
        (block for block in payload["blocks"] if block["path"] == first["path"]),
        key=lambda block: block["start_byte"],
    )
    assert b"".join(block["text"].encode("utf-8")
                     for block in blocks) == (vault / first["path"]).read_bytes()
    assert "A_ONLY_SENTINEL" in bundle["context"]
    assert "B_ONLY_SENTINEL" not in bundle["context"]
    assert "TASK_ONLY_SENTINEL" not in bundle["context"]
    assert bundle["estimated_tokens"] > 0


def test_windows_shaped_keys_roundtrip_across_processes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scope = ("--project-key", r"C:\Work\Foo", "--task-key", "release:0.7")
    receipt = cli_capture(
        vault, tmp_path, scope, "checkpoint-2",
        "WINDOWS_SENTINEL\nRelease notes for the Windows shape.",
    )
    assert receipt["path"].startswith(".mnemosyne-handoffs/")

    latest = run_cli("--vault", str(vault), "handoff", "latest", *scope, cwd=tmp_path)
    assert latest.returncode == 0, latest.stderr
    stored = json.loads(latest.stdout.decode("utf-8"))
    assert stored["scope"] == {"project_key": r"C:\Work\Foo",
                               "task_key": "release:0.7"}
    assert "WINDOWS_SENTINEL" in stored["fields"]["work"]

    missing = run_cli(
        "--vault", str(vault), "handoff", "latest",
        "--project-key", r"C:\Work\Foo", "--task-key", "missing", cwd=tmp_path,
    )
    assert missing.returncode == 1
    assert missing.stdout == b""


def test_absent_latest_exits_one_with_stderr(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    result = run_cli("--vault", str(vault), "handoff", "latest", *SCOPE, cwd=tmp_path)
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"no active handoff capture" in result.stderr


@pytest.mark.parametrize("case", [
    ("handoff", "capture", *SCOPE, "--work", "x"),
    ("handoff", "capture", *SCOPE, "--capture-id", "c"),
    ("handoff", "capture", *SCOPE, "--capture-id", "c", "--work", "x",
     "--work", "y"),
    ("handoff", "capture", *SCOPE, "--capture-id", "c", "--capture-id", "c2",
     "--work", "x"),
    ("handoff", "capture", *SCOPE, "--capture-id", "c", "--work", "x",
     "--project-key", "a", "--project-key", "b"),
    ("handoff", "capture", *SCOPE, "--capture-id", "c", "--work", "x",
     "--decision", ""),
    ("handoff", "capture", *SCOPE, "--capture-id", "c", "--work", " "),
    ("handoff", "capture", *SCOPE, "--capture-id", "c", "--work", "x",
     "--bogus", "y"),
    ("handoff", "capture", "--json-stdin", "--open-item", "i"),
    ("handoff", "capture", "--json-stdin"),
    ("handoff", "latest"),
    ("handoff", "fold"),
    ("handoff", "fold", *SCOPE, "--keep", "0"),
    ("handoff", "fold", *SCOPE, "--apply"),
    ("handoff", "fold", *SCOPE, "--apply", "--plan-id", "0" * 64),
    ("handoff", "undo"),
    ("handoff", "undo", "--transaction", "deadbeef"),
    ("handoff", "bogus-command"),
    ("handoff",),
])
def test_bad_and_duplicate_options_exit_two_without_creating_records(
    tmp_path: Path, case: tuple[str, ...],
) -> None:
    vault = tmp_path / "vault"
    result = run_cli("--vault", str(vault), *case, cwd=tmp_path)
    assert result.returncode == 2, (case, result.returncode, result.stderr)
    assert result.stderr, case
    assert records_only(vault) == {}


def test_fold_preview_apply_and_undo_via_cli(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for index in range(5):
        receipt = cli_capture(
            vault, tmp_path, SCOPE, f"cap-{index}", f"work {index}",
        )
        assert receipt["created"] is True
    scope = HandoffScope("mn-070", "handoff")
    assert [note.record.capture_id
            for note in HandoffStore(vault).records(scope)] == \
        [f"cap-{index}" for index in range(5)]

    preview = run_cli("--vault", str(vault), "handoff", "fold",
                      *SCOPE, "--keep", "3", cwd=tmp_path)
    assert preview.returncode == 0, preview.stderr
    folded = json.loads(preview.stdout.decode("utf-8"))
    assert folded["state"] == "preview"
    assert folded["plan_id"]
    assert len(folded["accepted"]) == 2
    assert folded["rejected"] == []
    assert folded["pinned"]["recorded_at"] == \
        sorted(n.record.recorded_at
               for n in HandoffStore(vault).records(scope))[-1]

    applied = run_cli("--vault", str(vault), "handoff", "fold", *SCOPE,
                      "--keep", "3", "--apply", "--plan-id",
                      folded["plan_id"], cwd=tmp_path)
    assert applied.returncode == 0, applied.stderr
    committed = json.loads(applied.stdout.decode("utf-8"))
    assert committed["state"] == "committed"
    assert committed["transaction_id"]

    latest = run_cli("--vault", str(vault), "handoff", "latest", *SCOPE, cwd=tmp_path)
    assert json.loads(latest.stdout.decode("utf-8"))["capture_id"] == "cap-4"

    undone = run_cli("--vault", str(vault), "handoff", "undo",
                     "--transaction", committed["transaction_id"], cwd=tmp_path)
    assert undone.returncode == 0, undone.stderr
    receipt = json.loads(undone.stdout.decode("utf-8"))
    assert receipt["state"] == "undone"
    assert receipt["transaction_id"] == committed["transaction_id"]
    assert [note.record.capture_id
            for note in HandoffStore(vault).records(scope)] == \
        [f"cap-{index}" for index in range(5)]


def test_capture_utf8_output_survives_ascii_host_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    vault = tmp_path / "vault"
    result = run_cli(
        "--vault", str(vault), "handoff", "capture", *SCOPE,
        "--capture-id", "ko-1", "--work", "한국어 원문과 日本語のメモ",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.decode("utf-8"))
    assert receipt["capture_id"] == "ko-1"
    latest = run_cli("--vault", str(vault), "handoff", "latest", *SCOPE,
                     cwd=tmp_path)
    assert json.loads(latest.stdout.decode("utf-8"))["fields"]["work"] == \
        "한국어 원문과 日本語のメモ"


def test_json_stdin_utf8_survives_ascii_host_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    vault = tmp_path / "vault"
    payload = json.dumps({
        "project_key": "mn-070", "task_key": "handoff",
        "capture_id": "ko-stdin", "work": "한국어 원문과 日本語のメモ",
    }).encode("utf-8")
    result = run_cli("--vault", str(vault), "handoff", "capture",
                     "--json-stdin", cwd=tmp_path, stdin=payload)
    assert result.returncode == 0, result.stderr
    latest = run_cli("--vault", str(vault), "handoff", "latest", *SCOPE,
                     cwd=tmp_path)
    assert json.loads(latest.stdout.decode("utf-8"))["fields"]["work"] == \
        "한국어 원문과 日本語のメモ"
