"""Every CI job runs the suite on every supported OS, so a test cannot pass
on one OS and never run on another."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"
SUPPORTED = {"ubuntu-latest", "windows-latest", "macos-latest"}
_OS_LINE = re.compile(r"^\s*(?:-\s*)?os:\s*(.+)$")


def _jobs(text: str) -> dict[str, str]:
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z][\w-]*):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


def _matrix_systems(block: str) -> set[str]:
    """The runner names on the job's ``os:`` matrix lines; comments and
    every other line are ignored."""
    found: set[str] = set()
    for line in block.splitlines():
        m = _OS_LINE.match(line.split("#", 1)[0])
        if m and "matrix." not in m.group(1):
            found.update(re.findall(r"[a-z]+-latest", m.group(1)))
    return found


def test_workflow_has_the_three_suites():
    assert set(_jobs(WORKFLOW.read_text(encoding="utf-8"))) == {"core", "mcp", "semantic"}


@pytest.mark.parametrize("job", ["core", "mcp", "semantic"])
def test_every_job_runs_pytest_on_every_supported_os(job):
    block = _jobs(WORKFLOW.read_text(encoding="utf-8"))[job]
    assert "python -m pytest" in block
    assert _matrix_systems(block) == SUPPORTED


def test_a_system_named_only_in_a_comment_does_not_count():
    block = "    strategy:\n      matrix:\n        os: [ubuntu-latest, windows-latest]  # macos-latest removed\n"
    assert _matrix_systems(block) == {"ubuntu-latest", "windows-latest"}
