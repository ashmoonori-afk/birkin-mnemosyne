# mn-070-features - Work Plan

Canonical task/plan root: `/Volumes/toshiba/work/mn-070-features`.
Implementation references below are relative to the Feature A worktree
`/Volumes/toshiba/work/mn-070-features/handoff`, unless an absolute path is given.
The unchanged baseline is `/Volumes/toshiba/work/mn-070-features/repo`.
After plan approval, export an identical reviewed copy into the feature PR's
`.omo/plans/` directory; this task-root file remains the canonical plan.

Execution checkpoint: Item A merged as PR #79 at
`4b258d8a8bce95ec115d7a2537f5a24bbe07b98a`, after exact-head Sol approval and
all 21 CI jobs passed. Item B references now resolve against
`/Volumes/toshiba/work/mn-070-features/labeling` on branch `mn-070-labels`.
The baseline checkout remains unchanged. Routine label interfaces are specified
in the task evidence file `evidence/labeling-contract.md`.

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**Who this is for and what changes for them:** Agents can resume the right
project without losing the last session's work. Memory owners can organize and
find notes with editable suggestions while keeping their own tags and source data.

**What you'll get:** Two independently checked changes for version 0.7.0:
session handoff memory, then note and imported-data labeling. Each includes
working commands, integrations, bilingual guidance and measured costs.

**Why this approach:** Session records are immutable and scoped; labels stay
separate from search-scoring text. Existing complete-read verification and
reversible curation are reused, with one proven file-move safety defect fixed first.

**What it will NOT do:** Delete original notes, overwrite handoffs, require a
paid model, change retrieval ranking, or publish a release.

**Effort:** XL
<!-- Effort is exactly ONE band, never hours/days. Quick = single edit, minutes of agent work; Short = one focused change, a few files; Medium = multi-file feature in one session; Large = several waves, one long session; XL = multi-session or architectural work. A written duration is rewritten to a band. -->
**Risk:** High - new persistent session state crosses startup, host callbacks
and reversible file operations.
**Decisions to sanity-check:** Exact project/task keys; fail visibly rather than
truncate required context; preview imports and label edits; preserve all frozen
retrieval results.

Your next move: none; the owner has preapproved planning, implementation and
protected merges. Review the completed plan, then execute its bounded phases.

---

> TL;DR (machine): XL / HEAVY / two verified 0.7.0 PRs; 26 execution tasks,
> four final audit items; at most two implementation workers; no release.

## Scope
### Affected user and ideal state
<!-- From the draft ledger: who this touches and how they use the result, then one IS row per property with its reason, then one GAP row per difference with its reason. Every todo below closes a GAP row; ## Success criteria proves every IS row. -->
**Affected user:** Agents resuming a project/task, developers integrating CLI/MCP
and Hermes, and owners maintaining a local Markdown vault. They already have
complete INDEX startup and editable notes; after this work they also have scoped
session continuity and useful, reversible label suggestions without a model.

| Row | Statement | Reason |
| --- | --- | --- |
| IS-1 | API, CLI, MCP and Hermes capture complete scoped handoffs deterministically. | Work survives session ends and compaction without credentials. |
| IS-2 | Fresh startup includes the exact latest active-scope handoff and complete INDEX with verified coverage. | No context loss, cross-project leakage or silent truncation. |
| IS-3 | Retention writes a new dated summary, gates archival, retains originals and supports checked undo. | Context stays manageable without losing history. |
| IS-4 | Init previews and explicitly enables handoff support without overwriting notes. | Existing onboarding remains safe. |
| IS-5 | Writes/import/init attach readable deterministic suggestions while preserving user tags and edits. | Labels organize memory without asserting unsupported facts. |
| IS-6 | Markdown/text/JSON inputs become labeled candidates in a no-write preview, with explicit apply and recoverable changes. | Owners inspect raw-data transformations first. |
| IS-7 | Search/MCP filters, optional label topic grouping and init counts make labels usable. | Metadata serves actual recall and curation. |
| IS-8 | Every frozen author/slice and existing startup safety contract remains nonregressed; added tokens are measured. | Organization cannot silently degrade recall or increase context cost. |
| IS-9 | Two reviewed PRs merge on exact approved heads with Windows-inclusive CI green, before another session releases. | The shipped tree is the verified tree. |
| GAP-1 | No scoped handoff model, capture API or immutable event storage exists. | Requires a new bounded domain, not ordinary overwrite semantics. |
| GAP-2 | Startup has retrieval text but no project/task identity or mandatory latest handoff. | Scope must remain distinct from the lexical task query. |
| GAP-3 | Archive gates and journals exist separately and assume existing source images. | Immutable new summary publication and undo need an explicit contract. |
| GAP-4 | Hermes provider callbacks and handoff enablement are not implemented. | Wire real host methods and explicit init choices. |
| GAP-5 | The note writer reconstructs a fixed header without labels. | Readable edits and user tags must be deliberately preserved. |
| GAP-6 | Import currently accepts only a Markdown directory. | Text/JSON candidate conversion must be lossless and previewed. |
| GAP-7 | Search/grouping/reports do not consume labels. | Add filters, grouping and counts without changing scores. |
| GAP-8 | Existing benchmark directly writes unlabeled fixture vaults. | Candidate proof must actually apply production labeling. |
| GAP-9 | Feature docs, costs, regression cases and exact-head shipping receipts are absent. | Capture complete evidence for each PR. |

### Must have

Every requirement from `/Volumes/toshiba/work/mn-070-features/BRIEF.md`, Items A
and B. One PR per item, A before B. Preserve stdlib-only Python >=3.10 core and
existing optional provider/MCP patterns. Optional richer provider summaries or
labels may use the current registry, but no model is required.

Record complete handoff work, decisions, open items, open questions, next step
and links. Scope project/task identity independently of session ID and retrieval
query. Keep INDEX never-dropped and handoffs complete/verified. Retention keeps
original bytes and supports conflict-detecting undo. Labels cover type,
topic/zone, project, people/entities, dates, language and imported-data source.
User-set tags and editable suggestions must survive subsequent writes.

README.md, README.ko.md and CHANGELOG under 0.7.0 are required for each feature.
Report startup token costs and frozen ranking changes in the final owner result.

### Must NOT have (guardrails, anti-slop, scope boundaries)

No tags, GitHub release, release-workflow dispatch or PyPI publication. No
changes outside the authorized workspace, except the bound memory tool and
read-only external source/skill/session evidence. Do not touch other tmux
sessions, live services or `~/.omo` configuration. No paid-provider requirement,
ranking tuning, altered frozen fixtures, deleted originals, overwritten
handoffs, suppressed diagnostics or weakened tests. Keep at most two concurrent
implementation helpers. No unrequested framework, database, compatibility layer
or broad cleanup.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: read the existing pytest cases first, add behavioral regression
  cases that fail without the feature, then implement and run the related tests.
  Pure prose receives QA-by-read, not prose-pinning tests.
- Evidence root: `/Volumes/toshiba/work/mn-070-features/evidence/`, as required by
  the owner. Reference these real artifacts in the ulw-loop ledger/criteria.
- Every write scope gets LSP diagnostics and a diff review. No unrun check is
  labeled passing. Existing required CI is the 21-job core/MCP/semantic matrix
  across Windows/macOS/Linux and Python 3.10/3.12/3.13/3.14.
- Baseline: `repo/` at `7b137e8e6d16d973cf0304f1164f43fae7e4281b` passed
  1,187 tests with all optional suites enabled. `evidence/baseline-tests.log`
  contains the command/output; the monitor exited 0.
- Frozen baseline: `evidence/retrieval-before.json` and `.log` contain all four
  engines (bm25, hybrid, expanded-claude, expanded-gpt), sizes 160/1,000/10,000,
  1,440 queries per row, three authors and both dev/test splits. No fixtures
  changed. Reuse the same pinned semantic model and environment for the candidate.
- Export `PATH=/Users/MoonGwanghoon/.local/bin:$PATH`,
  `UV_CACHE_DIR=/Volumes/toshiba/work/mn-070-features/.uv-cache` and
  `TMPDIR=/Volumes/toshiba/work/mn-070-features/qa-temp`. Set pytest `--basetemp`
  to a unique task-owned path. Limit benchmark compute threads to one.
- Capture CLI subprocess stdout/stderr and JSON; these are first-class
  auxiliary surfaces for this CLI/data product. MCP proof uses actual
  tools/list and tools/call through its stdio client, not just function mocks.
- Hermes proof loads the real adapter registration against the pinned public
  provider contract, exercises initialize/end/pre-compress/switch/prefetch,
  and captures durable notes plus returned startup context. Do not claim a
  nonexistent generic pre-compaction hook.
- Handoff channel invocations:
  `uv run --extra dev --extra mcp python /Volumes/toshiba/work/mn-070-features/evidence/qa_handoff.py --scenario capture-resume`
  and the same command with `--scenario retention-hosts`.
- Label channel invocations:
  `uv run --extra dev --extra mcp python /Volumes/toshiba/work/mn-070-features/evidence/qa_labels.py --scenario write-import-init`
  and the same command with `--scenario search-topics`.
- Benchmark candidate runs the production labeling transform on only its
  disposable measurement vaults before using the frozen runner. Compare every
  stored metric slice and query rank against the baseline, asserting no worsening;
  a printed `compare.py` table alone is not an exit-code gate.
- Measure added startup context with the repository estimator,
  `ceil(UTF-8 bytes / 4)`. Report it as an estimate, alongside byte counts, on
  identical fixture inputs before/after. Do not silently call it tokenizer usage.
- Final head per PR: complete pytest, real-surface proof, clean diagnostics,
  independent non-author `chatgpt-subscription/gpt-6.1-sol` APPROVE, all required
  CI including Windows green, and `gh pr merge --match-head-commit` with the
  captured full head SHA. Evidence follows the tree, not an old review.
- Tear down all task-owned QA processes, temp vaults, worktrees and caches at
  the appropriate boundary; retain evidence and source worktrees needed for
  the requested PRs. Never delete unrelated resources.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

The owner's shared-Mac limit overrides the generic wave-width guidance: at most
two implementation workers run together. All workers use `quick` with explicit
contracts, except prose-only documentation (`writing`). The lead owns integration,
real-surface QA and merges. No team is needed: overlapping files are sequenced.

Use a fresh workflow run per phase, never one graph for the whole request:

- A foundation: record codec and journal moves in parallel; store after codec;
  a read-only verification node depends on both store and journal.
- A behavior: startup and gated retention in parallel; final verification node.
- A adapters: MCP and CLI in parallel; final verification node.
- A hosts/onboarding: Hermes and init in parallel; final verification node.
- A proof/publication: lead QA and measurements, docs, frozen-head review and CI,
  then the single A PR merge.
- B foundation: pure labels, then search-cache and journaled annotation in
  parallel; final verification node.
- B integration: note writer and init/raw import in disjoint waves, then MCP and
  Hermes adapters; every run ends in verification of all its producers.
- B proof/publication: lead actual-label benchmark and real QA, docs, exact-head
  independent review/CI and the single B PR merge.

Each producer owns its implementation and neighboring regression tests. Workers
do not commit, push, change the plan, install global packages or edit another
unit's paths. The lead verifies returns, runs diagnostics and commits each
verified unit before proceeding across a phase boundary. Workflow completion
claims are not accepted without reading the diff and checking the actual output.

### Accepted contracts

These decisions supersede conflicting advisory recommendations.

**Storage.** Use a managed `.mnemosyne-handoffs/` directory of plain Markdown.
It is readable/greppable (`rg --hidden` with its explicit path), outside ordinary
note search, mutation, onboarding and INDEX orphan detection. This avoids broad
changes to the general memory model and prevents handoff text affecting ranking.
One child directory represents exact `[project_key, task_key]`, with a short
readable label and the full SHA-256 encoded as lowercase unpadded Base32.
Project/task keys are opaque data, not paths: preserve case, Unicode and slash
spelling; reject empty/control-bearing keys; null task means project-wide and
does not equal "". Windows-shaped keys must work on every OS.

Active filenames:
`YYYYMMDDTHHMMSSffffffZ--capture|summary--<full-file-hash-base32>.md`.
Each scope has an `archive/` directory. Staging and private captures belong to
the existing `.mnemosyne-reviews/` directory. No mutable latest pointer or retry
cache. Refuse symlinked/escaping ancestors and malformed/partial owned records.

New `handoff_records.py` defines frozen `HandoffScope`, `HandoffFields`,
`HandoffNote`, `HandoffReceipt` and `HandoffError`, plus strict codec/hash helpers.
`HandoffFields` has `work`, `decisions`, `open_items`, `open_questions`,
`next_step`, `links`; work is nonblank, unknown fields remain empty, lists contain
strings. Records retain scope, kind, capture_id, recorded_at, event, session_id
and source. Render minimal normal frontmatter and a readable pretty-JSON fenced
body; choose a fence payload backticks cannot terminate. Validate all machine
fields and the full raw-byte hash encoded in the filename.

The shared low-level interface is frozen before adapter workers start:
`HandoffScope(project_key: str, task_key: str | None = None)`;
`HandoffFields(work: str, next_step: str = "", decisions: tuple[str, ...] = (),
open_items: tuple[str, ...] = (), open_questions: tuple[str, ...] = (),
links: tuple[str, ...] = ())`.
`HandoffRecord` carries scope/fields/kind/capture_id/recorded_at/event/session_id/
source/provenance, with UTC recorded_at as a fixed-width ISO string and provenance
as path/full-hex-SHA pairs. `HandoffNote` carries record/path/raw/sha256.
`HandoffReceipt` carries path/created/archived/sha256/capture_id/estimated_tokens/
warnings. Pure helpers are `scope_directory(scope)`, `encode_record(record)`,
`record_filename(record, raw)`, and `decode_record(raw, filename)`.
Decode requires canonical bytes, exact known schema and a matching full hash.

`HandoffStore(vault)` in `handoffs.py` exposes `enable`, `capture`, `records`,
`latest`, and warning reporting. Capture signature:
`capture(scope, fields, *, capture_id, event="explicit", session_id="",
source="api", now=None)`. Same scope/capture_id/request returns the original
active or archived receipt without changing bytes/mtimes; different content at
that ID conflicts. The server timestamp is excluded from request identity and
increases monotonically beyond every retained capture, even after clock rollback.
Summaries never become latest. Publish via `atomic_create_bytes` under VaultLock;
uncertain copies stay recovery errors, never silently skipped or replaced.

Explicit capture additively enables the store and an absent INDEX, preserving an
existing INDEX's routes/budget. Init offers `--enable-handoff`. Settings contain
enabled state and a 2,000-estimated-token default soft threshold, never a shared
active project/task. Cap complete record bytes at 1 MiB; warn rather than truncate
at the soft threshold and recommend retention when active history grows.

**Startup.** Add `project_key`/`task_key` to StartupReader read/verify, independent
of free-text `task`; no scope preserves existing output. Use memory_index_root
for handoffs, including when identity root differs. Under vault-before-reader
lock ordering, seed complete INDEX, latest active capture and a synthetic receipt
binding scope hash and selected path/hash (or null), then normal sources. Feed
them through existing source_blocks/cache/verify_context. Never interpret
generated handoff text as live MUST READ references. Re-select/re-read on verify;
reject foreign scope replay, missing/changed blocks and stale latest selection.
Keep 64-file, 1 MiB/source and 2 MiB/bundle hard errors. Do not substitute notices,
drop INDEX, or truncate. Append soft warnings. Bundle metadata may add
handoff_path/handoff_tokens with compatible defaults.

**Retention.** `handoff_retention.py` previews and applies deterministic folds.
Keep the newest three captures by default and always pin latest. Preview is
read-only, including no cache rebuild or lock-file creation. Build a fresh
normal-note snapshot via the existing shallow scanner and `_note_entry`, then
augment it with all validated active managed records across scopes. Preserve
type/polarity/wikilink protection semantics; use a logical handoffs zone for
managed rows. Call the unchanged `validate_clamp` with the real Mnemosyne
instance, complete snapshot, and fixed time. Only older selected-scope records
are proposed, ordered by timestamp/hash; managed records have no search dynamics,
so their existing equal default strength preserves that order. Respect the real
global cap and protections, not a reduced scope-only cap or repeated draining.

Only accepted inputs enter the new summary. Preserve all six field families,
deduplicate exact values, and retain source paths/full hashes. Date it by its
newest included source so the complete summary bytes are deterministic.
An empty accepted set writes nothing. Preview returns a plan_id binding scope,
keep, pinned latest, accepted source images and summary bytes. Apply requires
that plan_id, rereads all sources and reruns the gate under VaultLock; changed
images/accepted sets refuse the stale plan.

Stage summary exclusively; use existing Change pure moves for originals into
the scope archive and for staged summary to a new active summary, publishing
summary last. Namespaced question_id binds scope/plan identity. Repeated committed
apply is idempotent only while images agree; prepared/recovery-required needs
checked recovery; undone/rolled-back requires a fresh preview. Existing undo
restores original paths/bytes and returns summary to hidden staging.

**Journal prerequisite.** Keep the existing schema/state machine. New
`journal_moves.py` owns only forward/inverse pure-move helpers. Forward publication:
prepared manifest first; mark attempted; create target exclusively; capture source
to a private journal slot; verify captured source and target; retain private bytes.
Undo: prevalidate the whole receipt and retained captures; restore an absent
source exclusively or leave an identical source unchanged; never replace a
different arrival; capture/check target privately rather than unlinking a racing
pathname. Conflicts and partial copies become recovery-required with every image
retained. Do not rewrite existing in-place `_replace_captured` behavior. Real
before-failure evidence is `evidence/journal-races-before.json`.

**Adapters.** MCP adds `memory_handoff_capture`, `memory_handoff_read`,
`memory_handoff_fold`; startup tools gain project_key/task_key. Capture exposes
the six fields, scope and capture_id; read returns latest/count/warnings; fold
defaults to preview and apply requires plan_id. Existing memory_review_undo
handles the transaction. Per-process defaults are MNEMOSYNE_PROJECT_KEY and
MNEMOSYNE_TASK_KEY; overriding project never inherits another project's task.

CLI: `mnemosyne --vault V handoff capture|latest|resume|fold|undo`.
Capture flags are --project-key, optional --task-key, required --capture-id and
--work, optional --next-step, repeated --decision/--open-item/--open-question/--link.
--json-stdin accepts the same structured payload. Resume returns the actual
StartupReader JSON bundle. Fold uses --keep and --apply --plan-id; undo uses
--transaction. Invalid input exits 2, absent latest exits 1, success exits 0.

Hermes implements the actual provider methods, not invented generic hooks.
Resolve project from explicit project_key or agent_workspace; task_key is explicit;
session ID is checkpoint identity only. No project means no automatic capture,
and non-primary contexts never write. Enablement is opt-in. Deterministic fallback
keeps last user/assistant text verbatim and extracts only explicitly marked
decisions/open-items/questions/next-step sections; unknown fields stay empty.
Do not invent decisions or silently truncate evidence. Derive capture_id from
session, event and canonical evidence. Pre-compress returns a receipt after
durable success. Honor new scope on session switch and clear transient state;
do not clear stable scope merely because compression rotates the session ID.
Every scoped prefetch includes latest plus INDEX even for empty/unmatched query.
Document v1 host best-effort failures; advertise no unsupported v2 guarantee.

**Labels.** Dedicated inline `labels: ["namespace:value", ...]`, never tags.
Normalize/sort/deduplicate suggestions deterministically; existing labels,
including [], are user-owned until explicit replacement. Namespaces cover type,
zone, topic, project, person, entity, date, lang and imported source/format.
Infer from existing fields, typed links, exact INDEX routes, paths and bounded
lexical rules. Explicit language wins; unknown Latin language stays unknown.
No automatic provider calls. Optional provider output is supplied explicitly
through the same validated label interface, not a second inference engine.

`labels.py` owns pure inference and safe byte edits; `labeling.py` owns read-only
preview and journaled apply/replace. Label-only operations preserve every other
header key/comment, BOM/newline style and body byte. Ambiguous metadata is retained
with a warning, not reserialized. Undo checks post-images. General note writes
retain intended content/version/date behavior while preserving or explicitly
replacing labels. Init uses its existing normalization journal and reports counts.
Generated catalogues and immutable handoff artifacts are not retroactively
rewritten. Avoid imports from memory.py into the pure label module.

Search filters are AND and restrict eligible candidates before CAND/top-k.
They do not alter score inputs, IDF, document length or tie ordering. Store labels
in the index metadata and bump its cache schema through the existing rebuild
path. Expose labels in API/MCP remember/search/list/get and Hermes search.

Raw import uses existing `init --import`, accepting a single file or directory.
Each Markdown/UTF-8 text/JSON file becomes one lossless candidate; original
suffixes remain (`export.json.md`). JSON remains original bytes inside a safe
fence, not guessed record extraction. Invalid JSON stays text with a warning;
invalid UTF-8/unsafe paths are refused. Source digest is separate from converted
candidate bytes. Preview lists labels/source format with no mutations.
`mnemosyne label` previews, --apply journals, and explicit replacement uses the
same journal. `init --group-by-label <namespace>` chooses an existing matching
label for its catalogue topic, falling back to existing behavior. Grouping is
required but opt-in; default routing remains compatible.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | None | 3 | 2 |
| 2 | None | 5, 17 | 1, 3 |
| 3 | 1 | 4-9 | 2 |
| 4 | 3 | 6-10 | 5 |
| 5 | 2, 3 | 6, 7, 10 | 4 |
| 6 | 4, 5 | 10 | 7 |
| 7 | 4, 5 | 9, 10 | 6 |
| 8 | 3, 4 | 10 | 9 |
| 9 | 3, 7 | 10 | 8 |
| 10 | 6-9 | 11, 12 | None |
| 11 | 10 | 12 | None |
| 12 | 10, 11 | 13 | CI and independent review together |
| 13 | 12 | 14 | None |
| 14 | 13 | 15-19 | None |
| 15 | 14 | 16, 20, 21 | 17 |
| 16 | 14, 15 | 20, 22 | 18 |
| 17 | 2, 14 | 18, 19, 22 | 15 |
| 18 | 14, 17 | 19, 22 | 16 |
| 19 | 18 | 22 | None |
| 20 | 15, 16 | 22 | 21 |
| 21 | 15 | 22 | 20 |
| 22 | 16-21 | 23, 24 | None |
| 23 | 22 | 24 | None |
| 24 | 22, 23 | 25 | None |
| 25 | 24 | 26 | CI and independent review together |
| 26 | 25 | F1-F4 | None |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Define canonical scoped handoff record encoding
  Recommended task executor category: quick - pure types/codec with fixed contracts.
  What to do / Must NOT do: add handoff_records.py and tests/test_handoff_records.py; full hashes, exact opaque keys, six fields, safe Markdown/JSON, strict parse; no I/O or provider.
  Closes: GAP-1. Parallelization: A foundation; independent of 2, blocks 3.
  References: accepted contracts above; atomic.py:9-12; frontmatter.py; tests/test_py310_compat.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_handoff_records.py tests/test_py310_compat.py` exits 0; LSP clean.
  QA: round-trip keys `Foo`, `foo`, `C:\\Work\\Repo`, null task and task `release`; reject empty/control keys, malformed schema, hash mismatch and fence injection. Real capture/resume proof is paired in 10.
  Evidence: evidence/handoff/unit-1-tests.log. Commit: Y | feat: define scoped immutable handoff records.

- [x] 2. Fix journal pure moves and checked inverse moves
  Recommended task executor category: quick - implement the fully specified exclusive move protocol, not a new design.
  What to do / Must NOT do: edit review_journal.py, add journal_moves.py and tests/test_journal_moves.py; preserve schema/in-place behavior and retain every race image.
  Closes: GAP-3. Parallelization: A foundation with 1/3; blocks 5.
  References: review_journal.py:149-325; atomic.py:47-73,144-155; tests/test_consolidation.py; handoff/qa_journal_races.py and before JSON.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_journal_moves.py tests/test_consolidation.py tests/test_atomic.py` exits 0; LSP clean.
  QA: `PYTHONPATH=. .venv/bin/python qa_journal_races.py` must change all three real-file scenarios from unsafe to safe; inject partial exclusive copy and interrupted move, then checked recovery; no sleeps.
  Evidence: evidence/journal-races-after.json and evidence/handoff/unit-2-tests.log. Commit: Y | fix: preserve concurrent arrivals during journal moves.

- [x] 3. Implement immutable capture and archive-aware latest lookup
  Recommended task executor category: quick - one store over existing atomic/lock primitives.
  What to do / Must NOT do: add handoffs.py, exports in __init__.py and tests/test_handoffs.py; implement exact store contract, enablement and warnings; no mutable current-scope pointer.
  Closes: GAP-1. Parallelization: after 1, with 2.
  References: handoff_records.py; atomic_create_bytes; vault_lock.py; memory_index.py enable/register.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_handoffs.py tests/test_memory_index_enable.py` exits 0; same retry changes no bytes/mtimes.
  QA: real subprocess capture twice with scope `mn-070`/`handoff`, ID `checkpoint-1`; a changed request at that ID must fail; second process reads the original; two processes synchronize on an event before simultaneous capture; partial files and symlink ancestors fail closed.
  Evidence: evidence/handoff/unit-3-tests.log; paired real-surface capture evidence in 10. Commit: Y | feat: persist immutable scoped handoff captures.

- [x] 4. Include scoped handoffs in complete startup verification
  Recommended task executor category: quick - extend the existing source-set pipeline.
  What to do / Must NOT do: edit startup.py and add tests/test_handoff_startup.py; explicit scope receipt, INDEX-first/latest-next, fresh selection and warnings; never drop/truncate.
  Closes: GAP-2. Parallelization: A behavior with 5.
  References: startup.py:214-343; startup_coverage.py; tests/test_startup.py and test_task_memory.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_handoff_startup.py tests/test_startup.py tests/test_task_memory.py` exits 0.
  QA: empty/unmatched task still includes latest; foreign-scope and stale-latest verification fail; different identity/vault roots work; oversized complete bundles raise; no-scope output remains compatible.
  Evidence: evidence/handoff/unit-4-tests.log and 10. Commit: Y | feat: verify scoped handoffs alongside startup INDEX.

- [x] 5. Add curation-gated retention preview apply and undo
  Recommended task executor category: quick - implement the accepted gate/staging/journal contract.
  What to do / Must NOT do: add handoff_retention.py and tests/test_handoff_retention.py; full fresh snapshot, true validate_clamp, plan_id, summary-last pure moves; no gate bypass or repeated cap draining.
  Closes: GAP-3. Parallelization: A behavior with 4.
  References: curation_gate.py:21-107; curation_contract.py; review_journal.py; mnemosyne.py:370-410,708-744,879-901.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_handoff_retention.py tests/test_handoff_retention_journal.py tests/test_handoff_retention_edges.py tests/test_curation.py tests/test_consolidation.py` exits 0.
  QA: preview preserves every byte/mtime and creates no sidecar; fold more than cap, preserve protected/linked records and latest; changed preview inputs refuse; undo restores all original paths/bytes and retains summary in staging; archived capture retry returns original.
  Evidence: evidence/handoff/unit-5-tests.log and retention-hosts.json. Commit: Y | feat: fold handoff history through curation and undo.

- [x] 6. Expose handoff capture read fold and scoped startup over MCP
  Recommended task executor category: quick - follow the existing MCP 2.2 MCPServer tool patterns.
  What to do / Must NOT do: edit _mcp_app.py, add tests/test_mcp_handoffs.py, update stale tool-list assertions in test_mcp_server.py; no lifecycle fiction.
  Closes: GAP-1, GAP-2. Parallelization: A adapters with 7.
  References: _mcp_app.py memory_startup_read/verify and memory_review_undo; tests/test_mcp_memory_index.py; accepted names/fields above.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_mcp_handoffs.py tests/test_mcp_server.py tests/test_mcp_memory_index.py` exits 0.
  QA: actual stdio tools/list schema includes all six fields/scope/capture_id and correct annotations; tools/call capture/read/startup/fold/undo works; project override does not inherit foreign task; malformed data returns an MCP error without writes.
  Evidence: evidence/handoff/unit-6-tests.log and mcp-transcript.json from 10. Commit: Y | feat: expose scoped handoff tools over MCP.

- [x] 7. Add handoff CLI capture resume retention and recovery
  Recommended task executor category: quick - argparse dispatch with fixed commands.
  What to do / Must NOT do: edit memory_index_cli.py, add a focused handoff_cli.py only if needed for size, add tests/test_handoff_cli.py; preserve init/check/split syntax.
  Closes: GAP-1, GAP-2, GAP-3. Parallelization: A adapters with 6.
  References: memory_index_cli.py:35-126; tests/test_memory_index_cli.py; accepted CLI contract.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_handoff_cli.py tests/test_memory_index_cli.py tests/test_onboarding_cli.py` exits 0.
  QA: real separate CLI processes capture JSON/stdin and resume with INDEX; missing latest exits 1; malformed/duplicate incompatible options exit 2 and create nothing; fold requires its preview plan_id.
  Evidence: evidence/handoff/unit-7-tests.log and capture-resume transcript. Commit: Y | feat: add handoff capture and resume CLI.

- [x] 8. Implement real Hermes lifecycle capture and mandatory scoped prefetch
  Recommended task executor category: quick - fixed public provider callbacks and thin store calls.
  What to do / Must NOT do: edit integrations/hermes/provider.py and tests/test_host_adapters.py; add a focused helper only for transcript parsing if needed; no invented generic hooks or delivered-once suppression.
  Closes: GAP-4. Parallelization: A hosts/onboarding with 9.
  References: integrations/hermes/__init__.py; pinned hermes-contract/agent/memory_provider.py; accepted lifecycle contract; upstream memory_manager.py:742-843.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_host_adapters.py` exits 0; callback retry produces one record and non-primary/off/unbound cases do not write.
  QA: instantiate the registered MnemosyneProvider against the real pinned base; initialize, pre-compress twice, session-end, switch and prefetch on empty/unmatched text; a new instance resumes only its scope. Capture receipts and full context outside pytest in 10.
  Evidence: evidence/handoff/unit-8-tests.log and hermes-transcript.json. Commit: Y | feat: capture handoffs at Hermes session boundaries.

- [x] 9. Offer handoff enablement in reversible init onboarding
  Recommended task executor category: quick - add one explicit option to the existing preview/apply flow.
  What to do / Must NOT do: edit onboarding_plan.py, onboarding.py, memory_index_cli.py and tests/test_onboarding_handoffs.py; --enable-handoff and report state; no automatic context scope shared in the vault.
  Closes: GAP-4. Parallelization: A hosts/onboarding with 8.
  References: onboarding.py:66-127; onboarding_plan.py; tests/test_onboarding.py and test_onboarding_safety.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_onboarding_handoffs.py tests/test_onboarding.py tests/test_onboarding_safety.py tests/test_onboarding_cli.py` exits 0.
  QA: preview creates neither directories nor changes; explicit apply enables and verifies INDEX; repeated apply is byte/mtime stable; existing notes/routes remain untouched by enablement.
  Evidence: evidence/handoff/unit-9-tests.log and retention-hosts.json. Commit: Y | feat: offer handoff memory during vault initialization.

- [x] 10. Run handoff real-surface scenarios and measure startup cost
  Recommended task executor category: quick - lead-executed QA with fixed acceptance, not delegated approval.
  What to do / Must NOT do: implement evidence/qa_handoff.py as a real subprocess/MCP/provider driver, then run both registered scenarios; no mocks replacing storage/coverage/gate.
  Closes: GAP-8, GAP-9. Parallelization: after 6-9.
  References: loop G001 criteria, actual shipped adapters and baseline evidence.
  Acceptance criteria: both registered `uv run ... qa_handoff.py --scenario capture-resume|retention-hosts` commands exit 0 and emit complete assertions plus cleanup.
  QA: normal capture/fresh resume; project/task/Windows isolation; idempotent compaction; oversized warning and hard-error boundaries; gated fold+undo+edited-postimage refusal; real schema; compare identical before/after full startup bundles and record bytes/estimated tokens.
  Evidence: evidence/handoff/{capture-resume,retention-hosts,startup-cost,mcp-transcript,hermes-transcript}.json. Commit: N, external evidence; no product stub.

- [x] 11. Document handoff usage and 0.7.0 release entry
  Recommended task executor category: writing - bilingual product documentation only.
  What to do / Must NOT do: update README.md, README.ko.md, integrations/hermes/README.md and CHANGELOG.md under 0.7.0; include CLI/MCP/API examples, omo/Claude Code convention, enablement, failure/undo behavior and measured estimate.
  Closes: GAP-9. Parallelization: after 10.
  References: implemented public signatures, pinned Hermes contract and measured cost JSON.
  Acceptance criteria: execute every new command/tool example on task-owned fixtures; `pytest -q tests/test_readme_links.py tests/test_version_alignment.py` exits 0.
  QA: examples succeed without API keys; wrong-scope/oversized/conflicting cases are honestly documented; no false automatic MCP lifecycle claim. Prose is reviewed, not pinned by new tests.
  Evidence: evidence/handoff/docs-qa.md. Commit: Y | docs: explain scoped handoffs for 0.7.0.

- [x] 12. Freeze handoff head and obtain independent approval and CI
  Recommended task executor category: quick - lead git/CI orchestration; reviewer uses the explicit Sol model.
  What to do / Must NOT do: full suite and diagnostics, freeze/push head, create one A PR, launch separate non-author GPT-6.1 Sol reviewer and monitor all 21 checks; no release workflow.
  Closes: GAP-9. Parallelization: independent review and CI together.
  References: owner exact-head gate, git history, evidence/handoff/.
  Acceptance criteria: `uv run --extra dev --extra mcp --extra semantic pytest -q` exits 0; reviewer receipt says APPROVE for full head; `gh pr checks <A-PR> --watch` ends with all required checks green including Windows.
  QA: re-fetch head after review/checks; any changed tree invalidates affected evidence and any changed head requires exact-head approval. Save full head/tree and reviewer provider/model.
  Evidence: evidence/handoff/{tests,ci,review,head}. Commit: only verified fixes, each rechecked; final footer names this plan.

- [x] 13. Merge the reviewed handoff PR by exact head
  Recommended task executor category: quick - authorized protected merge.
  What to do / Must NOT do: lead runs `gh pr merge <A-PR> --squash --match-head-commit <reviewed-head>` after fresh gate checks; no tag/publish.
  Closes: GAP-9. Parallelization: after 12 only.
  Acceptance criteria: `gh pr view <A-PR> --json state,headRefOid,mergeCommit,url` reports MERGED and headRefOid equals the approved head.
  QA: a stale head must not be substituted; record the resulting merge commit separately from PR head. Refresh main for B.
  Evidence: evidence/handoff/merge.json. Commit: GitHub merge only.

- [x] 14. Implement pure deterministic labels and safe field edits
  Recommended task executor category: quick - pure inference and byte-span edits.
  What to do / Must NOT do: add labels.py and tests/test_labels.py; dedicated namespaces, existing-fields/path/INDEX/lexical inference, manual ownership and safe byte-preserving labels field; no tags/ranking changes.
  Closes: GAP-5. Parallelization: B foundation after 13.
  References: frontmatter.py; onboarding_notes.py:87-161; accepted label contract.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_labels.py tests/test_onboarding_notes.py` exits 0.
  QA: all requested families and mixed-language inputs; identical input gives identical suggestions; manual empty labels retained; BOM/CRLF/comments/body preserved; malformed/ambiguous headers unchanged with warnings.
  Evidence: evidence/labeling/unit-14-tests.log. Commit: Y | feat: infer editable memory label suggestions.

- [x] 15. Filter indexed search by labels without changing ranking
  Recommended task executor category: quick - add metadata and pre-cut eligibility to current search.
  What to do / Must NOT do: edit mnemosyne.py and add tests/test_label_search.py; cache schema upgrade, AND filters before candidate cut, no score/term/doclen/tie changes.
  Closes: GAP-7, GAP-8. Parallelization: B foundation with 17.
  References: mnemosyne.py:_note_entry/_decode_index/search; tests/test_index_format.py and test_mnemosyne.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_label_search.py tests/test_index_format.py tests/test_mnemosyne.py` exits 0.
  QA: matching note outside unfiltered top 32 is returned; unfiltered score/rank sequences remain equal; old cache rebuilds; malformed filters refuse rather than silently broaden.
  Evidence: evidence/labeling/unit-15-tests.log and frozen comparison in 23. Commit: Y | feat: filter memory search by labels.

- [x] 16. Attach and preserve labels on normal note writes
  Recommended task executor category: quick - integrate pure inference at the existing write seam.
  What to do / Must NOT do: edit memory.py and tests/test_note_labels.py; absent labels infer, existing labels preserve, explicit labels replace; forward search labels and expose read/list metadata.
  Closes: GAP-5. Parallelization: B integration with 18.
  References: memory.py:207-347, _compose_frontmatter; tests/test_memory.py; labels.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_note_labels.py tests/test_memory.py tests/test_memory_os.py` exits 0.
  QA: create/append/replace retain tags and editable labels; explicit [] stays empty; note version/evidence/source/TTL contracts remain unchanged; no provider/network call.
  Evidence: evidence/labeling/unit-16-tests.log. Commit: Y | feat: preserve label suggestions on note writes.

- [x] 17. Journal label annotation and explicit replacement
  Recommended task executor category: quick - existing Change before/after transaction pattern.
  What to do / Must NOT do: add labeling.py and tests/test_label_journal.py; preview no-write, apply/replace checked images and label counts; no body or other-header rewrites.
  Closes: GAP-5. Parallelization: B foundation with 15.
  References: review_journal.py, onboarding_notes.complete_header, tests/test_consolidation.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_label_journal.py tests/test_consolidation.py` exits 0.
  QA: label -> undo restores exact bytes; changed post-image refuses without partial restore; user-owned labels untouched unless explicit replacement; preview leaves bytes/mtimes/cache state unchanged.
  Evidence: evidence/labeling/unit-17-tests.log and write-import-init.json. Commit: Y | feat: journal reversible label annotation.

- [x] 18. Integrate init label counts grouping and label CLI
  Recommended task executor category: quick - extend current onboarding and argparse patterns.
  What to do / Must NOT do: edit onboarding_notes.py, onboarding_plan.py, onboarding.py, memory_index_cli.py and tests/test_onboarding_labels.py; infer on touched notes, journal with existing normalization, report counts, add label preview/apply and --group-by-label.
  Closes: GAP-5, GAP-7. Parallelization: with 16; do not edit memory.py or mnemosyne.py.
  References: onboarding.py/plan/notes, existing init CLI tests, accepted opt-in grouping contract.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_onboarding_labels.py tests/test_onboarding.py tests/test_onboarding_cli.py` exits 0.
  QA: default grouping unchanged; explicit label grouping picks matching values/fallback; init rerun changes no bytes; generated catalogues and immutable handoffs are not rewritten; counts match actual labels.
  Evidence: evidence/labeling/unit-18-tests.log. Commit: Y | feat: label and group notes during onboarding.

- [x] 19. Convert raw file imports into labeled preview candidates
  Recommended task executor category: quick - deterministic lossless conversion and existing import publication.
  What to do / Must NOT do: add import_candidates.py if needed, edit onboarding_plan.py/onboarding.py/CLI and tests/test_raw_imports.py; files/directories, MD/text/JSON, separate source digest, safe original suffixes and source labels.
  Closes: GAP-6. Parallelization: after 18, no overlapping onboarding writer.
  References: onboarding import plans and atomic publication; tests/test_onboarding.py/test_onboarding_safety.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_raw_imports.py tests/test_onboarding.py tests/test_onboarding_safety.py` exits 0.
  QA: three formats preview without files/mtime changes; apply retains source bytes and is idempotent; JSON backticks cannot escape its fence; invalid JSON warns/preserves text; changed source/unsafe path/invalid encoding refuses safely.
  Evidence: evidence/labeling/unit-19-tests.log and write-import-init.json. Commit: Y | feat: preview labeled text and JSON imports.

- [ ] 20. Expose labels through actual MCP tools
  Recommended task executor category: quick - schema and argument propagation following current tools.
  What to do / Must NOT do: edit _mcp_app.py and tests/test_mcp_labels.py, update stale existing tool assertions only as needed; labels on remember/search/list/get and a read-only label-count surface.
  Closes: GAP-7. Parallelization: B adapters with 21.
  References: existing MCP parameter/annotation patterns and real stdio client tests.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_mcp_labels.py tests/test_mcp_server.py` exits 0.
  QA: tools/list types/limits, tools/call create/read/filter, AND semantics, malformed filters cannot broaden results, explicit manual labels survive updates.
  Evidence: evidence/labeling/unit-20-tests.log and mcp-transcript.json. Commit: Y | feat: expose memory labels over MCP.

- [ ] 21. Forward label filters through Hermes search
  Recommended task executor category: quick - one adapter argument/schema change.
  What to do / Must NOT do: edit integrations/hermes/provider.py and tests/test_host_labels.py; preserve handoff callback/prefetch behavior.
  Closes: GAP-7. Parallelization: B adapters with 20.
  References: provider._search/get_tool_schemas and tests/test_host_adapters.py.
  Acceptance criteria: `.venv/bin/python -m pytest -q tests/test_host_labels.py tests/test_host_adapters.py` exits 0.
  QA: actual registered provider filters labels correctly; invalid input errors; no-scope and handoff startup contracts remain intact.
  Evidence: evidence/labeling/unit-21-tests.log and search-topics.json. Commit: Y | feat: filter Hermes recall by note labels.

- [ ] 22. Run labeling real-surface scenarios and startup measurements
  Recommended task executor category: quick - lead executes fixed public-surface proof.
  What to do / Must NOT do: implement evidence/qa_labels.py using real CLI/API/MCP/provider processes; run both registered scenarios with no credentials.
  Closes: GAP-5-9. Parallelization: after 16-21.
  Acceptance criteria: both `uv run ... qa_labels.py --scenario write-import-init|search-topics` commands exit 0; artifact assertions and cleanup receipts exist.
  QA: all label families, three source formats, dry-run/apply/undo/manual-edit conflict; filter before candidate cut; label grouping/counts; original tags/other bytes retained; exact full-bundle startup token delta and A handoff regression.
  Evidence: evidence/labeling/{write-import-init,search-topics,startup-cost,mcp-transcript}.json. Commit: N, external evidence.

- [ ] 23. Prove zero frozen retrieval ranking regression after real labeling
  Recommended task executor category: quick - lead drives the unchanged frozen runner and strict comparison.
  What to do / Must NOT do: add an evidence-only runner that invokes production labeling on generated vaults before frozen evaluation; preserve corpus/query/expansion bytes and all four engines/sizes.
  Closes: GAP-8. Parallelization: after 22.
  References: benchmarks/retrieval/bench_retrieval.py:210-343, compare.py; evidence/retrieval-before.json.
  Acceptance criteria: candidate JSON has 12 rows and 1,440 ranks each; every rank array and every stored metric slice equals the same-environment baseline; fixture SHA-256s unchanged; comparison exits 0.
  QA: `uv run --extra dev --extra mcp --extra semantic python /Volumes/toshiba/work/mn-070-features/evidence/qa_label_benchmark.py` labels real measurement files, runs bm25/hybrid/expanded-claude/expanded-gpt at 160/1000/10000 and fails on any changed rank/metric/fixture.
  Evidence: evidence/labeling/{retrieval-after,ranking-comparison,fixture-hashes}.json and benchmark transcript; record labeling duration. Commit: N, external evidence; no fixture edits.

- [ ] 24. Document labels imports filtering and measured 0.7.0 results
  Recommended task executor category: writing - bilingual product documentation.
  What to do / Must NOT do: README.md, README.ko.md, integrations/hermes/README.md, CHANGELOG.md under 0.7.0; ownership, undo, import formats, grouping, filter semantics, measured ranking/tokens.
  Closes: GAP-9. Parallelization: after 22, 23.
  Acceptance criteria: execute every new example; `pytest -q tests/test_readme_links.py tests/test_version_alignment.py` exits 0; no unsupported quality claim.
  QA: no-credential examples work, fallback/ambiguous metadata/import warnings are documented, Korean product prose is Korean; no tests pin prose.
  Evidence: evidence/labeling/docs-qa.md. Commit: Y | docs: explain deterministic labels for 0.7.0.

- [ ] 25. Freeze labeling head and obtain exact-head Sol approval and CI
  Recommended task executor category: quick - lead orchestration with an independent explicit-model reviewer.
  What to do / Must NOT do: full local suite/diagnostics and current real-surface evidence; create the B PR, freeze/push, run non-author GPT-6.1 Sol review and monitor Windows-inclusive CI.
  Closes: GAP-9. Parallelization: review and CI together.
  Acceptance criteria: full `uv run --extra dev --extra mcp --extra semantic pytest -q` exits 0, all 21 required checks green and APPROVE names the exact head.
  QA: refresh head/check states; any changed head restarts approval, changed behavior/tree invalidates affected proof; record all source URLs and receipts.
  Evidence: evidence/labeling/{tests,ci,review,head}. Commit: verified fixes only; final footer names this plan.

- [ ] 26. Merge labeling PR and verify both requested outcomes
  Recommended task executor category: quick - lead authorized protected merge.
  What to do / Must NOT do: `gh pr merge <B-PR> --squash --match-head-commit <reviewed-head>` after fresh gates; record both merged PRs; no tag/release/PyPI.
  Closes: GAP-9. Parallelization: after 25.
  Acceptance criteria: `gh pr view <B-PR> --json state,headRefOid,mergeCommit,url` returns MERGED with approved head; all six loop criteria have honest evidence.
  QA: read both merge receipts and the resulting main state; reconcile exact requested behavior against every ideal-state row before declaring complete.
  Evidence: evidence/labeling/merge.json and evidence/final-audit.md. Commit: GitHub merge only.

## Final verification wave
> Owner has already authorized execution and protected merges. No second approval
> interview. The lead performs real QA and scope/fidelity audits; one independent
> exact-head Sol reviewer per PR performs the required review, not a reviewer panel.
- [ ] F1. Plan compliance audit
  Owner: lead. Verify all 26 rows and every original requirement against actual
  artifacts, not task self-reports. Record any unmet criterion as open, not PASS.
- [ ] F2. Code quality review
  Owner: the two distinct exact-head Sol review receipts from 12/25, integrated
  by the lead. No additional reviewer panel. Refuse stale, missing or conditional approval.
- [ ] F3. Real manual QA
  Owner: lead. Inspect the 10/22/23 captures and teardown every task-owned QA
  process/temp path/cache/upstream checkout; cancel the 25-minute reminder.
  Keep source/evidence and merged history needed for the requested handoff.
- [ ] F4. Ideal-state fidelity
  Owner: lead. Map every IS row to actual captured behavior and emit the exact
  final status format plus authorized Korean Discord report. Include both PR
  URLs, estimated session-memory tokens, labeling rank delta and honest open items.

## Commit strategy

Observe repository history before each commit:
`git log --oneline -20` and `git log -5 -- <unit paths>`. Current convention uses
English subjects such as `feat: ...`, `fix: ...`, `docs: ...` and `chore: ...`.
Commit each verified increment, staging only that unit's files. No WIP commits,
amend, force-push or history rewrite. Keep the plan and its evidence references
reviewable; final feature commit footer:
`Plan: .omo/plans/mn-070-features.md`.

Feature A branch/worktree: `mn-070-handoff` at
`/Volumes/toshiba/work/mn-070-features/handoff`. Baseline clone remains `repo/`.
Feature B branches from the refreshed merged main in a new task-owned worktree.
Create one PR per item. Refresh PR head/check state before every gated action,
freeze the reviewed head, and merge only with `--match-head-commit <that SHA>`.
Record PR URLs, head/tree SHAs, review receipt, CI checks and merge result under
the corresponding evidence directory. Do not invoke release automation.

## Success criteria
> One row per IS row. The plan is complete only when every IS row has a delivering todo and a proving QA scenario; F4 checks the delivered behavior against these rows 1:1, and a shortfall becomes new `- [ ] N.` rows, never a note.
| IS | Delivering todo(s) | Proving QA scenario | Evidence |
| --- | --- | --- | --- |
| IS-1 | 1,3,6-8,10 | Capture/resume + real callback/schema proof | evidence/handoff/capture-resume.json, hermes-transcript.json, mcp-transcript.json |
| IS-2 | 4,6-8,10 | Fresh-process StartupReader/CLI/MCP/provider, cross-scope mutation/overflow rejection | evidence/handoff/capture-resume.json, retention-hosts.json |
| IS-3 | 2,5,10 | Real race reproducer green, true cap/protection, fold+undo and edited-image refusal | evidence/journal-races-after.json, evidence/handoff/retention-hosts.json |
| IS-4 | 9,10 | No-write init preview, explicit enable, idempotent apply | evidence/handoff/retention-hosts.json |
| IS-5 | 14,16-18,22 | Deterministic suggestions, user tags/labels retained, exact label-only undo | evidence/labeling/write-import-init.json |
| IS-6 | 19,22 | Actual MD/text/JSON dry-run/apply, lossless source and stale-plan guard | evidence/labeling/write-import-init.json |
| IS-7 | 15,18,20-22 | Pre-cut AND filtering, real MCP/provider, opt-in grouping/counts | evidence/labeling/search-topics.json |
| IS-8 | 10,22,23 | Full-bundle estimated-token deltas and zero rank/metric changes for all frozen rows | evidence/handoff/startup-cost.json, evidence/labeling/startup-cost.json, ranking-comparison.json |
| IS-9 | 11-13,24-26,F1-F4 | Executed docs examples, green Windows CI, non-author exact-head APPROVE and protected merges | evidence/handoff/ and evidence/labeling/ review/ci/merge receipts; evidence/final-audit.md |
