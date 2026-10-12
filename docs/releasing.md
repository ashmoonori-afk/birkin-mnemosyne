# Release maintenance checklist

Every release ships three things: a version bump with docs, a PyPI publish
through the existing manual tag/workflow process, and a landing-site redeploy
from the `site/` static root. **Nothing below changes the publishing process**:
PyPI releases stay a manual tag followed by the `release` workflow, and the
site stays one Vercel project. The checklist only makes the required steps
explicit so a release cannot ship with stale docs, missing notes, or an
unverified site.

## 1. Version bump

Bump the version in every place the alignment test enforces
(`tests/test_version_alignment.py`), so CI passes on the release branch:

- [ ] `pyproject.toml` — `[project].version`
- [ ] `birkin_mnemosyne/__init__.py` — `__version__`
- [ ] `integrations/hermes/pyproject.toml` and `integrations/hermes/plugin.yaml`
      — pin `birkin-mnemosyne==<version>` and match each other's version
- [ ] `integrations/hermes/README.md` and `integrations/openclaw/README.md`
      — install lines reference `==<version>`

## 2. Changelog, READMEs, release notes, site copy

Required for **every** release, without exception:

- [ ] `CHANGELOG.md` — add `## <version> - <YYYY-MM-DD>` with the same
      section style as prior entries (`Fixed`, `Added`, `Documentation`)
- [ ] `README.md` — update English content; it is the PyPI long description,
      so every link must stay absolute (`tests/test_readme_links.py` rejects
      relative links)
- [ ] `README.ko.md` — update Korean content in parallel
- [ ] Site English and Korean copy in `site/` (both routes, `/` and `/ko/`),
      matching the README facts
- [ ] GitHub release notes — prepare them from the CHANGELOG entry, then
      publish them with the release tag (step 5)

## 3. CI

- [ ] Open the release PR and let `tests.yml` run: core, mcp and semantic
      jobs across ubuntu, **windows** and macos and the Python matrix
      (3.10–3.14). Windows must pass — a release is not green on Linux alone.
- [ ] All checks green, including the incremental document-length check.

## 4. Landing preview, review and guarded merge

The static root is `site/` and the destination is the existing Vercel project
`birkin-mnemosyne` only — no other project, no config changes. Deploy with
`npx -y vercel@latest` throughout.

- [ ] From the repository root at the release PR head, run
      `npx -y vercel@latest deploy --target=preview` and record its **preview** URL.
      The project root setting is `site/`; do not apply that path twice.
- [ ] **Verified-preview rule:** the source tree the preview is built from
      must equal the tree that will be merged. Any change to the PR head
      after review invalidates the review — re-run QA and re-approve on the
      new head before merging.
- [ ] Browser QA on the preview, both routes `/` and `/ko/`:
      - widths 1440 and 390
      - light and dark themes
      - all links work (including locale switch), no console errors,
        performance within the measured navigation/CLS/asset metrics from
        `site/DESIGN.md` (reported as measurements, not a Lighthouse score)
- [ ] Independent approval: an exact-head GPT-6.1 Sol **APPROVE** on the
      reviewed commit.
- [ ] All CI passes, including Windows.
- [ ] Record the full reviewed SHA with `git rev-parse HEAD`, and confirm
      it equals `gh pr view <PR> --json headRefOid --jq .headRefOid`.
      Merge with `gh pr merge <PR> --squash --match-head-commit <reviewed-SHA>`.
      Pass the actual SHA, not the literal word `HEAD`. A moved head requires
      a new approval and passing checks.

## 5. Publish the release and promote the site

- [ ] Tag the merged commit `v<version>` (must match `pyproject.toml`
      exactly — `release.yml` fails the build otherwise) and push the tag:
      `git tag -a v<version> -m "v<version>" && git push origin v<version>`.
      Do not move an existing published tag.
- [ ] Run the `release` workflow from Actions on the tag ref
      (workflow_dispatch). It builds the sdist/wheel with `python -m build`,
      checks them with `python -m twine check --strict`, verifies the wheel
      version equals `pyproject.toml` and the tag, smoke-installs the wheel
      into a fresh venv and runs the test suite against the installed wheel,
      then publishes to PyPI through the Trusted Publisher (OIDC).
- [ ] Confirm the build **and** publish jobs both complete; the `build` job
      finishing is not a release.
- [ ] Create the GitHub release for `v<version>` with the prepared notes.
- [ ] After the merge, **only then** promote the verified preview to
      production in the `birkin-mnemosyne` project
      (`npx -y vercel@latest promote <verified-preview-url>`).
- [ ] Confirm production at https://birkin-mnemosyne.vercel.app and
      https://birkin-mnemosyne.vercel.app/ko/.

## 6. Record completion

- [ ] Record the release tag, PyPI version, merged PR, reviewed SHA, deployment
      URL and browser evidence. Close every task-owned QA browser and server.
- [ ] Check that both README landing links still resolve. The release is not
      complete while its documentation or production landing page is stale.
