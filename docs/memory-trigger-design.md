# Task-bound memory reads and lossless topic indexes

Status: design recorded before implementation, 2026-10-10.
Base: version 0.6.0, `259d949`.

## Goal and limits

Deliver matching memory documents before a managed task proceeds, rather than
depending on an agent noticing an index line. Keep the resident index small
without deleting any route. The implementation remains standard-library-only
and supports Python 3.10 and later.

The guarantee is mechanical: given a task, return every route selected by the
published lexical rule and every selected document in full, or fail the
complete read. It is not a semantic classifier or a way to control an external
agent that ignores its host's startup contract.

Keep `MemoryIndex.open(query, limit=3)` unchanged. Its exact/lexical ranking,
search fallback, limits, and frozen accuracy evaluation remain a separate,
explicit retrieval interface.

## Observed baseline

The unchanged release passes 1,012 local tests with the MCP and semantic
extras installed. The frozen GPT and Claude identity sets each score 12/12.
The existing synthetic sample's already-indexed complete startup costs
1,781 `o200k_base` tokens; its 30-entry index alone costs 630. The historical
45,128-token full-document startup is not this change's comparison baseline.

A frozen fictional corpus contains 16 tasks, 12 documents, and 13 mappings.
Route-only startup delivers none of the required bodies for its 12 positive
tasks. Existing explicit `open` passes 12/16 tasks: three tasks require more
than its three-document cap, and one unrelated task matches function words.

A separate private corpus is evaluated outside the repository. Only numeric
and anonymized results may be published; its source, task text, document
names, and detailed responses must never enter this repository. Its fixture
is frozen before implementation and is deleted with its source at completion.

## Task matching

Add `MemoryIndex.match(task: str) -> tuple[IndexEntry, ...]`. It selects
original entries in stored order without reading bodies, ranking, top-k,
document-content search, or search fallback.

An empty or whitespace-only supplied task is invalid. An absent optional
index gives no matches; enabled-but-invalid or required-but-missing state
still fails loudly.

Normalize with the existing Unicode tokenizer, but discard its synthetic
five-character prefix stems. This retains NFKC, casefold, accent folding,
Hangul runs/bigrams, and Han/kana character tokens without allowing arbitrary
English shared prefixes to become task matches.

Remove this fixed set of ordinary function words from both sides:

```text
a an the and or as at by for from in into of on onto to with
about after before between during through under over
when while if then than that this these those
what how why where which who whom whose
i me my we our you your he his she her it its they their
is am are was were be been being
do does did have has had
can could may might must shall should will would
```

For ASCII alphabetic words, retain the original and add these nonrecursive
variants when the result has at least four letters: `ies`/`ied` to `y`;
remove `ing` or `ed`, optionally removing a doubled final consonant from
`b d g l m n p r t`; remove final `s` except endings `ss`, `us`, and `is`.
Do not restore silent `e` or infer arbitrary synonyms.

Task-side `lexical-v2` expansion supports these bounded technical equivalents:

```text
web / browser / website / site / webpage
login / log in / sign in / authentication
repository / repo / codebase
rollback / backout / back out / revert
```

A whole-word contiguous phrase in the normalized original task activates its
group once. The existing search-time `synonyms` expansion validator/tokenizer
adds the equivalents; discard synthetic prefix stems and apply the same suffix
and function-word rules. Literal task terms remain. Stored triggers are not
rewritten, and expansion is not recursive. There is no model call, dependency,
body search, ranking or document limit in this rule. Search expansion weights
do not suppress a selected route: every resulting lexical match is returned.

Select an entry if its complete normalized trigger equals the complete task,
or if at least one remaining non-function-word token variant intersects. Evaluate every
entry; an exact match must not suppress other applicable aliases. A trigger
containing only function words requires whole-trigger equality.

For `lexical-v2`, count term presence across distinct original trigger strings,
not across their document targets. Exclude a generic-action term from trigger
selection when it appears in at least two distinct triggers. The fixed action
vocabulary, expanded with the same suffix rules above, is:

```text
check checking work working do doing write writing open opening
update updating answer answering report reporting launch launching
resume resuming choose choosing pick picking use using handle handling
post posting send sending format formatting decide deciding
monitor monitoring touch touching deal dealing automate automating
```

If exclusion leaves no content terms, retain the original trigger terms.
Unique action terms and explicit action-only aliases therefore remain usable.
This operates on registered conditions, not inferred parts of speech: a noun
such as "shopping" is not removed merely because it ends in `ing`.
Adding a distinct condition can change action-only selection; duplicating its
document targets cannot. Register an explicit short alias when a generic action
alone should select a document.

The remaining ANY rule is recall-oriented. Natural trigger sentences often list
alternatives; requiring every word would incorrectly turn their alternatives
into a conjunction. Shared words can still overmatch. Report extra
documents as well as misses, and do not claim semantic precision. Matching
does not interpret negated intent or guarantee paraphrases outside the declared
equivalence vocabulary. Register explicit aliases for other terminology.

Author triggers with distinctive subjects, tool names, operations, or
identifiers. Prefer short explicit aliases to vague phrases such as "when
needed". Preserve all aliases; never rewrite existing conditions from private
evaluation answers.

## One verified full-read path

Extend the existing API:

```python
StartupReader.read(paths, *, task: str | None = None) -> StartupBundle
StartupReader.verify(context, paths, *, task: str | None = None) -> Coverage
```

Append `matched_entries: tuple[IndexEntry, ...] = ()` to `StartupBundle`.
`task=None` keeps the current startup behavior. An explicit task does not make
empty paths valid when no index is enabled.

Assemble sources from one validated index snapshot:

1. The complete resident index.
2. A task receipt, when a task is supplied.
3. Existing caller paths and their literal `MUST READ` closure.
4. Complete topic indexes for matched routes when grouping is active.
5. Every distinct matched document body, without a document-count cutoff.

The task receipt is a synthetic source at `.mnemosyne-memory-index/task`.
It contains version 1, matcher `lexical-v2`, SHA-256 of the exact task,
the canonical index digest, and every selected `[trigger, document]` pair.
It binds caching and verification to the task as well as current routing.

Caller files resolve under the identity root. Matched documents resolve under
the index's vault root using `document_path()`. With different roots, their
source labels are `.mnemosyne-memory-index/documents/<relative-path>`;
with equal roots they retain ordinary relative labels. Deduplicate by
configured root and canonical relative path, never by identical contents.
Caller-supplied paths cannot claim these reserved synthetic labels.

Task memories are terminal data sources: their text does not create new
filesystem reads. Existing `MUST READ` expansion applies to caller startup
files and their closure. A file present in both roles is returned once when
roots are equal, and its explicitly requested startup declarations still run.

Reuse the existing coverage format. `verify` independently reconstructs
sources from fresh authoritative state and bytes, rejecting another task,
changed documents, missing selected bodies, altered receipts, or tampering
even when the caller recomputes block certificates.

Keep the complete-read safety bounds: 64 source records, 1 MiB per source,
2 MiB total. Include synthetic sources in those bounds. Missing targets,
invalid UTF-8, unsafe paths, corrupt state, and exceeded bounds fail the whole
operation. Never truncate or return a successful partial read. Fresh reads
are not an atomic snapshot across unrelated external filesystem writes.

## Host boundaries

Extend MCP's existing `memory_startup_read(paths, task=None)` and
`memory_startup_verify(paths, context, task=None)` tools. The read response
also exposes `matched_entries`. The MCP initialization/discovery refresh
cannot know the next task; hosts must pass that task at their managed boundary.

Hermes `prefetch(query)` is an existing task-query boundary. With an enabled
index, call the task-aware startup reader without slicing the task. Return the
complete verified context when routes match, an empty string for no match,
and propagate read failures. Do not fall back to snippets for an indexed
automatic read. With no index, preserve existing optional search behavior.
`system_prompt_block()` independently retains the resident index, including
after empty prefetch and context rebuilding.

## Derived two-level index

Keep v1 `index.json` as the sole routing authority. Reads must create no
second cache, generated files, migration, or mutable topic state.

Derive a topic from the document's full parent directory:
`dir:<parent-directory>`. Root-level documents use
`file:<canonical-document-path>`. These identifiers are opaque API selectors,
not filesystem paths. Every original route belongs to exactly one topic.

Extend `MemoryIndex.read(*, topic: str | None = None)`. The default view's
`entries` always contains every original entry. A topic view contains every
entry in that topic. Unknown topics fail rather than falling back.
Append defaulted `mode`, `index_sha256`, `topic`, and `topics` metadata.
Each topic summary contains its identifier, route count, distinct-document
count, and digest.

The resident grouped representation lists every topic, with counts and
digests. The complete second-level view retains every original trigger and
document. A task-aware read loads each matching topic view once before its
document bodies. Explicit expansion is available as MCP
`memory_index_read(topic=None)` and Hermes `birkin_memory_index(topic=None)`.

Construct flat and grouped candidates including their instructions and
warnings. Grouping is eligible only when a topic has multiple distinct
documents; use it only if its final runtime-estimated token count is strictly
smaller. Flat wins ties. Do not pick an entry threshold merely to bypass tests.

For overlapping routes to the same document, display that document once with
an unambiguous JSON-escaped alias array only when shorter. Preserve every
original alias and stored entry. The same trigger pointing to several
documents retains all targets. Similar wording never authorizes semantic
merging or removal.

## Retention, revisions, and warnings

Canonical digests use UTF-8 JSON, `ensure_ascii=False`, compact separators,
and route pairs sorted by their original `(trigger, document)` values.
The index digest covers version 1, `max_tokens`, and all route pairs; a topic
digest covers all its pairs. A synthetic topic source is labeled
`.mnemosyne-memory-index/topic/<SHA-256-of-topic-identifier>`.

The disjoint union of complete topic routes must equal the authoritative
route set. Every topic appears once; counts and digests derive from that
same state. Grouping never selects a top-k subset. Verification regenerates
the representation from current state, not from caller-provided commitments.

The never-droppable invariant now has two compatible representations: a flat
resident list, or a complete resident topic map with all routes available in
its complete second-level views. It does not claim that unmatched leaf text
is resident. Additive registration and all existing lifecycle exclusions
remain unchanged. A valid external rewrite cannot be identified as
historically unauthorized without independent history.

`max_tokens` remains a warning, never an eviction limit. Determine excess
before appending the warning once, then report the final emitted size.
`capacity_report().always_loaded` measures the selected resident context;
entry counts still cover all original routes. Tiny budgets and zero ordinary
note limits cannot hide any topic.

## Frozen evaluation and real-surface proof

Use the immutable fictional fixture and its frozen grown shape: 12 topics,
20 documents per topic, and two aliases per document (480 routes). Only the
task enters routing; expected paths are used afterwards to score returned
complete bodies. Report positives, negatives, every miss, and extra documents.
Run the private fixture unchanged outside the repository and publish only
anonymous numeric summaries.

Measure resident index, whole `StartupReader.context`, topic expansions,
task responses, and actual Hermes prompt/prefetch strings independently.
Count repeated material when it is actually transmitted. Use benchmark-only
`o200k_base`, characters, UTF-8 bytes, and the declared bytes/4 runtime estimate.
These are comparison units, not provider billing measurements.

Commands from a committed product tree:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m benchmarks.memory_index.run --output /home/hp/work/mn-trigger/evidence/index-after.json
.venv/bin/python -m benchmarks.memory_triggers.run --output /home/hp/work/mn-trigger/evidence/triggers-after.json
```

Keep the existing frozen author fixtures, scorer, protocol, and legacy
`open(query, limit=3)` evaluation unchanged. Require 12/12 for each author
with no per-question regressions.

Exercise real MCP stdio with `memory_startup_read` using
`{"paths":[],"task":"Review the deployment rollback plan."}`. All four
fictional required bodies must appear; verifying with the same task succeeds,
and a changed task or omitted body fails. Exercise an unrelated task, separate
identity/vault roots, a task whose match occurs after character 500, restart,
same-length external changes, missing targets, and tiny budgets.

Run the real Hermes provider through initialize, system prompt, prefetch,
topic expansion, shutdown, and reinitialize. Capture inputs, outputs and
process cleanup. This proves the shipped provider surface, not discovery in
an independently installed external host.

## Delivery

PR 1 adds matching, verified task reads, receipts, host integration and its
tests/measurements; rendering stays flat. PR 2 adds derived topic views, safe
alias compaction, grouping, expansion and accounting. Each uses the existing
neighboring test homes plus a focused fixture runner.

One implementer owns the shared core and host contract. A disjoint benchmark
implementation may run alongside it after APIs are fixed; the lead runs the
real-surface proof. For each final head, run all CI, including non-gating
checks, and obtain separate GPT-6.1 Sol approval of that exact SHA. Refresh
state and merge with `--match-head-commit`. A changed head requires new
approval and checks. No release, tag, version bump, or publication.
