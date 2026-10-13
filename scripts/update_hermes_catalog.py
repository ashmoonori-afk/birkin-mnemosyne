#!/usr/bin/env python3
"""Propose a Hermes plugin-catalog SHA bump for a published birkin-mnemosyne release.

Run after the release's PyPI publish succeeded:

    python scripts/update_hermes_catalog.py --release-tag v0.7.0 [--dry-run]

It reads NousResearch/hermes-agent main, rewrites only
plugin-catalog/birkin-mnemosyne.yaml (sha, docs_url, version, the core
version named in description), and opens a NEW pull request from a
release-specific branch of ashmoonori-afk/hermes-agent created at the upstream
main snapshot. The fork's own branches are never merged, rebased or
force-pushed, and an existing pull request is never edited.

Writes use only the HERMES_CATALOG_TOKEN environment variable. Without it a
real run prints a notice and exits 0 so a release never fails on it.
--dry-run performs no write and prints the catalog diff on stdout.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = "https://api.github.com"
SOURCE_REPO = "ashmoonori-afk/birkin-mnemosyne"
UPSTREAM_REPO = "NousResearch/hermes-agent"
FORK_REPO = "ashmoonori-afk/hermes-agent"
CATALOG_PATH = "plugin-catalog/birkin-mnemosyne.yaml"
PLUGIN_SUBDIR = "integrations/hermes"
PYPI_PROJECT = "birkin-mnemosyne"
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PYPI_ATTEMPTS = 5
PYPI_RETRY_SECONDS = 30


class CatalogError(Exception):
    pass


class HttpError(CatalogError):
    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:300]}")
        self.status = status


def request(method: str, url: str, token: str | None = None,
            body: dict[str, Any] | None = None) -> tuple[int, bytes]:
    """The only network seam: tests replace this function with a fake."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "birkin-mnemosyne-catalog-bot")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class GitHub:
    def __init__(self, read_token: str | None, write_token: str | None) -> None:
        self.read_token = read_token
        self.write_token = write_token

    def call(self, method: str, path: str, body: dict[str, Any] | None = None,
             ok: tuple[int, ...] = (200,)) -> tuple[int, Any]:
        url = path if path.startswith("https://") else API + path
        token = self.read_token if method == "GET" else self.write_token
        if method != "GET" and not token:
            raise CatalogError(f"refusing {method} {path}: no HERMES_CATALOG_TOKEN")
        status, raw = request(method, url, token, body)
        if status not in ok:
            raise HttpError(method, url, status, raw.decode("utf-8", "replace"))
        return status, (json.loads(raw) if raw else None)

    def get(self, path: str, ok: tuple[int, ...] = (200,)) -> tuple[int, Any]:
        return self.call("GET", path, ok=ok)


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def parse_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise CatalogError(f"release tag must look like v1.2.3, got {tag!r}")
    return match.group(1)


def resolve_tag(gh: GitHub, tag: str) -> str:
    _, ref = gh.get(f"/repos/{SOURCE_REPO}/git/ref/tags/{quote(tag)}")
    obj = ref["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            return obj["sha"]
        if obj["type"] != "tag":
            raise CatalogError(f"tag {tag} points to a {obj['type']}, not a commit")
        _, tag_obj = gh.get(f"/repos/{SOURCE_REPO}/git/tags/{obj['sha']}")
        obj = tag_obj["object"]
    raise CatalogError(f"tag {tag} nests too deeply")


def file_at(gh: GitHub, repo: str, path: str, ref: str) -> tuple[str, str]:
    _, data = gh.get(f"/repos/{repo}/contents/{path}?ref={quote(ref)}")
    return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]


def yaml_scalar(text: str, key: str) -> str:
    match = re.search(rf'^{key}:\s*"?([^"\n]+?)"?\s*$', text, re.MULTILINE)
    if not match:
        raise CatalogError(f"no top-level {key!r} found")
    return match.group(1)


def require_on_pypi(version: str) -> None:
    url = f"https://pypi.org/pypi/{PYPI_PROJECT}/{quote(version)}/json"
    status = 0
    for attempt in range(1, PYPI_ATTEMPTS + 1):
        status, _ = request("GET", url)
        if status == 200:
            return
        if attempt < PYPI_ATTEMPTS:
            time.sleep(PYPI_RETRY_SECONDS)
    raise CatalogError(f"{PYPI_PROJECT} {version} is not on PyPI (HTTP {status}); publish first")


def replace_once(text: str, pattern: str, repl: str, what: str) -> str:
    new, count = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if count != 1:
        raise CatalogError(f"expected exactly one {what} in {CATALOG_PATH}, found {count}")
    return new


def rewrite_catalog(text: str, new_sha: str, plugin_version: str, core_version: str) -> str:
    repo_url = f"https://github.com/{SOURCE_REPO}"
    if yaml_scalar(text, "repo") != repo_url or yaml_scalar(text, "subdir") != PLUGIN_SUBDIR:
        raise CatalogError(f"{CATALOG_PATH} no longer points at {repo_url} / {PLUGIN_SUBDIR}")
    text = replace_once(text, r"^sha: [0-9a-f]{40}$", f"sha: {new_sha}", "sha line")
    text = replace_once(
        text,
        rf"^docs_url: {re.escape(repo_url)}/tree/[0-9a-f]{{40}}/{re.escape(PLUGIN_SUBDIR)}$",
        f"docs_url: {repo_url}/tree/{new_sha}/{PLUGIN_SUBDIR}",
        "pinned docs_url line",
    )
    text = replace_once(text, r'^version: "[^"\n]*"$', f'version: "{plugin_version}"', "version line")
    return replace_once(
        text,
        rf"published {re.escape(PYPI_PROJECT)} \d+\.\d+\.\d+",
        f"published {PYPI_PROJECT} {core_version}",
        "'published birkin-mnemosyne X.Y.Z' description phrase",
    )


def catalog_diff(old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{CATALOG_PATH}",
            tofile=f"b/{CATALOG_PATH}",
        )
    )


def commit_range(gh: GitHub, old_sha: str, new_sha: str) -> tuple[int, list[str]]:
    _, cmp = gh.get(f"/repos/{SOURCE_REPO}/compare/{old_sha}...{new_sha}")
    if cmp["status"] != "ahead":
        raise CatalogError(f"{new_sha} is {cmp['status']} relative to the pinned {old_sha}; refusing a non-forward pin")
    lines = []
    for commit in cmp["commits"][-50:]:
        subject = commit["commit"]["message"].splitlines()[0].replace("`", "'")
        # code spans keep "#80" / "@user" in commit subjects from linking or pinging upstream
        lines.append(f"- `{commit['sha'][:12]}` `{subject}`")
    return cmp["total_commits"], lines


def pr_body(tag: str, core: str, old_sha: str, new_sha: str, old_version: str, plugin_version: str,
            total: int, lines: list[str], run_url: str | None) -> str:
    shown = "" if total <= len(lines) else f"\nShowing the last {len(lines)} of {total} commits.\n"
    run_line = f"\n- Release workflow run: {run_url}" if run_url else ""
    return f"""## What does this PR do?

SHA-bump PR for the existing `birkin-mnemosyne` catalog entry, following the
published core release `{tag}` (PyPI `{PYPI_PROJECT}=={core}`):
`{old_sha}` -> `{new_sha}`.

The entry keeps a full 40-character commit pin. `version` is the Hermes plugin
manifest version at the pinned commit (`{old_version}` -> `{plugin_version}`); `{core}` is
the core package version the plugin depends on.

## Changes Made

- Only `{CATALOG_PATH}`: `sha`, the pinned `docs_url`, `version`, and the core
  version named in `description`. Capabilities and every other field are unchanged.
- The automation does not re-evaluate the disclosure wording in `description` or
  `capabilities`; check them against the commit range below (admission rules 6, 13).

## Upstream commit range adopted

https://github.com/{SOURCE_REPO}/compare/{old_sha}...{new_sha}
({total} commits)
{shown}
{chr(10).join(lines)}

## How to Test

This PR was opened by release automation in the plugin repository after the
`{tag}` PyPI publish job succeeded.{run_line}

Not run by the automation (reviewer or author please run before merge):

1. `python scripts/validate_plugin_catalog.py {CATALOG_PATH}`
2. `hermes plugins validate --install-deps <checkout at {new_sha}>/{PLUGIN_SUBDIR}`
"""


def find_existing_pr(gh: GitHub, branch: str, new_sha: str) -> str | None:
    owner = FORK_REPO.split("/")[0]
    _, prs = gh.get(f"/repos/{UPSTREAM_REPO}/pulls?state=all&head={quote(owner + ':' + branch)}")
    if prs:
        return f"#{prs[0]['number']} ({prs[0]['state']}) from {owner}:{branch}"
    query = quote(f"repo:{UPSTREAM_REPO} is:pr is:open {new_sha}")
    _, found = gh.get(f"/search/issues?q={query}")
    if found["total_count"]:
        return f"#{found['items'][0]['number']} (open) already names {new_sha}"
    return None


def check_reused_branch(gh: GitHub, branch: str, base_sha: str, old_text: str) -> None:
    owner = FORK_REPO.split("/")[0]
    _, cmp = gh.get(f"/repos/{UPSTREAM_REPO}/compare/{base_sha}...{quote(owner + ':' + branch)}")
    changed = sorted(f["filename"] for f in cmp.get("files", []))
    if changed not in ([], [CATALOG_PATH]):
        raise CatalogError(f"{FORK_REPO}:{branch} changes files other than {CATALOG_PATH}: {changed}; "
                           "refusing to reuse it (delete the branch to start over)")
    merge_base = cmp["merge_base_commit"]["sha"]
    if merge_base != base_sha and file_at(gh, UPSTREAM_REPO, CATALOG_PATH, merge_base)[0] != old_text:
        raise CatalogError(f"{FORK_REPO}:{branch} starts from an older catalog ({merge_base}); its range "
                           "would not match upstream main (delete the branch to start over)")


def notice(message: str) -> None:
    prefix = "::notice title=Hermes catalog::" if os.environ.get("GITHUB_ACTIONS") == "true" else "NOTICE: "
    print(prefix + message, file=sys.stderr)


def run(tag: str, dry_run: bool) -> int:
    core = parse_tag(tag)
    write_token = os.environ.get("HERMES_CATALOG_TOKEN") or None
    if not dry_run and not write_token:
        notice(f"HERMES_CATALOG_TOKEN is not set; skipping the Hermes catalog PR for {tag}.")
        return 0
    gh = GitHub(read_token=write_token or os.environ.get("GITHUB_TOKEN") or None,
                write_token=None if dry_run else write_token)

    new_sha = resolve_tag(gh, tag)
    pyproject, _ = file_at(gh, SOURCE_REPO, "pyproject.toml", new_sha)
    found = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.split("[project]", 1)[-1], re.MULTILINE)
    if not found or found.group(1) != core:
        raise CatalogError(f"pyproject.toml at {tag} does not declare version {core!r}")
    require_on_pypi(core)
    manifest, _ = file_at(gh, SOURCE_REPO, f"{PLUGIN_SUBDIR}/plugin.yaml", new_sha)
    plugin_version = yaml_scalar(manifest, "version")

    _, main_ref = gh.get(f"/repos/{UPSTREAM_REPO}/git/ref/heads/main")
    base_sha = main_ref["object"]["sha"]
    old_text, _ = file_at(gh, UPSTREAM_REPO, CATALOG_PATH, base_sha)
    old_sha = yaml_scalar(old_text, "sha")
    if old_sha == new_sha:
        notice(f"upstream main already pins {new_sha} for {tag}; nothing to propose.")
        return 0
    new_text = rewrite_catalog(old_text, new_sha, plugin_version, core)
    total, lines = commit_range(gh, old_sha, new_sha)
    branch = f"catalog/birkin-mnemosyne-{tag}"
    existing = find_existing_pr(gh, branch, new_sha)

    print(f"{tag} -> {new_sha}; upstream main {base_sha}; {total} commits since {old_sha}; "
          f"branch {FORK_REPO}:{branch}", file=sys.stderr)
    if dry_run:
        sys.stdout.write(catalog_diff(old_text, new_text))
        if existing:
            notice(f"a real run would make no change: PR {existing}.")
        return 0
    if existing:
        notice(f"PR {existing}; not creating another and not modifying it.")
        return 0

    title = f"chore(plugins): pin birkin-mnemosyne to core {core}"
    status, _ = gh.call("GET", f"/repos/{FORK_REPO}/git/ref/heads/{quote(branch)}", ok=(200, 404))
    if status == 404:
        gh.call("POST", f"/repos/{FORK_REPO}/git/refs", {"ref": f"refs/heads/{branch}", "sha": base_sha}, ok=(201,))
    else:
        check_reused_branch(gh, branch, base_sha, old_text)
    branch_text, branch_blob = file_at(gh, FORK_REPO, CATALOG_PATH, branch)
    if branch_text not in (old_text, new_text):
        raise CatalogError(f"{FORK_REPO}:{branch} holds an unexpected {CATALOG_PATH}; refusing to touch it")
    if branch_text == old_text:
        gh.call("PUT", f"/repos/{FORK_REPO}/contents/{CATALOG_PATH}", {
            "message": title,
            "content": base64.b64encode(new_text.encode("utf-8")).decode("ascii"),
            "sha": branch_blob,
            "branch": branch,
        }, ok=(200, 201))
    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                   f"{os.environ.get('GITHUB_REPOSITORY', SOURCE_REPO)}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    old_version = yaml_scalar(old_text, "version")
    try:
        _, pr = gh.call("POST", f"/repos/{UPSTREAM_REPO}/pulls", {
            "title": title,
            "head": f"{FORK_REPO.split('/')[0]}:{branch}",
            "base": "main",
            "body": pr_body(tag, core, old_sha, new_sha, old_version, plugin_version, total, lines, run_url),
            "maintainer_can_modify": True,
        }, ok=(201,))
    except HttpError as exc:
        raise CatalogError(
            f"{exc}\nThe branch {FORK_REPO}:{branch} is ready; open the PR by hand: "
            f"https://github.com/{UPSTREAM_REPO}/compare/main...{FORK_REPO.split('/')[0]}:{branch}"
        ) from exc
    print(f"opened {pr['html_url']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose a Hermes catalog SHA-bump PR for a release.")
    parser.add_argument("--release-tag", required=True, help="published core release tag, e.g. v0.7.0")
    parser.add_argument("--dry-run", action="store_true", help="read only; print the catalog diff")
    args = parser.parse_args(argv)
    try:
        return run(args.release_tag, args.dry_run)
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
