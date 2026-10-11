"""Resume must consume the same resolved scope as capture and latest."""

import json
from pathlib import Path

import pytest

from birkin_mnemosyne.handoff_records import HandoffFields, HandoffScope
from birkin_mnemosyne.handoffs import HandoffStore
from test_handoff_cli import run_cli


@pytest.mark.parametrize("arguments,task,marker", [
    ((), "default-task", "DEFAULT_SCOPE_SELECTED"),
    (("--task-key", "other-task"), "other-task", "TASK_OVERRIDE_SELECTED"),
    (("--project-key", "default-project"), None, "PROJECT_SCOPE_SELECTED"),
])
def test_resume_uses_resolved_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    arguments: tuple[str, ...], task: str | None, marker: str,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    for key, work in (
        ("default-task", "DEFAULT_SCOPE_SELECTED"), ("other-task", "TASK_OVERRIDE_SELECTED"),
        (None, "PROJECT_SCOPE_SELECTED"),
    ):
        _ = store.capture(HandoffScope("default-project", key), HandoffFields(work), capture_id="one")
    monkeypatch.setenv("MNEMOSYNE_PROJECT_KEY", "default-project")
    monkeypatch.setenv("MNEMOSYNE_TASK_KEY", "default-task")
    result = run_cli("--vault", str(vault), "handoff", "resume", *arguments, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert marker in payload["context"]
    latest = store.latest(HandoffScope("default-project", task))
    assert latest is not None and latest.path in payload["context"]


def test_handoff_rejects_duplicate_vault_before_writing(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    result = run_cli(
        "--vault", str(first), "--vault", str(second), "handoff", "capture",
        "--project-key", "project", "--capture-id", "one", "--work", "must not write",
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert not first.exists() and not second.exists()
