# Latest README measurements

Intent: clear. Owner approved planning and execution up front.
Tier: HEAVY, because owner explicitly demands an independent exact-head review.
Final review: separate GPT-6.1 Sol child, read-only, APPROVE exact commit.
No planning-only pause: this is an execution request with an ulw-plan-shaped artifact.

## Users, ideal state and observed gaps

English and Korean project evaluators use the README to understand quality,
resource costs and memory-routing limitations before installing the package.
Both must see the same latest reproducible measured values, exact source
precision, declared platform/date/commit and honest regression caveats.

1. README retrieval numbers match the old frozen results, but measurements
   predate search scan throttling (#16), incremental document lengths (#26),
   model revision pinning (#39) and cache-write coalescing (#52). Re-run on
   main; preserve frozen queries and configuration, never tune on test data.
2. README INDEX headline still reports 45,128 -> 1,781 at the #60 product
   subtree. Current main includes grouped indexes and changed startup
   verification (#68/#71/#72); re-run public INDEX/task runners.
3. Latest replacement private snapshot results already exist anonymously in
   docs/memory-index-results.md. Preserve their explicit different-corpus,
   historical-measurement boundary; do not restore, read or rerun private data.
4. Old sources have incomplete calendar/revision provenance for expansion and
   reference latency. Fresh public runs must bind full main SHA and date.
5. Both READMEs must update together. No production behavior, fixture,
   scorer, package version, release/tag/PyPI or unrelated upstream PR changes.

## Ground truth and source inventory

Base: 876ad40159399666f11642cfcfaab536c2d8e9fc, 2026-10-11.
README.md:80-84 / README.ko.md:80-84 expansion 0.205 -> 0.981 / 0.952:
benchmarks/retrieval/RESULTS.md:456-625.
README.md:146-150 / README.ko.md:144-148 INDEX 45,128 -> 1,781, 12/12:
docs/memory-index-results.md and benchmarks/memory_index/results.json.
README.md:154-350 / README.ko.md:152-345 retrieval quality/footprint:
benchmarks/retrieval/RESULTS.md:627-885,
benchmarks/retrieval/semantic_test_run.json (old c0657fb frozen run).
README.md:352-377 / README.ko.md:347 onward historical Korean comparison
and expansion costs: retrieval RESULTS historical comparisons.
No test-count claims in either README. Non-measurement values (Python minimum,
configuration budgets, weights, timeouts, versions, PR identifiers) stay intact.

## Topology and ordering

Completed parallel read-only explore lanes: measurement-inventory and
benchmark-history; librarian merge-contract established --match-head-commit.
Root verifies their findings, owns all benchmark runs, edits and final QA.
Known procedure with no unresolved architecture decision: no planning child.
Use quick edit children only if genuinely independent edits emerge; source
and translated README updates share numbers and should remain one root unit.
After all proof is captured, one independent Sol reviewer reads a locked
dedicated final-head worktree; it cannot edit the implementation.

## Ordered work and exact scenarios

1. Bootstrap environment:
   `/usr/bin/python3 -m venv .venv`
   `.venv/bin/python -m pip install -e ".[dev,mcp,semantic]" tiktoken==0.14.0`.
   PASS: successful install. Environment removed at finish.
2. Prepare model explicitly in task-owned cache:
   `MNEMOSYNE_MODEL_CACHE=/home/hp/work/mn-readme-results/model-cache HF_HOME=/home/hp/work/mn-readme-results/hf-cache .venv/bin/python -m birkin_mnemosyne.semantic`.
   PASS: pinned model prepared successfully; preserve measured cache sizes
   in evidence and remove task-owned caches after all tests/runs.
3. Frozen INDEX:
   `.venv/bin/python -m benchmarks.round4.run --check-inputs-only`
   `.venv/bin/python -m benchmarks.memory_index.run --output /home/hp/work/mn-readme-results/evidence/index-main.json`.
   PASS: inputs unchanged, both answer sets 12/12, byte-perfect reconstruction,
   runner cleanup reports removed temporary vaults. Record main product tree.
4. Public task delivery:
   `.venv/bin/python -m benchmarks.memory_triggers.run --output /home/hp/work/mn-readme-results/evidence/triggers-main.json`.
   PASS: all 16 frozen cases full-body correct/verified, all 480 routes retained,
   empty negatives; exact output records costs and extras, temporary vault cleanup.
5. Retrieval + expansion + semantic:
   `.venv/bin/python benchmarks/retrieval/bench_retrieval.py --engines bm25 hybrid expanded-claude expanded-gpt --sizes 160 1000 10000 --json /home/hp/work/mn-readme-results/evidence/retrieval-main.json --install-size --install-extras semantic`.
   Then `.venv/bin/python benchmarks/retrieval/compare.py /home/hp/work/mn-readme-results/evidence/retrieval-main.json /home/hp/work/mn-readme-results/evidence/retrieval-main.json --engine-before bm25 --engine-after hybrid`
   and same with `--engine-after expanded-claude` / `expanded-gpt`.
   PASS: successful test-split reports for all authors/languages/sizes with
   unchanged fixtures/configuration; no missing semantic engine fallback.
6. Update source results using apply_patch, keeping original historic runs
   explicitly historical. Add latest-main artifact(s) and date/SHA/platform.
   Do not replace separate historical reference latency with unrelated fields
   under its old label; report fresh-run timing with its actual runner scope.
7. Update both README variants from latest section/artifacts: all retrieval
   cells, losses prose/tables, expansion figures/caveats, INDEX startup/answers,
   task-read public results and published private aggregates. Fresh footprint
   fields use source's exact precision/units; cache figures measured separately.
8. QA numeric inventory and rendered/readable documentation:
   `git diff --check`; root read-based comparison of every table and numeric
   prose against captured sources. PASS: full parity, exact precision, no
   Hangul in English, caveats preserved. Store inventory/diff evidence.
   This is data/prose work: resulting Markdown and source JSON are first-class
   surface artifacts; no new prose-pinning tests.
9. Local CI:
   `.venv/bin/python -m pytest -q`
   `.venv/bin/python -m pytest -v tests/test_incremental_doclen.py`.
   PASS: zero failures, extras available; identify any existing model/network
   skips honestly. Also run applicable ruff checks as existing repo requires.
10. Read recent history and touched-path history, stage exact scope, commit one
    coherent verified docs/results increment; footer names this plan.
11. Push new branch; `gh pr create --base main --head <branch> ...` exactly once.
12. Exact-head Sol review in dedicated locked worktree, all criteria/evidence
    supplied; PASS only explicit APPROVE with full head SHA. Any change after
    review invalidates it and requires fresh review.
13. `gh pr checks <PR> --watch` via monitor; require every reported CI green,
    not merely required subset. Re-read PR head and status.
14. `gh pr merge <PR> --squash --match-head-commit <approved-head>`.
    `gh pr view <PR> --json state,mergedAt,mergeCommit,headRefOid`.
    PASS: MERGED exact independently approved CI-green head.
15. Cleanup environment, task-owned caches, review worktree and runtime
    resources; retain evidence/notepad. Append receipts, final status and stop.

## Evidence and report

Evidence root: /home/hp/work/mn-readme-results/evidence/.
Notepad: /tmp/ulw-20261011-140613.cj7cIo.md.
Owner report: append-only /mnt/c/Users/HP/jarvis/mnreadme/status.md.
Record exact commands, SHA, pass/fail, output paths, cleanup and reviewer model.
Final includes PR, old->new headline numbers, reruns, no open items if complete.

## Authorized 0.7.0 release extension

Owner's 2026-10-11 14:15 KST instruction supersedes the initial no-release
constraint. Continue after README PR merge and green main CI. Inspect previous
release PR #62 and workflow: release.yml is workflow_dispatch only, not tag
triggered. Previous process tags the squash merge, dispatches on tag, downloads
the exact published dist artifact, then manually creates GitHub release with
those sdist/wheel assets. Follow it, do not alter the release workflow.

Repository had no CHANGELOG.md: #62 kept notes solely in GitHub release body.
Owner explicitly requests a CHANGELOG entry; create a 0.7.0 entry from merged
#67/#68/#71/#72 and README refresh, without fabricating an existing Unreleased
section. Historical result sections remain historical, not version-relabelled
current features. Current README feature prose becomes shipped in 0.7.0.

Release sequence/QA:
1. Verify main tests on merged README head.
2. Read all six version-bearing paths enforced by tests/test_version_alignment:
   pyproject.toml, birkin_mnemosyne/__init__.py, integrations/hermes/{pyproject.toml,
   plugin.yaml,README.md}, integrations/openclaw/README.md. Bump 0.6.0 -> 0.7.0.
3. Move any actually existing Unreleased notes to 0.7.0, create CHANGELOG if
   absent, update English/Korean current-feature labels and current usage guide.
   Preserve unresolved #65 hard-link filesystem regression and #66 wheel CLI
   checkout-testing gap as known issues, not fixes.
4. Run full installed-extra tests, version-alignment cases and package build +
   twine strict validation; evidence saved under evidence/release/.
5. Commit release increment, open second dedicated release PR, Sol exact-head
   read-only independent APPROVE and all 21 CI green.
6. `gh pr merge <release-PR> --squash --match-head-commit <approved-head>`.
7. `git tag v0.7.0 <release-merge-SHA>`; `git push origin v0.7.0`.
8. `gh workflow run release.yml --ref v0.7.0`; subscribe using
   `gh run watch <run-id> --exit-status`. PASS: build and Trusted Publisher
   publish succeeded. Download exact workflow artifact with
   `gh run download <run-id> --name dist --dir <owned-artifact-dir>`.
9. `gh release create v0.7.0 <exact-wheel> <exact-sdist> --title
   "birkin-mnemosyne v0.7.0" --notes-file <reviewed-release-notes>`.
10. HTTP `GET https://pypi.org/pypi/birkin-mnemosyne/0.7.0/json`: PASS 200 and
    info.version=0.7.0; capture response/version/digests.
11. Clean owned venv outside checkout: `python3 -m venv <clean-dir>`;
    `<clean-dir>/bin/python -m pip install birkin-mnemosyne==0.7.0`;
    import check from outside checkout prints/asserts __version__=0.7.0 and
    site-packages path. PASS includes real published package behavior smoke.
12. `gh release view v0.7.0 --json url,tagName,assets,publishedAt`: PASS correct
    tag with wheel and sdist assets matching published artifact checksums.
13. `gh run watch <release-main-tests-run> --exit-status`: PASS main CI green.
14. Remove owned verification envs/build/runtime resources, preserve evidence,
    append final RESULT with README PR and release URLs, install yes/no and
    known #65/#66 open. Complete goal only at this extended stop condition.
