"""Isolated per-test vault + scrubbed API keys (no network, no real vault)."""

from __future__ import annotations

import importlib.util

import pytest

# optional suite -> top-level modules its tests importorskip (looked up with
# find_spec only, so the header never imports a heavy package)
OPTIONAL_SUITES = (
    ("mcp", ("mcp",)),
    ("semantic", ("numpy",)),
    ("static_model", ("numpy", "safetensors")),
)


def pytest_report_header(config) -> str:
    """One line saying which optional suites run and which skip, and why."""
    parts = []
    for suite, modules in OPTIONAL_SUITES:
        missing = [m for m in modules if importlib.util.find_spec(m) is None]
        parts.append(f"{suite}=off ({', '.join(missing)} missing)" if missing
                     else f"{suite}=on")
    return "optional suites: " + " ".join(parts)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    # -q hides the report header, so repeat the line where -q users see it
    if config.option.verbose < 0:
        terminalreporter.write_line(pytest_report_header(config))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "mn"
    monkeypatch.setenv("MNEMOSYNE_TEST_HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # the optional semantic leg is opt-in per test (never downloads a model)
    monkeypatch.setenv("MNEMOSYNE_SEMANTIC", "0")
    return home
