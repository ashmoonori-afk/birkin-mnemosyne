# Always-loaded memory INDEX

Status: design recorded before implementation, 2026-10-09.
Base: v0.5.0, `7ebaee7a997eaa8e62276b8c07f47faaf2ca7fbd`.

## Users and intended result

An agent currently rereads an expanding personal-memory note, a manual, and a
handoff before knowing which details its task needs. The motivating example
costs roughly 10K + 8K + 21K tokens at startup. An integrator can instead keep
an explicit map of **when to read -> which document**, then open only the
matching documents. A vault owner can inspect that map and account for every
line moved out of the old startup material.

The target is approximately 2,000 always-loaded tokens on a realistic fictional
sample, not a promise that arbitrary amounts of routing information fit in
2,000 tokens. Details remain ordinary local documents. Runtime code remains
standard-library-only; the existing optional MCP dependency remains optional.

## Ideal state, current gaps, and acceptance

| Ideal property and reason | Current gap | Observable acceptance |
| --- | --- | --- |
| Every INDEX entry is always present, including after restart or host context rebuilding. A forgotten pointer makes its rule effectively disappear. | `VaultMemory.render()` caps all notes and only includes summaries; startup reads only caller-supplied paths. | More than 10 entries survive `render(limit=0)`, `StartupReader.read([])`, a new reader, MCP initialization/startup, and Hermes system-prompt rebuilding. |
| The INDEX is durable state, never a ranked result or disposable cache. | `.mnemosyne-index.json.z` is a rebuildable BM25 cache, not this feature. | Search-index rebuild, TTL purge, rezone, curation, consolidation, and review recovery leave routing state byte-identical. |
| Capacity pressure is visible but cannot remove entries. | Existing budgets count protected notes and bytes, not startup tokens. | A one-token INDEX budget returns every entry with an explicit warning; no successful partial INDEX exists. |
| Details are loaded only when requested. | Search/get-note exist, but no first-class trigger-to-document relation exists. | Exact trigger opens the referenced document; unmatched trigger uses ordinary search; an unrelated query returns no documents. |
| Every moved rule remains reachable. | No migration coverage or routing-integrity checker exists. | Source bytes reconstruct exactly from topic documents; each original source line has a coverage row; missing topics and unreferenced documents are reported. |
| Existing integrations and stores continue working. | New behavior must not silently reinterpret old notes. | No routing directory means unchanged legacy startup, digest, search, and mutation behavior. |
| Claims can be reproduced without private data or new model calls. | Frozen dual-author fixtures exist, but no trigger-index runner exists. | Immutable fixture checks pass; separate author scores, token denominators, and every regression are published. |

## Never-droppable invariant

The owner's explicit requirement is: **the INDEX must never be lost or
dropped**. This is a design invariant, not an optimization target.

1. Every registered entry is included in each managed always-loaded surface.
   No top-k, TTL, note limit, token budget, summarization, or compaction may
   select a subset. A host rebuilding its context must reinsert the complete
   INDEX through the same startup/system-prompt surface.
2. Over-budget reads return the complete INDEX with a warning. Malformed or
   missing enabled state fails loudly. Neither case falls back to an empty
   INDEX or an apparently successful partial result.
3. Generic note writes, deletion, rezoning, archiving, consolidation, and
   review undo do not own routing state. The dedicated API is additive:
   adding the same mapping is idempotent; it exposes no remove, clear,
   replacement, expiry, or automatic-retirement operation.
4. Startup verification reconstructs the complete rendered INDEX from fresh
   durable state. Removing even one entry from returned context fails
   verification, even if the caller rewrites the returned certificate.
5. Tests also deliberately mutate the renderer to omit an entry and prove
   that the completeness test fails. Restoring the implementation restores
   the passing test.

The library can enforce its own storage and context surfaces, not prevent an
external filesystem owner from deleting an entire vault or a host from
ignoring its system-prompt contract. An explicit `required=True` reader mode
fails if even the feature marker is missing; hosts can retain this requirement
outside the vault. These limits are documented rather than presented as
protection against arbitrary external destruction.

## Smallest compatible storage

Add `birkin_mnemosyne/memory_index.py` and a public `MemoryIndex` API.
Use a dedicated `.mnemosyne-memory-index/` directory containing `index.json`.
The directory is the persistent opt-in marker; its presence with missing or
invalid `index.json` is an error. Existing stores without the directory are
disabled and are not modified by reads.

The version-1 JSON record contains a positive `max_tokens` budget (default
2,000) and an ordered array of `{trigger, document}` entries. Entries use
nonempty single-line triggers and canonical vault-relative document paths.
Registration accepts a relative path or an existing note identifier; note
identifiers are resolved to a path before storage. A trigger may point to
several documents. Exact duplicate mappings are idempotent. Ordering is
insertion ordering, not usage ranking.

This state is deliberately not a Markdown note. The existing scanners skip
dot-directories, and review-journal mutations only accept Markdown paths.
Consequently it cannot accidentally acquire a TTL, be chosen as a retirement
candidate, be rewritten through note frontmatter, or disappear during a
search-cache rebuild. Public path validation rejects hidden state as a target.

Reads reread the authoritative JSON, never a cached summary. Updates use the
existing `VaultLock` and atomic replacement helper. Validate input, existing
state, target confinement, and the full proposed entry set before writing.
No new database, tokenizer, embedding model, daemon, or compatibility layer is
needed.

## Always-loaded surfaces and budget

`MemoryIndex.render()` emits one compact deterministic block with the complete
entry set and instructions to open details on demand. It is independent of
`VaultMemory.render(limit=...)`'s ordinary-note limit and is prepended to that
digest, including when no ordinary note is selected.

`StartupReader` includes this block as a distinguished generated source in
the existing byte/line coverage payload, then includes any explicitly
requested source closure exactly as before. This preserves the meaning of
legacy complete reads: registering a document does not make it a `MUST READ`
startup dependency. Empty requested paths are allowed only when an enabled
INDEX itself provides startup material. The verifier compares against freshly
rendered state; generated source identity cannot collide with a caller path.

MCP initialization instructions, the digest resource, and
`memory_startup_read` include the complete vault INDEX. If `identity_root`
differs from the vault, startup sources still come from the identity root but
the INDEX comes from the vault. Hermes `system_prompt_block()` similarly
rebuilds the complete INDEX independently of search prefetch. Integrators must
use these surfaces again after their own context compaction.

Runtime accounting is explicitly an **estimate**:
`ceil(len(text.encode("utf-8")) / 4)`, including the rendered instructions and
any over-budget warning. The capacity report adds the enabled state, entry
count, always-loaded INDEX estimate, configured budget, estimator name, and
over-budget state. Existing note/byte counts keep their meanings. Arbitrary
caller-supplied startup files are not misreported as part of this fixed cost;
the startup result separately reports its whole returned-context estimate.

An over-budget read keeps all entries. Warnings never recommend retiring the
INDEX. A byte or file safety bound in the complete startup reader may still
fail the entire read, but must never trim the INDEX to claim success.

## On-demand API and MCP

`MemoryIndex.open(query, limit=3)` returns complete UTF-8 document content and
relative paths, with `matched_by` distinguishing exact/lexical trigger matches,
ordinary search fallback, and no result. The exact trigger is the reliable
agent-facing interface. Lexical matching is a convenience, not a claim of
semantic understanding. Ties follow registration order; duplicates are read
once. Fallback reuses the existing BM25 search, not a second retrieval engine.

Only the query participates in routing. Expected answers, section labels, and
gold document identifiers are never routing inputs in the natural-language
evaluation. Invalid paths, paths outside the root, hidden files, malformed
state, and unreadable explicitly matched targets produce errors rather than
an unrelated successful fallback.

Expose thin MCP tools for registration, complete INDEX reading, and on-demand
opening. Registration is opt-in and returns the complete updated INDEX.
Read/open tools expose ordinary structured results; they do not execute
instructions stored in memory. The core API works without MCP installed.

## Integrity and lossless splitting

Add `memory_index_migration.py` for the checker and migration helper rather
than growing the storage class into a general migration framework.

The checker reports:

- entries whose target is missing or cannot be read safely;
- visible topic/note documents with no entry (orphans, reported separately
  from archived and hidden implementation state);
- migration coverage failures when recorded original bytes do not reconstruct
  exactly from their mapped topic ranges.

A split operates on an explicitly named UTF-8 startup file. Boundaries are
complete Markdown sections outside fenced examples, preserving the preamble,
BOM, CRLF, blank lines, heading ancestry, and final non-newline text. No model
summarizes or paraphrases content. Default triggers derive only from headings;
callers may supply clearer explicit triggers. JSON or unsectioned material is
kept as a whole topic, never guessed into fragments.

The preview describes every output and gives a coverage table mapping each
original line (a stronger mechanical guarantee than guessing which prose is
a rule) to its topic path and source byte range. Applying is explicit. It
refuses existing destination collisions, preserves a byte-exact original
backup and machine-readable coverage receipt outside startup context, writes
and verifies all topic files, registers every mapping, and only then replaces
the old always-loaded source with a compact routing notice. Reconstruct and
compare the original bytes before replacing that source. An interrupted
operation therefore retains the original until its replacements and INDEX
are durable; failures are visible and no source text is silently discarded.

The CLI prints the coverage table; API/MCP return the same structured rows.
No automatic semantic "rule extraction" or destructive deletion is provided.

## Measurement protocol frozen before implementation

Use fictional material only. The realistic cost sample has an approximately
10K-token memory note, 8K-token manual, and 21K-token handoff, distributed among
named topic sections. Report actual sizes rather than claiming the generated
sample hits an exact token count. Compare the complete previous startup
payload with the complete INDEX-based payload. The 2K target applies to the
new always-loaded payload in this scenario.

Use benchmark-only `tiktoken` with `o200k_base` for measured BPE counts, plus
characters, UTF-8 bytes, and the runtime estimate. This encoding is not a claim
about GPT/Claude billing. It is not imported by production code.

Reuse existing separately authored question sets and scorers without edits:

- GPT-6.1 Sol: `benchmarks/round3/frozen_sol.json`, identity slice, 12 questions.
- Claude Opus: `benchmarks/round3/frozen_claude_identity.json`, 12 questions.
- Both use unchanged `benchmarks/round3/answerer.py`.
- Pin and validate the existing `benchmarks/round4/frozen-manifest.json`.

Claude authored its existing fictional set before this task. Replaying it
respects the prohibition on new Claude calls. Provenance is the repository's
recorded authorship, not a newly authenticated authoring session.

For each author, before uses the full original document. After creates topics
and triggers from document headings only, routes only the frozen `query`, and
passes the actual loaded context to the unchanged answerer. Fix the routing
algorithm before running these questions and do not tune it against failures.
Report exact counts, positive-answer and abstention counts, regressions,
improvements, selected paths, context hashes, always-loaded tokens, additional
loaded tokens, and combined task tokens. These are reused public fixtures and
constrained extraction, not proof of general agent compliance.

An accuracy gain is claimed only if both sets improve. Full reads may already
score 100%; preserved accuracy plus lower startup cost is a cost improvement,
not an accuracy improvement. If one author regresses, disclose it separately;
never hide it in a pooled average. The frozen complete-startup tests remain
legacy compatibility checks; partial reads are not relabelled as complete
startup or comprehensive rule compliance.

## Delivery and QA

Three focused PRs, each passing the repository's full 21-job OS/Python/extra
matrix, independently reviewed by GPT-6.1 Sol on its exact head, with no
unresolved blocking comments before merge:

1. Durable INDEX, startup/digest/host integration, capacity, on-demand API/MCP,
   and never-droppable regression tests.
2. Integrity checker and lossless split/coverage helper with interruption and
   preservation tests.
3. Reproducible fictional measurements, frozen dual-author evaluation, usage
   documentation, and evidence.

No version bump, release, or PyPI publication.

Run `python -m pytest -q` for each verified increment. Targeted test homes are
`test_memory_index.py`, `test_memory_index_migration.py`, `test_startup.py`,
`test_capacity.py`, `test_mcp_server.py`, and `test_host_adapters.py`.
Manually exercise the public library and real MCP stdio process against a
temporary fictional vault. Capture outputs and remove that vault afterwards.

Required adversarial scenarios: entry-drop mutation; empty and malformed
state; enabled-but-missing state; one-token budget; digest limit zero;
same-length external edits; restart; Unicode paths/triggers; path traversal
and symlink escape; multi-document trigger; irrelevant-query fallback;
ordinary lifecycle operations; complete split reconstruction; destination
collision; write interruption; dangling and orphan reports. No test may depend
on a fixed sleep or successful timing luck.

Baseline on the untouched release: `859 passed, 2 skipped` with MCP installed.
The two skips are the optional semantic/static-model suites absent from the
local environment; CI separately exercises those extras on all three OSes.
