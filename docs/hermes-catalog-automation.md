# Hermes plugin-catalog automation

Each published release of `birkin-mnemosyne` can propose a SHA-bump pull request
for `plugin-catalog/birkin-mnemosyne.yaml` in
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/main/plugin-catalog).
The catalog's admission rules (its `plugin-catalog/README.md`) require that every
pin is a full 40-character commit SHA and that every SHA bump is a **new PR**,
re-reviewed against the adopted commit range. A maintainer still reviews and
merges it; nothing here merges anything.

## Flow

1. A GitHub release is published (or `release.yml` is run by hand on a tag).
2. `release.yml` builds, tests and publishes to PyPI. Only if `publish` succeeds,
   and the run is for a tag that is not a pre-release, the `hermes-catalog` job
   calls `.github/workflows/hermes-catalog.yml`.
3. `scripts/update_hermes_catalog.py --release-tag vX.Y.Z`:
   - validates the tag (`vX.Y.Z` only; it is passed through an environment
     variable and argv, never interpolated into shell);
   - resolves the tag to its commit, following annotated tag objects;
   - checks `pyproject.toml` at that commit declares `X.Y.Z` and that
     `birkin-mnemosyne==X.Y.Z` is on PyPI (retries for about two minutes to
     absorb PyPI's API lag);
   - reads `integrations/hermes/plugin.yaml` at that commit for the plugin version;
   - takes a snapshot of upstream `main` and rewrites only `sha`, the pinned
     `docs_url`, `version`, and the `published birkin-mnemosyne X.Y.Z` phrase in
     `description`;
   - refuses a pin that is not strictly ahead of the current one;
   - creates branch `catalog/birkin-mnemosyne-vX.Y.Z` in
     `ashmoonori-afk/hermes-agent` **at the upstream main commit** (the fork's
     own `main` is never merged, rebased or force-pushed), commits the one file,
     and opens a PR to `NousResearch/hermes-agent:main`.

The PR body lists the old and new SHAs, a compare link and the commit subjects in
the range (inside code spans, so `#123` and `@name` in subjects do not link
issues or ping anyone). It says plainly which checks the automation did **not**
run (`scripts/validate_plugin_catalog.py`, `hermes plugins validate
--install-deps`) and that disclosure wording in `description`/`capabilities` is
not re-evaluated automatically. The script never comments, requests reviewers,
or mentions maintainers.

## Idempotency and existing PRs

The script makes no write when any of these hold:

- upstream `main` already pins the release commit;
- any PR (open or closed) exists from `ashmoonori-afk:catalog/birkin-mnemosyne-vX.Y.Z`;
- an open upstream PR already contains the new full SHA (GitHub search), such
  as a hand-made PR for the same release. Search indexing can lag, so the
  branch check above is the primary guard.

A rerun after a partial failure may reuse the release branch, but only after
comparing it with upstream `main`. The comparison must show that the branch
changes nothing but `plugin-catalog/birkin-mnemosyne.yaml`, that the catalog at
its merge base equals the one on current upstream `main` (so the PR's old -> new
range is the one the body claims), and that its catalog file is either untouched
or exactly the expected new file. Otherwise the script refuses without any write
and asks for the branch to be deleted. If those checks pass, it commits the file
if it is missing and opens the PR. The branch is never merged or rebased. The script never edits, retargets or
pushes to a branch that has a PR, and a different release always uses a
different branch, so it cannot mutate an earlier release's PR. Concurrent runs
for one tag are serialized by the workflow's `concurrency` group.

## Release contract

The automation handles stable releases only, following this repository's
convention (tags `v0.2.0` ... `v0.7.0`):

- the tag is exactly `vX.Y.Z` and equals `v` + `[project].version` in
  `pyproject.toml` (`release.yml` already enforces this for the wheel);
- the GitHub release is published and not marked as a pre-release. The
  `hermes-catalog` job is skipped for pre-releases, and the script rejects any
  tag outside `vX.Y.Z`, such as `v0.8.0rc1`, with exit 1;
- PyPI has `birkin-mnemosyne==X.Y.Z`.

Tests and dry runs never publish: the unit tests use a fake transport, and the
`hermes-catalog` workflow has no build or publish step.

## Token setup

Writes use **only** the `HERMES_CATALOG_TOKEN` environment variable (a repository
secret in Actions). The script never falls back to the `gh` CLI's stored login,
and `GITHUB_TOKEN` is used only for read requests. Without
`HERMES_CATALOG_TOKEN` a real run prints a notice and exits 0, so a release never
fails because of the catalog step.

The token must be able to (1) create a branch and commit in
`ashmoonori-afk/hermes-agent` and (2) open a pull request on
`NousResearch/hermes-agent`.

- **A fine-grained PAT does not suffice.** GitHub's PAT documentation states
  that fine-grained personal access tokens cannot be used to contribute to public
  repositories where the user is not a member
  ([GitHub Docs: managing personal access
  tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)).
  A fine-grained token with Contents read/write on the fork can push the release
  branch, but it cannot open the PR on `NousResearch/hermes-agent`. With such a
  token the script pushes the branch, then exits 1 with the HTTP error and a
  ready-made compare URL so a person can open the PR by hand.
- **Recommended: a dedicated new classic PAT with only the `public_repo` scope
  and an expiry date.** It covers both steps. Because it applies to every public
  repository of the account, use it for nothing else, store it only as the
  `HERMES_CATALOG_TOKEN` repository secret, and rotate it before it expires. Do
  not reuse or copy an existing personal token, including the one held by a
  local `gh` login.

### Current token and renewal

The `HERMES_CATALOG_TOKEN` repository Actions secret in
`ashmoonori-afk/birkin-mnemosyne` holds a dedicated classic PAT with only the
`public_repo` scope and a **90-day expiry**. It was created on 2026-10-12, so it
expires around 2027-01-10. The exact date is shown on the token's page under
GitHub Settings -> Developer settings -> Personal access tokens -> Tokens
(classic); check it there rather than relying on this estimate. GitHub emails the
account owner before a token expires.

After expiry, release runs still publish to PyPI, but the `hermes-catalog` job
fails visibly (HTTP 401 on its first request). The PyPI publish is never undone.

Renewal, before the expiry date:

1. On the token's page, choose **Regenerate token**, keep only `public_repo`, and
   set a 90-day expiry. Alternatively, create a new dedicated classic token with
   the same settings and delete the old one.
2. Paste the new value directly into the repository secret: Settings -> Secrets
   and variables -> Actions -> `HERMES_CATALOG_TOKEN` -> Update. Do not store it
   anywhere else.
3. Note the new expiry date where the maintainers track renewals.
4. If a release ran while the token was expired, rerun the **hermes-catalog**
   workflow by hand for that tag with `dry_run: false`. It is idempotent.

A dispatch dry run does not receive the secret at all (the workflow passes it
only when `dry_run` is false), so it cannot prove the token works; the next real
run does.

To add the secret: repository Settings -> Secrets and variables -> Actions ->
New repository secret -> `HERMES_CATALOG_TOKEN`.

## Running by hand

Dry run (read-only, no token needed; prints the unified catalog diff on stdout,
progress and notices on stderr):

```sh
python scripts/update_hermes_catalog.py --release-tag v0.7.0 --dry-run
```

From Actions, run the **hermes-catalog** workflow (`workflow_dispatch`) with a
tag and `dry_run` (default `true`). A dry run gets no `HERMES_CATALOG_TOKEN`
(reads use the job's read-only `GITHUB_TOKEN`) and makes no external writes.
This workflow never builds or publishes to PyPI; `release.yml` is the only
publisher. Running it with `dry_run: false`
retries the PR for an already-published release.

`release.yml` still works by hand (`workflow_dispatch`). The catalog job runs only
when it was dispatched on a tag ref.

## Tests

`tests/test_hermes_catalog_automation.py` replaces the script's single network
function with an in-memory fake. Any request the fake does not expect fails the
test, so no test reaches GitHub or PyPI or creates a PR.
