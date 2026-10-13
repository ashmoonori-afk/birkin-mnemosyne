from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_hermes_catalog.py"
_spec = importlib.util.spec_from_file_location("update_hermes_catalog", SCRIPT)
assert _spec and _spec.loader
cat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cat)

OLD = "4244768c9afcc14001a59af6e39151e96a43bc2a"
NEW = "08e518d31bb71e5e8c530a5a0f8930c5f194b300"
TAG_OBJ = "62c30afec3a826e06cce6315671372a9237ba5bf"
BASE = "835c3dd038d903182a66ecc45e34bf5e0de65f00"
BRANCH = "catalog/birkin-mnemosyne-v0.7.0"
SRC = "/repos/ashmoonori-afk/birkin-mnemosyne"
UP = "/repos/NousResearch/hermes-agent"
FORK = "/repos/ashmoonori-afk/hermes-agent"
CATALOG = f"""name: birkin-mnemosyne
repo: https://github.com/ashmoonori-afk/birkin-mnemosyne
sha: {OLD}
subdir: integrations/hermes
version: "0.0.9"
description: >-
  Local Markdown memory provider. Uses
  published birkin-mnemosyne 0.4.0; no API key.
maintainer: ashmoonori-afk
docs_url: https://github.com/ashmoonori-afk/birkin-mnemosyne/tree/{OLD}/integrations/hermes
capabilities:
  provides_tools: []
"""
EXPECTED = (CATALOG.replace(f"sha: {OLD}", f"sha: {NEW}")
            .replace(f"tree/{OLD}/", f"tree/{NEW}/")
            .replace('version: "0.0.9"', 'version: "0.1.0"')
            .replace("birkin-mnemosyne 0.4.0", "birkin-mnemosyne 0.7.0"))


def _content(text: str, blob: str = "blob1") -> dict[str, str]:
    return {"content": base64.b64encode(text.encode()).decode(), "sha": blob}


def _quoted(value: str) -> str:
    return cat.quote(value)


class FakeGitHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.routes: dict[tuple[str, str], tuple[int, object]] = {
            ("GET", f"{SRC}/git/ref/tags/v0.7.0"): (200, {"object": {"type": "tag", "sha": TAG_OBJ}}),
            ("GET", f"{SRC}/git/tags/{TAG_OBJ}"): (200, {"object": {"type": "commit", "sha": NEW}}),
            ("GET", f"{SRC}/contents/pyproject.toml?ref={NEW}"):
                (200, _content('[project]\nname = "birkin-mnemosyne"\nversion = "0.7.0"\n')),
            ("GET", f"{SRC}/contents/integrations/hermes/plugin.yaml?ref={NEW}"):
                (200, _content('name: birkin-mnemosyne\nversion: "0.1.0"\n')),
            ("GET", "https://pypi.org/pypi/birkin-mnemosyne/0.7.0/json"): (200, {}),
            ("GET", f"{UP}/git/ref/heads/main"): (200, {"object": {"sha": BASE}}),
            ("GET", f"{UP}/contents/plugin-catalog/birkin-mnemosyne.yaml?ref={BASE}"): (200, _content(CATALOG)),
            ("GET", f"{SRC}/compare/{OLD}...{NEW}"): (200, {"status": "ahead", "total_commits": 2, "commits": [
                {"sha": "a" * 40, "commit": {"message": "feat: labels (#80) thanks @someone\n\nbody"}},
                {"sha": NEW, "commit": {"message": "fix: `quoted` edge"}},
            ]}),
            ("GET", f"{UP}/pulls?state=all&head={_quoted('ashmoonori-afk:' + BRANCH)}"): (200, []),
            ("GET", f"/search/issues?q={_quoted(f'repo:NousResearch/hermes-agent is:pr is:open {NEW}')}"):
                (200, {"total_count": 0, "items": []}),
            ("GET", f"{FORK}/git/ref/heads/{_quoted(BRANCH)}"): (404, {"message": "Not Found"}),
            ("POST", f"{FORK}/git/refs"): (201, {}),
            ("GET", f"{FORK}/contents/plugin-catalog/birkin-mnemosyne.yaml?ref={_quoted(BRANCH)}"):
                (200, _content(CATALOG, "branchblob")),
            ("PUT", f"{FORK}/contents/plugin-catalog/birkin-mnemosyne.yaml"): (200, {}),
            ("POST", f"{UP}/pulls"): (201, {"html_url": "https://github.com/NousResearch/hermes-agent/pull/1"}),
        }

    def __call__(self, method, url, token=None, body=None):
        path = url.removeprefix(cat.API)
        self.calls.append((method, path, body))
        assert (method, path) in self.routes, f"unexpected request {method} {path}"
        if method != "GET":
            assert token == "write-token", "writes must use HERMES_CATALOG_TOKEN only"
        status, payload = self.routes[(method, path)]
        return status, json.dumps(payload).encode()

    def writes(self) -> list[tuple[str, str, dict[str, Any] | None]]:
        return [c for c in self.calls if c[0] != "GET"]


@pytest.fixture
def fake(monkeypatch):
    transport = FakeGitHub()
    monkeypatch.setattr(cat, "request", transport)
    monkeypatch.setattr(cat.time, "sleep", lambda _s: None)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("HERMES_CATALOG_TOKEN", "write-token")
    return transport


def test_missing_token_skips_with_notice_and_exit_zero() -> None:
    env = {k: v for k, v in os.environ.items() if k != "HERMES_CATALOG_TOKEN"}
    env["GITHUB_ACTIONS"] = "false"
    result = subprocess.run([sys.executable, str(SCRIPT), "--release-tag", "v0.7.0"],
                            capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "HERMES_CATALOG_TOKEN is not set" in result.stderr


@pytest.mark.parametrize("tag", ["0.7.0", "v0.7", "v0.8.0rc1", "v0.7.0; rm -rf /", "v0.7.0\n", "$(id)"])
def test_malformed_tag_is_rejected_before_any_request(fake, tag, capsys) -> None:
    assert cat.main(["--release-tag", tag]) == 1
    assert fake.calls == []
    assert "release tag must look like" in capsys.readouterr().err


def test_dry_run_prints_only_the_catalog_diff_and_never_writes(fake, capsys, monkeypatch) -> None:
    monkeypatch.delenv("HERMES_CATALOG_TOKEN")
    assert cat.main(["--release-tag", "v0.7.0", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert fake.writes() == []
    assert out == cat.catalog_diff(CATALOG, EXPECTED)
    assert out.startswith("--- a/plugin-catalog/birkin-mnemosyne.yaml\n")
    changed = [line for line in out.splitlines() if line[:1] in "+-" and line[:3] not in ("---", "+++")]
    assert len(changed) == 8


def test_annotated_tag_resolves_to_its_commit(fake) -> None:
    assert cat.resolve_tag(cat.GitHub(None, None), "v0.7.0") == NEW


def test_real_run_branches_from_upstream_main_and_opens_one_new_pr(fake, capsys) -> None:
    assert cat.main(["--release-tag", "v0.7.0"]) == 0
    writes = fake.writes()
    assert [(m, p) for m, p, _ in writes] == [
        ("POST", f"{FORK}/git/refs"),
        ("PUT", f"{FORK}/contents/plugin-catalog/birkin-mnemosyne.yaml"),
        ("POST", f"{UP}/pulls"),
    ]
    assert writes[0][2] == {"ref": f"refs/heads/{BRANCH}", "sha": BASE}
    put = writes[1][2]
    assert put and put["branch"] == BRANCH and put["sha"] == "branchblob"
    assert base64.b64decode(put["content"]).decode() == EXPECTED
    pr = writes[2][2]
    assert pr and pr["head"] == f"ashmoonori-afk:{BRANCH}" and pr["base"] == "main"
    assert f"`{OLD}` -> `{NEW}`" in pr["body"]
    assert f"compare/{OLD}...{NEW}" in pr["body"]
    assert "- `aaaaaaaaaaaa` `feat: labels (#80) thanks @someone`" in pr["body"]
    assert "- `08e518d31bb7` `fix: 'quoted' edge`" in pr["body"]
    assert "Not run by the automation" in pr["body"]
    assert "pull/1" in capsys.readouterr().out


def test_rerun_with_existing_pr_for_the_release_makes_no_writes(fake, capsys) -> None:
    fake.routes[("GET", f"{UP}/pulls?state=all&head={_quoted('ashmoonori-afk:' + BRANCH)}")] = (
        200, [{"number": 7, "state": "open"}])
    assert cat.main(["--release-tag", "v0.7.0"]) == 0
    assert fake.writes() == []
    assert "#7 (open)" in capsys.readouterr().err


def test_open_pr_naming_the_same_sha_from_another_branch_is_left_alone(fake, capsys) -> None:
    fake.routes[("GET", f"/search/issues?q={_quoted(f'repo:NousResearch/hermes-agent is:pr is:open {NEW}')}")] = (
        200, {"total_count": 1, "items": [{"number": 136924}]})
    assert cat.main(["--release-tag", "v0.7.0"]) == 0
    assert fake.writes() == []
    assert "#136924" in capsys.readouterr().err


BRANCH_COMPARE = f"{UP}/compare/{BASE}...{_quoted('ashmoonori-afk:' + BRANCH)}"
OLDER_BASE = "c" * 40


def _existing_branch(fake, files: list[str], merge_base: str = BASE, content: str = EXPECTED) -> None:
    fake.routes[("GET", f"{FORK}/git/ref/heads/{_quoted(BRANCH)}")] = (200, {"object": {"sha": "b" * 40}})
    fake.routes[("GET", BRANCH_COMPARE)] = (
        200, {"merge_base_commit": {"sha": merge_base}, "files": [{"filename": f} for f in files]})
    fake.routes[("GET", f"{FORK}/contents/plugin-catalog/birkin-mnemosyne.yaml?ref={_quoted(BRANCH)}")] = (
        200, _content(content, "branchblob"))


def test_rerun_after_branch_was_pushed_only_opens_the_pr(fake) -> None:
    _existing_branch(fake, ["plugin-catalog/birkin-mnemosyne.yaml"])
    assert cat.main(["--release-tag", "v0.7.0"]) == 0
    assert [(m, p) for m, p, _ in fake.writes()] == [("POST", f"{UP}/pulls")]


def test_rerun_after_branch_was_created_but_not_committed_commits_then_opens_pr(fake) -> None:
    _existing_branch(fake, [], content=CATALOG)
    assert cat.main(["--release-tag", "v0.7.0"]) == 0
    assert [(m, p) for m, p, _ in fake.writes()] == [
        ("PUT", f"{FORK}/contents/plugin-catalog/birkin-mnemosyne.yaml"),
        ("POST", f"{UP}/pulls"),
    ]


def test_existing_branch_with_unrelated_file_changes_is_refused(fake, capsys) -> None:
    _existing_branch(fake, ["plugin-catalog/birkin-mnemosyne.yaml", "tools/other.py"])
    assert cat.main(["--release-tag", "v0.7.0"]) == 1
    assert fake.writes() == []
    assert "files other than plugin-catalog/birkin-mnemosyne.yaml" in capsys.readouterr().err


def test_existing_branch_on_an_older_catalog_is_refused(fake, capsys) -> None:
    _existing_branch(fake, ["plugin-catalog/birkin-mnemosyne.yaml"], merge_base=OLDER_BASE)
    fake.routes[("GET", f"{UP}/contents/plugin-catalog/birkin-mnemosyne.yaml?ref={OLDER_BASE}")] = (
        200, _content(CATALOG.replace(OLD, "d" * 40)))
    assert cat.main(["--release-tag", "v0.7.0"]) == 1
    assert fake.writes() == []
    assert "older catalog" in capsys.readouterr().err


def test_existing_branch_on_an_older_base_with_the_same_catalog_is_reused(fake) -> None:
    _existing_branch(fake, ["plugin-catalog/birkin-mnemosyne.yaml"], merge_base=OLDER_BASE)
    fake.routes[("GET", f"{UP}/contents/plugin-catalog/birkin-mnemosyne.yaml?ref={OLDER_BASE}")] = (
        200, _content(CATALOG))
    assert cat.main(["--release-tag", "v0.7.0"]) == 0
    assert [(m, p) for m, p, _ in fake.writes()] == [("POST", f"{UP}/pulls")]


def test_existing_branch_with_unexpected_catalog_content_is_refused(fake, capsys) -> None:
    _existing_branch(fake, ["plugin-catalog/birkin-mnemosyne.yaml"], content=EXPECTED + "extra: true\n")
    assert cat.main(["--release-tag", "v0.7.0"]) == 1
    assert fake.writes() == []
    assert "unexpected" in capsys.readouterr().err


def test_upstream_already_pinned_is_a_no_op(fake) -> None:
    fake.routes[("GET", f"{UP}/contents/plugin-catalog/birkin-mnemosyne.yaml?ref={BASE}")] = (
        200, _content(EXPECTED))
    assert cat.main(["--release-tag", "v0.7.0"]) == 0
    assert fake.writes() == []


def test_non_forward_pin_is_refused(fake, capsys) -> None:
    fake.routes[("GET", f"{SRC}/compare/{OLD}...{NEW}")] = (
        200, {"status": "behind", "total_commits": 0, "commits": []})
    assert cat.main(["--release-tag", "v0.7.0"]) == 1
    assert fake.writes() == []
    assert "non-forward" in capsys.readouterr().err


def test_release_missing_from_pypi_is_refused(fake, capsys) -> None:
    fake.routes[("GET", "https://pypi.org/pypi/birkin-mnemosyne/0.7.0/json")] = (404, {})
    assert cat.main(["--release-tag", "v0.7.0"]) == 1
    assert fake.writes() == []
    assert "not on PyPI" in capsys.readouterr().err


def test_pr_creation_failure_reports_manual_compare_url(fake, capsys) -> None:
    fake.routes[("POST", f"{UP}/pulls")] = (403, {"message": "Resource not accessible by personal access token"})
    assert cat.main(["--release-tag", "v0.7.0"]) == 1
    err = capsys.readouterr().err
    assert "HTTP 403" in err
    assert f"compare/main...ashmoonori-afk:{BRANCH}" in err


def test_catalog_without_expected_fields_is_refused() -> None:
    with pytest.raises(cat.CatalogError, match="published birkin-mnemosyne"):
        cat.rewrite_catalog(CATALOG.replace("published birkin-mnemosyne 0.4.0", "core 0.4.0"), NEW, "0.1.0", "0.7.0")
