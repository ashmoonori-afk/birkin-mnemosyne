"""Isolated per-test vault + scrubbed API keys (no network, no real vault)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "mn"
    monkeypatch.setenv("MNEMOSYNE_TEST_HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # the optional semantic leg is opt-in per test (never downloads a model)
    monkeypatch.setenv("MNEMOSYNE_SEMANTIC", "0")
    return home
