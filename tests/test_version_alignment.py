from __future__ import annotations

import re
import sys
from pathlib import Path

import birkin_mnemosyne

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _project_version() -> str:
    text = _read("pyproject.toml")
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(text)["project"]["version"]
    project = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    assert project, "pyproject.toml has no [project] table"
    match = re.search(r'^version = "(.+)"', project.group(1), re.MULTILINE)
    assert match, "pyproject.toml [project] has no version"
    return match.group(1)


def test_package_version_matches_pyproject() -> None:
    version = _project_version()
    assert birkin_mnemosyne.__version__ == version, (
        f"birkin_mnemosyne/__init__.py __version__ is {birkin_mnemosyne.__version__!r} "
        f"but pyproject.toml says {version!r}; bump __version__"
    )


def test_hermes_manifests_pin_current_release() -> None:
    pin = f"birkin-mnemosyne=={_project_version()}"
    for relative in ("integrations/hermes/pyproject.toml", "integrations/hermes/plugin.yaml"):
        assert f'"{pin}"' in _read(relative), f"{relative} must pin {pin!r}; bump its dependency"


def test_integration_readmes_mention_current_release() -> None:
    needle = f"=={_project_version()}"
    for relative in ("integrations/hermes/README.md", "integrations/openclaw/README.md"):
        assert needle in _read(relative), f"{relative} must reference {needle!r}; bump its install line"
