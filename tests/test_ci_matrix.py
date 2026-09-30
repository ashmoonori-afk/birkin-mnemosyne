"""Every CI job runs the suite on every supported OS, so a test cannot pass
on one OS and never run on another."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"
SUPPORTED = ("ubuntu-latest", "windows-latest", "macos-latest")


def _jobs() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z][\w-]*):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


def test_workflow_has_the_three_suites():
    assert set(_jobs()) == {"core", "mcp", "semantic"}


@pytest.mark.parametrize("job", ["core", "mcp", "semantic"])
def test_every_job_runs_pytest_on_every_supported_os(job):
    block = _jobs()[job]
    assert "python -m pytest" in block
    assert [os for os in SUPPORTED if os not in block] == []
