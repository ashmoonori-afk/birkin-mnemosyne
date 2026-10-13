from __future__ import annotations

import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

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


_CORE_DEP = re.compile(r'birkin-mnemosyne([<>=!~][^"\s]*)')


def test_hermes_manifests_declare_matching_core_range() -> None:
    relative_pyproject = "integrations/hermes/pyproject.toml"
    relative_manifest = "integrations/hermes/plugin.yaml"
    declared: dict[str, SpecifierSet] = {}
    for relative in (relative_pyproject, relative_manifest):
        match = _CORE_DEP.search(_read(relative))
        assert match is not None, f"{relative} declares no birkin-mnemosyne dependency"
        declared[relative] = Requirement(f"birkin-mnemosyne{match.group(1)}").specifier
    assert declared[relative_pyproject] == declared[relative_manifest], (
        f"Hermes manifests declare different core ranges: {declared}"
    )
    specifier = declared[relative_pyproject]
    assert Version(_project_version()) in specifier, (
        f"published core {_project_version()} is outside the declared range {specifier}"
    )
    assert Version("1.0") not in specifier, "the core range must stay below 1.0"


def test_hermes_plugin_versions_match() -> None:
    project = _read("integrations/hermes/pyproject.toml")
    manifest = _read("integrations/hermes/plugin.yaml")
    project_version = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE)
    manifest_version = re.search(r'^version: "([^"]+)"$', manifest, re.MULTILINE)
    assert project_version and manifest_version
    assert project_version.group(1) == manifest_version.group(1)


def test_hermes_python_requirement_matches_core() -> None:
    pattern = r'^requires-python = "([^"]+)"$'
    core = re.search(pattern, _read("pyproject.toml"), re.MULTILINE)
    plugin = re.search(pattern, _read("integrations/hermes/pyproject.toml"), re.MULTILINE)
    assert core and plugin
    assert plugin.group(1) == core.group(1)


def test_openclaw_readme_mentions_current_release() -> None:
    relative = "integrations/openclaw/README.md"
    needle = f"=={_project_version()}"
    assert needle in _read(relative), f"{relative} must reference {needle!r}; bump its install line"
