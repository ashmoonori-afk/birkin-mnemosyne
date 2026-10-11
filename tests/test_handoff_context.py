"""Process defaults must not leak a task across an explicit project override."""

import pytest

from birkin_mnemosyne.handoff_context import required_scope, scope_from_defaults
from birkin_mnemosyne.handoff_records import HandoffError, HandoffScope


def test_process_defaults_and_explicit_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_PROJECT_KEY", "default-project")
    monkeypatch.setenv("MNEMOSYNE_TASK_KEY", "default-task")
    assert required_scope() == HandoffScope("default-project", "default-task")
    assert required_scope(task_key="other-task") == HandoffScope("default-project", "other-task")


@pytest.mark.parametrize("project", ["other-project", "default-project"])
def test_explicit_project_does_not_inherit_task(
    monkeypatch: pytest.MonkeyPatch, project: str,
) -> None:
    monkeypatch.setenv("MNEMOSYNE_PROJECT_KEY", "default-project")
    monkeypatch.setenv("MNEMOSYNE_TASK_KEY", "default-task")
    assert required_scope(project) == HandoffScope(project)
    assert required_scope(project, "explicit-task") == HandoffScope(project, "explicit-task")


def test_absent_defaults_are_optional_only_for_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_PROJECT_KEY", raising=False)
    monkeypatch.delenv("MNEMOSYNE_TASK_KEY", raising=False)
    assert scope_from_defaults() is None
    with pytest.raises(HandoffError):
        _ = required_scope()
    monkeypatch.setenv("MNEMOSYNE_TASK_KEY", "unbound-task")
    with pytest.raises(HandoffError):
        _ = scope_from_defaults()


def test_blank_explicit_project_does_not_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_PROJECT_KEY", "default-project")
    with pytest.raises(HandoffError):
        _ = required_scope("")
