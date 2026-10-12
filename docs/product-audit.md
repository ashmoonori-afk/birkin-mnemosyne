# Product journey audit

Status: implementation, focused QA, installed-wheel journeys and full-suite
comparison complete; final review and PR checks are in progress.

## Users and ideal state

- An agent user installs the MCP extra, connects a client, stores multilingual
  notes, resumes work and relies on complete, correctly scoped memory.
- A standalone user imports the Python package or inspects the same vault from
  the terminal, without hidden mutation of note content or usage ranking.
- A returning user upgrades an existing vault, edits labels, imports files,
  archives and restores notes, and can recover from interrupted operations.
- Two clients can share a vault without losing information or silently accepting
  stale writes. Errors identify an actionable cause without corrupting stdio.

The ideal experience preserves existing data, documented option precedence,
complete required context, platform support, and parity between client surfaces.
Convenience must not weaken the existing checked-undo and containment contracts.

## Starting revisions and preservation

Original base: `4b258d8`. Main `08e518d` adds editable labels and raw imports;
the final comparison baseline is `28556d3`, including Hermes metadata PR #81.
Previously verified changes were preserved as:

- `29255ab`: optional MCP startup paths and direct regression tests.
- `8295b02`: terminal note reads, vault resolution, checked undo and version.
- `c88af55`: English/Korean user guidance and the prior journey plan.

Main was integrated, not treated as interchangeable with the old baseline.
Its label/import behavior is included in the audit.

## Evidence and coverage boundaries

The first DeepSeek inventory reports were only partial evidence. Their shell
could not run local git; some overlap and ref-state assertions were incorrect.
The lead ran both comparisons locally:

```text
git diff --name-only 4b258d8
git diff --name-only 4b258d8..origin/main
```

The actual intersection was five files: CHANGELOG.md, README.md, README.ko.md,
birkin_mnemosyne/_mcp_app.py and birkin_mnemosyne/memory_index_cli.py.
`tests/test_index_format.py` was not a local modification. Main changed 41 files.
The actual merge produced one textual conflict, in memory_index_cli.py.

The complete path map is in [product-audit-coverage.md](product-audit-coverage.md).
All 60 production modules and 23 benchmark Python sources received assigned
read-only audits. Their findings were treated as hypotheses, not test results.
Focused reproductions, integration checks and the final suite own execution
evidence; a worker's file listing alone never proves correct behavior.

## Gap ledger

| ID | Observed difference | Evidence | Required outcome | State |
|---|---|---|---|---|
| A01 | New CLI outputs omit labels and list label_counts present in current main MCP responses; terminal label filtering is absent | Failing key-parity and AND-filter tests; real CLI label/list/show/undo and filtered recall | Corresponding surfaces retain metadata and filtering/pagination semantics | Fixed in 7b7a89f and db77927; 52 focused tests passed |
| A02 | Original CLI dispatcher and main independently add commands and init options | Actual merge conflict in `memory_index_cli.py` | Preserve label, group-by-label, raw imports, search/list/show/undo/version and vault precedence together | Fixed in 7b7a89f; 40 focused tests passed |
| A03 | A file supplied as MCP vault produces a Python traceback and exit 1 | Real `mnemosyne-mcp --vault README.md`: FileExistsError in `resolve_vault` | Startup configuration failures produce actionable stderr, empty protocol stdout and controlled failure | Fixed in e07191b; subprocess regression passed |
| A04 | A valid explicit budget cannot override an invalid environment budget | Both corresponding environment variables fail new regression cases before fix | Apply documented CLI precedence before validating the selected source | Fixed in e07191b; 18 tests and real stdio memory_capacity passed |
| A05 | Temporary staging repeats the destination name, overflowing valid long paths | Three new atomic writer cases fail before fix; Hermes baseline fails in mkstemp | Support valid long destinations without changing persistent identities or weakening publication checks | Fixed; 68 tests pass and real 256-character destination capture/latest/resume succeeds |
| A06 | Curation appends Related links under a later section or mistakes a fenced heading for a real one | Three failing cases: following section, fenced example, setext heading | Insert into the real section while retaining unrelated content | Fixed in ad434f4; 94 focused tests and real MCP curation passed |
| A07 | INDEX token warnings offer memory-retirement choices below actual capacity | New real-client regression fails before fix | Keep INDEX warnings visible but offer retirement only over capacity | Fixed in 70cf4e4; same focused suite and stdio journey passed |
| A08 | Upper/mixed-case supported extensions are silently omitted or refused | Seven failing source/import cases before fix; real `.MD` recall and `.TXT` import | Recognize supported extensions consistently without renaming files or losing bytes | Fixed in a0bebc0; source suite has 268 passes and one unchanged Windows symlink-privilege failure |
| A09 | A dot file inside a visible zone enters ordinary search | New hidden-zone regression returns `.private.md` before fix | Root and zone-level hidden files remain outside ordinary recall and fallback lookup | Fixed in a0bebc0; unit and real CLI/Python hidden-note scenarios passed |
| A10 | Unreadable INDEX state classifies every document as an orphan despite unknown routes | Strengthened corrupt-state test fails before fix | Preserve inventory/error reporting without invented route classification | Fixed in fdc5efc; 72 focused passes and real CLI exit-1 report |
| A11 | Quick-start instructions imply unreleased CLI commands exist in the published package, and omit the seed-note step | README commands compared against the feature/version history | Distinguish checkout installation and tell the user to create the example note | English/Korean quick starts corrected |
| A12 | Round-3 measurement runner imports benchmark-only tiktoken without a setup recipe in its user guide | Runner import and package extras inspected | State the separate dependency and exact replay invocation | Setup and replay section added to docs/round3.md |

## Exact scenario register

All paths below are task-owned fixtures. Tests must not operate on personal vaults.

1. Integration regression:
   `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
   --basetemp=C:/mnqa/integration tests/test_cli_notes.py
   tests/test_cli_vault_resolution.py tests/test_label_cli.py
   tests/test_mcp_startup_optional_paths.py`.
   PASS: prior commands and main's label behaviors work together, with matching
   CLI/MCP fields. Capture any failing test before implementing the correction.
2. MCP invalid vault: run installed `mnemosyne-mcp --vault <existing-file>`.
   PASS: controlled nonzero status, actionable stderr, no traceback or stdout,
   file bytes unchanged.
3. Budget precedence: start actual stdio server with
   `MNEMOSYNE_MAX_PROTECTED_NOTES=broken` and `--max-protected-notes 5`,
   then initialize and call `memory_capacity`.
   PASS: successful initialization and budget.max_protected equals 5.
   Without the explicit flag, invalid environment still fails at startup.
4. Final journeys run via
   `script/qa/product_journeys.py --evidence-dir .omo/evidence/product-audit`
   against an installed wheel outside the checkout, capturing actual stdio,
   terminal output, before/after bytes and cleanup.

Additional accepted-gap scenarios are listed below.
Existing green checks are retained only while their inputs remain unchanged.

5. Related placement and retirement: run
   `python -m pytest tests/test_curation_related.py tests/test_curation.py
   tests/test_mcp_server.py -q`, then the real stdio journey's
   `memory_curate` and `memory_review_questions` scenarios.
   PASS: links occur only in the real Related section; INDEX-only warnings
   retain capacity details but have no retire choices.
6. Case/hidden boundaries: run
   `python -m pytest tests/test_source_extensions.py tests/test_mnemosyne.py
   tests/test_memory.py tests/test_raw_imports.py tests/test_kibitzer.py -q`.
   PASS: original mixed-case paths and bytes survive recall/import/split,
   hidden-zone content is absent, and pre-existing containment guards remain.
7. Concurrent idempotency: the journey runner starts two real CLI processes
   with the same project/capture ID and identical work bytes, then waits for
   both process completions with a bounded timeout.
   PASS: two successful receipts refer to one path, with exactly one created=true.
8. Installed artifact: build a wheel, install it in a fresh environment outside
   the checkout, and run the journey script without `--allow-checkout`.
   PASS: recorded package provenance is site-packages, all assertions pass and
   the temporary root is removed. No paid model or live curation provider is used.

## Findings rejected or narrowed by lead verification

- The earlier Hermes reinitialization failure reproduces inside
  `tempfile.mkstemp`, before capture publication: it is a Windows path-length
  failure, not evidence of mixed provider state. Do not rewrite lifecycle
  assignment or blame stale bytecode without evidence.
- `--zone -_archive` and `--zone=_archive` are different input values; an
  argument-parser difference between them is not proof of a defect.
- An invalid *unoverridden* budget environment variable must still fail even
  when the other budget has a valid CLI override. A04 deliberately preserves it.
- The atomic-write documentation already scopes directory fsync to POSIX and
  qualifies durability by filesystem support. Do not weaken tests with xfail
  or claim unconditional Windows power-loss safety.

## Ongoing full-module coverage

The lead's actual `git ls-files birkin_mnemosyne/*.py` inventory contains
60 modules after integration. Nine modules are owned by the initial boundary
audit; the remaining modules are assigned to twelve sequential DeepSeek units:
retrieval, index, startup, handoff-store, handoff-retention, review-recovery,
curation, onboarding, labels, optional-features, mcp-tools, adapters-package.
The programmatic union check returned zero unassigned production paths.
All twelve units returned and were reviewed. Five additional serial units
covered all 23 benchmark Python sources. Full worker reports are retained as
local evidence under `.omo/evidence/product-audit/reports` in the control
workspace, not shipped as independently verified conclusions.

## Complete disposition of remaining audit leads

| Lead | Disposition and reason |
|---|---|
| Archive search apparently differs from list | Rejected by actual CLI execution: explicit `--zone _archive` returns the archived note. `-_archive` is a different invalid value, not an equivalent spelling. |
| Missing identity root should abort every server startup | Not accepted as a defect: identity reads are optional; their failures are reported at the tool boundary. No claim of successful required-file reading is made. |
| Bare OSError on a vanished file | Fail-closed behavior is retained. MCP maps expected I/O errors; direct library I/O exceptions do not imply lost data or a successful incomplete read. |
| Non-object JSON startup document should be rejected | Retained: valid JSON documents may be data; only the documented top-level registry declares must_read. Interpreting nested data as instructions would broaden the contract. |
| User-supplied absolute path echoed in an error | No new private root is disclosed by echoing the caller's own input. Out-of-root paths are rejected before reading; root-redaction tests remain. |
| All paths over the OS limit should gain an implicit Windows prefix | Not adopted. A05 fixes staging overflow of valid destinations without changing persistent path identities. The OS still governs unsupported final paths; explicit extended paths remain caller-controlled. |
| Hard links should be treated as symlinks | Not adopted: path containment is not an OS-level inode ownership sandbox. No promised hard-link rejection contract or data-loss reproduction was established. |
| Stat-preserving external edits | Existing stat-cache limit: use core rebuild() or Kibitzer force_refresh=True when metadata is deliberately preserved. Complete startup hashing remains. No full-vault hashing is added to ordinary search. |
| Reading an archived note reinforces it | Existing documented distinction: get_note records actual use; search and new terminal reads do not. Not a regression. |
| Fold summary omits gate-rejected captures | Deliberate: rejected captures stay active; only accepted inputs enter the summary. The report retains rejection reasons. |
| Explicit project might inherit a default task | Rejected by source tracing: required_scope delegates to scope_from_defaults and existing explicit-project cases pin task isolation. |
| Rezone followed by archive produces two outcomes | Sequential operations, not contradictory state; the audit records both. No implicit operation reordering was introduced. |
| Protected notes must reject supersede | Protection contract concerns automatic archiving/forgetting, not all annotation. Expanding it would silently change supported curation operations. |
| Hermes/OpenClaw plugin versions must equal core | Independent plugin and core versions are legitimate; main PR #81 explicitly aligns Hermes metadata. No artificial version synchronization was added. |
| Optional host registration is not covered by every test | Residual host-integration limit, not a reproduced defect. Official MCP stdio is exercised; Hermes provider behavior is covered by its existing adapter suites. No mock-only host compatibility claim is made. |
| Missing maxLength makes the long-path schema test vacuous | Rejected: JSON Schema without maxLength is unbounded; the existing test would fail if an insufficient finite cap were introduced. |
| Historical IDE snapshot mentions older tools/version | Labelled historical evidence, not a claim of current installed counts. The current installed-wheel probe records actual provenance separately. |
| Semantic sidecar is a directory not cleared by benchmarks | Rejected by source: np.savez writes an in-memory buffer published as one file. |
| Hybrid benchmark does not rebuild | Rejected: HybridEngine.build explicitly calls dex.rebuild. A benchmark must fail if its required semantic model is unavailable rather than silently label BM25 results as hybrid. |
| Python 3.10 cannot import typing.override in round4 | Rejected: runtime uses an explicit identity decorator; the typing-only import is under TYPE_CHECKING. |
| Frozen task costs or historical medians are wrong | No counterexample established. Existing corpus/scope labels are retained; no paid experiments or invented replacement measurements are published. |
| Same-day benchmark outputs overwrite | Existing deterministic output convention; keep distinct output directories or copy artifacts when retaining multiple runs. Not silent mutation of user memory. |
| hard_fixture has no bundled scoring runner | It is a fixture/count module, not a claimed runnable scorer in the README. The external companion is not represented as shipped here. |
| Optional benchmark model/setup gaps | Model-backed measurements require explicit extras/preparation. This run does not download large weights or relabel missing semantic measurements as pass. |
| Windows symlink tests fail at fixture creation | Environment limitation (WinError 1314), tracked separately from product failures. Tests are not skipped, deleted or weakened. |

No accepted production gap in A01-A10 is deferred. Final whole-suite and
installed-artifact results are recorded below.

## Final verification ledger

- Coverage comparison: all 240 tracked checkout paths have explicit rows in
  `product-audit-coverage.md`; newly added audit documents are also included.
- Refreshed baseline `28556d3`, Python 3.12.11 with `dev,mcp,semantic`:
  1,731 passed, 23 failed, 10 skipped in 1,451.04 seconds. Three failures occur
  while creating symlink fixtures without Windows privilege (WinError 1314);
  twenty occur in the old long-name atomic staging path. Evidence:
  `baseline-full.txt`. The baseline used `C:/mnqa/baseline-full`; the candidate
  uses the goal's required `C:/mnqa/final`, so path-length improvements are
  additionally established by A05's fixed-length regression and real CLI proof,
  not inferred solely from differing full-suite temporary directories.
- Ruff comparison over all 26 changed Python files: seven findings on both
  revisions, zero new findings. Existing findings are in `memory.py`,
  `mnemosyne.py`, `test_label_cli.py` and `test_mcp_optional.py`.
  Both lint commands exit 1; this is a no-regression result, not a claim that
  the baseline is lint-clean. Evidence: `ruff-comparison.json`.
- The wheel build exited 0 and its `mcp,semantic` extras installed in a fresh
  environment outside the checkout. The real journey command exited 0 with
  50 JSONL records and package provenance under
  `C:/mnqa/wheel-env/Lib/site-packages/birkin_mnemosyne`.
  It covers real stdio writes/search/stale updates/restore/startup/fold/undo,
  CLI reads/import/init/undo/corrupt INDEX, empty startup rejection, a
  256-character destination, two-process idempotent capture, offline semantic
  fallback without a model download, and profile close durability.
  The temporary vault was removed. Evidence: `journey-wheel/journeys.jsonl`,
  `journey-wheel.log`, and `wheel-build.md` (wheel SHA256).
- Candidate full suite: 1,800 passed, 3 failed, 10 skipped in 1,507.34 seconds,
  with MCP, semantic and static-model suites enabled. All three failures are
  the same WinError 1314 fixture-creation failures present in the baseline:
  `test_handoffs.py::test_symlinked_ancestors_are_refused`,
  `test_memory_index_consistency.py::test_warnings_ignore_internal_and_transient_files_when_scanning`,
  and `test_raw_imports.py::test_linked_import_paths_are_refused`.
  No new failing test identity exists. Evidence: `final-full.txt`.
- Sonnet's scoped integration/code-quality review returned APPROVE with no
  correctness blocker; Haiku found no bilingual documentation mismatch.
  Haiku did not independently trace source code. A Sonnet line-ending concern
  was disproved by `git ls-files --eol` (`i/lf w/lf` for the QA script).
  These checks do not replace the pending final goal gate.
- `examples/quickstart.py` and `examples/automatic_profiles.py` both exited 0
  using that installed interpreter outside the checkout. Output confirms the
  expected ingress note and all five persisted profiles. Evidence:
  `example-quickstart.txt` and `example-profiles.txt`.
  Provider-backed curation and large model measurements were not run; the
  real deterministic MCP curation journey and optional regression suites
  cover the changed contracts without claiming a paid-provider integration.
