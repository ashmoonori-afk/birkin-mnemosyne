"""Test-only config shim (not part of the shipped package).

Reproduces the two functions the ported Birkin tests call — `load_config()`
and `vault_dir()` — backed by the `MNEMOSYNE_TEST_HOME` env var that conftest
sets per test, so each test gets an isolated vault.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _home() -> Path:
    raw = os.environ.get("MNEMOSYNE_TEST_HOME") or os.environ.get("BIRKIN_HOME")
    home = Path(raw).expanduser() if raw else Path.home() / ".mnemosyne-test"
    home.mkdir(parents=True, exist_ok=True)
    return home


def load_config() -> dict[str, Any]:
    # pin vault_path so VaultMemory and vault_dir() resolve to the same dir
    return {"vault_path": str(_home() / "vault")}


def vault_dir(cfg: dict[str, Any] | None = None) -> Path:
    raw = (cfg or {}).get("vault_path")
    d = Path(raw).expanduser() if raw else _home() / "vault"
    d.mkdir(parents=True, exist_ok=True)
    return d
