"""Every CI job runs the suite on every supported OS, and the Python axis of
each job covers the oldest and newest supported interpreters, so a test
cannot pass on one OS or Python and never run on another."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"
SUPPORTED = {"ubuntu-latest", "windows-latest", "macos-latest"}
# The core job spans the supported range; mcp and semantic pin the oldest
# (requires-python) and the newest version that has the optional extras.
CORE_PYTHONS = {"3.10", "3.12", "3.14"}
EXTRA_PYTHONS = {"3.10", "3.13"}
_OS_LINE = re.compile(r"^\s*(?:-\s*)?os:\s*(.+)$")
_PYTHON_LINE = re.compile(r"^\s*python:\s*(\[.+\])\s*$")


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


def _matrix_pythons(block: str) -> set[str]:
    """The versions on the job's ``python: [...]`` matrix axis; comments,
    ``python-version`` and scalar include entries are ignored."""
    found: set[str] = set()
    for line in block.splitlines():
        m = _PYTHON_LINE.match(line.split("#", 1)[0])
        if m:
            found.update(re.findall(r"\d+\.\d+", m.group(1)))
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


def test_core_job_spans_the_supported_python_range():
    block = _jobs(WORKFLOW.read_text(encoding="utf-8"))["core"]
    assert CORE_PYTHONS <= _matrix_pythons(block)


@pytest.mark.parametrize("job", ["mcp", "semantic"])
def test_extra_jobs_cover_oldest_and_newest_python(job):
    block = _jobs(WORKFLOW.read_text(encoding="utf-8"))[job]
    assert EXTRA_PYTHONS <= _matrix_pythons(block)


@pytest.mark.parametrize("job", ["core", "mcp", "semantic"])
def test_matrix_is_a_full_os_by_python_grid(job):
    """An ``include:`` list is how an OS silently ends up on one Python only."""
    block = _jobs(WORKFLOW.read_text(encoding="utf-8"))[job]
    assert not re.search(r"(?m)^\s*(?:include|exclude):", block)


def test_python_axis_ignores_comments_and_the_setup_python_input():
    block = (
        "      matrix:\n"
        '        python: ["3.10", "3.13"]  # "3.14" not yet\n'
        "    steps:\n"
        '          python-version: "3.9"\n'
    )
    assert _matrix_pythons(block) == {"3.10", "3.13"}
